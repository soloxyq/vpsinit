#!/usr/bin/python3 -I
"""Verify the running UID 1006 proxy without changing its switch state.

Run as root in the host network namespace with --baseline HOST-BEFORE.json.
The baseline uses the original xq-tun verify.py --snapshot format. By default
only the already-ON service is tested; no firewall or switch is changed.
Explicit --exercise-switches also tests stopping this core, OFF, and ON again.
If that stop test fails, only the core stopped by the test is started again;
the guard is retained. There is no automatic OFF or timed rollback. The
independent xq-tun.service is never stopped. No unprotected target-user public
request is made.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time

CTL = '/usr/local/sbin/xq-user-proxyctl'
SERVICE = 'xq-user-proxy.service'
OLD_SERVICE = 'xq-tun.service'
IP = '/usr/sbin/ip'
NFT = '/usr/sbin/nft'
SYSTEMCTL = '/usr/bin/systemctl'
ENV ={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}
TABLE = 'xq_user_proxy'
SAFETY_TABLE = 'xq_user_proxy_verify'
TUN = 'xq-utun'
ROUTE_TABLE = 20261
PRIORITY = 18410
ROUTE_BIT = 0x40000000
CONFIG = Path('/etc/xq-user-proxy/sing-box.json')


def checked_interface(value):
    # Names are later included in nft source as a quoted string. Reject shell/
    # nft metacharacters as well as names too long for a Linux interface.
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,14}', value)
            or value in ('lo', TUN)):
        raise RuntimeError('Expected a valid upstream transport interface name')
    return value


def discover_network():
    installed = json.loads(CONFIG.read_text())
    upstreams = [outbound for outbound in installed.get('outbounds', [])
                 if outbound.get('tag') == 'upstream' and outbound.get('type') == 'socks']
    if len(upstreams) != 1:
        raise RuntimeError('Expected one installed SOCKS outbound tagged upstream')
    upstream = upstreams[0]
    proxy_host = str(ipaddress.IPv4Address(upstream['server']))
    proxy_port = upstream['server_port']
    if type(proxy_port) is not int or not 1 <= proxy_port <= 65535:
        raise RuntimeError('Invalid installed upstream port')
    routes = json.loads(run([IP, '-j', '-4', 'route', 'get', proxy_host]))
    if len(routes) != 1 or routes[0].get('type', 'unicast') != 'unicast':
        raise RuntimeError('Expected a single unicast IPv4 route to the upstream')
    route = routes[0]
    host = str(ipaddress.IPv4Address(route.get('prefsrc') or route.get('src')))
    interface = checked_interface(route.get('dev'))
    resolver = None
    for line in Path('/etc/resolv.conf').read_text().splitlines():
        fields = line.split('#', 1)[0].split(';', 1)[0].split()
        if len(fields) >= 2 and fields[0] == 'nameserver':
            try:
                address = ipaddress.IPv4Address(fields[1])
            except ipaddress.AddressValueError:
                continue
            resolver = str(address)
            break
    if resolver is None:
        raise RuntimeError('System resolver configuration has no usable IPv4 nameserver')
    return host, interface, resolver, proxy_host, proxy_port


def resolver_policy(resolver):
    """Describe the configured resolver using the installed LAN exception set."""
    address = ipaddress.IPv4Address(resolver)
    data = json.loads(run([NFT, '--json', 'list', 'set', 'inet', TABLE, 'lan_v4']))
    sets = [item['set'] for item in data.get('nftables', []) if 'set' in item
            and item['set'].get('name') == 'lan_v4' and item['set'].get('table') == TABLE]
    if len(sets) != 1:
        raise RuntimeError('Cannot inspect the installed IPv4 LAN DNS exception set')
    for element in sets[0].get('elem', []):
        if isinstance(element, dict) and 'elem' in element:
            element = element['elem']['val']
        if isinstance(element, str):
            matches = address in ipaddress.ip_network(element, strict=False)
        elif isinstance(element, dict) and 'prefix' in element:
            prefix = element['prefix']
            matches = address in ipaddress.ip_network(f'{prefix["addr"]}/{prefix["len"]}', strict=False)
        elif isinstance(element, dict) and 'range' in element:
            first, last = map(ipaddress.IPv4Address, element['range'])
            matches = first <= address <= last
        else:
            raise RuntimeError('Unrecognized installed LAN exception element')
        if matches:
            return 'LAN DNS exception: may remain available while the proxy core is stopped'
    return 'UID DNS interception: the configured resolver is outside the installed LAN exceptions'


def run(argv, *, data=None, timeout=40):
    result = subprocess.run(argv, env=ENV, input=data, text=True,
                            capture_output=True, close_fds=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{argv[0]} failed ({result.returncode}): '
                           + result.stderr.strip() + ' ' + result.stdout.strip())
    return result.stdout


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def without_counters(value):
    if isinstance(value, list):
        return [without_counters(item) for item in value]
    if isinstance(value, dict):
        return {key: (without_counters({k: v for k, v in item.items()
                                       if k not in ('packets', 'bytes')})
                      if key == 'counter' and isinstance(item, dict)
                      else without_counters(item)) for key, item in value.items()}
    return value


def snapshot():
    result = {}
    for family in ('-4', '-6'):
        for kind, tail in (('route', ['show', 'table', 'all']), ('rule', ['show'])):
            values = json.loads(run([IP, '-j', family, kind, *tail]))
            result[family + kind] = sorted(values, key=canonical)
    resolver = Path('/etc/resolv.conf')
    result['resolver'] = {
        'link': os.readlink(resolver) if resolver.is_symlink() else None,
        'content_sha256': hashlib.sha256(resolver.read_bytes()).hexdigest(),
    }
    rules = json.loads(run([NFT, '--stateless', '--json', 'list', 'ruleset']))
    result['nftables'] = [r for r in rules.get('nftables', []) if 'metainfo' not in r]
    result['forwarding'] = {
        str(path): path.read_text().strip() for path in
        (Path('/proc/sys/net/ipv4/ip_forward'), Path('/proc/sys/net/ipv6/conf/all/forwarding'))
        if path.exists()
    }
    return result


def number(value):
    return int(value, 0) if isinstance(value, str) else int(value)


def owned_route(route, family):
    if str(route.get('table')) == str(ROUTE_TABLE):
        if route.get('dst') != 'default':
            return False
        if family == '-4':
            return ((route.get('type') == 'blackhole' and route.get('metric') == 32760)
                    or (route.get('dev') == TUN and route.get('metric') == 10
                        and route.get('type', 'unicast') == 'unicast'))
        return route.get('type') == 'unreachable' and route.get('metric') == 32760
    return (family == '-4' and route.get('table') in ('local', 255)
            and route.get('dev') == TUN and route.get('type') == 'local'
            and route.get('dst') in ('172.30.254.1', '172.30.254.1/32'))


def owned_rule(rule):
    return (rule.get('priority') == PRIORITY
            and str(rule.get('table')) == str(ROUTE_TABLE)
            and number(rule.get('fwmark', 0)) == ROUTE_BIT
            and number(rule.get('fwmask', 0)) == ROUTE_BIT
            and rule.get('src', 'all') == 'all' and rule.get('dst', 'all') == 'all'
            and not rule.get('flags')
            and not set(rule) - {'priority', 'table', 'fwmark', 'fwmask', 'src', 'dst', 'protocol', 'flags'})


def strip_owned(value):
    result = json.loads(json.dumps(value))
    for family in ('-4', '-6'):
        result[family + 'route'] = [r for r in result[family + 'route'] if not owned_route(r, family)]
        result[family + 'rule'] = [r for r in result[family + 'rule'] if not owned_rule(r)]
    result['nftables'] = [entry for entry in result['nftables']
                         if not any(isinstance(obj, dict) and obj.get('family') == 'inet'
                                    and (obj.get('table') == TABLE
                                         or kind == 'table' and obj.get('name') == TABLE)
                                    for kind, obj in entry.items())]
    return result


def compare_baseline(before, *, on, destination):
    after = snapshot()
    destination.write_text(json.dumps(after, indent=2) + '\n')
    compared = strip_owned(after) if on else after
    changes = [key for key in before if without_counters(before[key]) != without_counters(compared.get(key))]
    if changes:
        raise RuntimeError('Unexpected host baseline difference: ' + ', '.join(changes)
                           + '. Review snapshots; concurrent administrator/Docker changes can also differ.')


WORKER = r'''
import ipaddress,json,os,selectors,socket,struct,subprocess,sys,threading
config=json.loads(sys.argv[1])
stop=threading.Event()
sockets=[]
ports={}
token=config['token'].encode()

def serve(kind):
    s=socket.socket(socket.AF_INET,kind)
    s.bind((config['host'],0)); s.settimeout(.2)
    if kind==socket.SOCK_STREAM: s.listen(8)
    sockets.append(s)
    ports['tcp' if kind==socket.SOCK_STREAM else 'udp']=s.getsockname()[1]
    def loop():
        while not stop.is_set():
            try:
                if kind==socket.SOCK_STREAM:
                    c,_=s.accept()
                    with c:
                        c.settimeout(2); c.recv(4096)
                        c.sendall(b'HTTP/1.0 200 OK\r\nContent-Length: '+str(len(token)).encode()+b'\r\n\r\n'+token)
                else:
                    data,peer=s.recvfrom(4096)
                    if data==token: s.sendto(token,peer)
            except (OSError,TimeoutError): pass
    threading.Thread(target=loop,daemon=True).start()

def exact(s,n):
    data=b''
    while len(data)<n:
        part=s.recv(n-len(data))
        if not part: raise OSError('Unexpected EOF')
        data+=part
    return data

def dns(tcp=False, successful=True, server=None, port=53):
    tx=os.urandom(2)
    packet=tx+bytes.fromhex('01000001000000000000076578616d706c6503636f6d0000010001')
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
        s.settimeout(4); s.connect((server or config['resolver'],port))
        if tcp:
            s.sendall(struct.pack('!H',len(packet))+packet)
            answer=exact(s,struct.unpack('!H',exact(s,2))[0])
        else:
            s.send(packet); answer=s.recv(4096)
    if len(answer)<12 or answer[:2]!=tx or not answer[2]&128:
        raise ValueError('Invalid DNS response')
    if successful and (answer[3]&15 or struct.unpack('!H',answer[6:8])[0]<1):
        raise ValueError('DNS query failed')

def curl(url, interface=None):
    args=['/usr/bin/curl','--disable','--fail','--silent','--show-error','--proxy','',
          '--noproxy','*','--connect-timeout','3','--max-time','8']
    if interface: args+=['--interface',interface]
    return subprocess.run(args+[url],capture_output=True,text=True,timeout=10)

def identity():
    fields={}
    for line in open('/proc/self/status'):
        key,_,value=line.partition(':')
        if key in ('CapEff','CapPrm','CapInh','CapAmb','NoNewPrivs'): fields[key]=value.strip()
    return dict(pid=os.getpid(),uid=os.getuid(),gid=os.getgid(),netns=os.readlink('/proc/self/ns/net'),
                security=fields,ports=ports,resolver=open('/etc/resolv.conf').read())

if config['serve']:
    serve(socket.SOCK_STREAM); serve(socket.SOCK_DGRAM)
print(json.dumps(identity()),flush=True)
try:
    for line in sys.stdin:
        request=json.loads(line); op=request['op']
        if op=='exit': break
        try:
            result={'ok':True}
            if op=='identity': result.update(identity())
            elif op=='local':
                expected=request['token'].encode()
                with socket.create_connection((config['host'],request['tcp']),timeout=3) as s:
                    s.settimeout(3); s.sendall(b'GET / HTTP/1.0\r\n\r\n'); answer=b''
                    while True:
                        chunk=s.recv(4096)
                        if not chunk: break
                        answer+=chunk
                if not answer.endswith(b'\r\n\r\n'+expected): raise ValueError('Local HTTP mismatch')
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
                    s.settimeout(3); s.connect((config['host'],request['udp'])); s.send(expected)
                    if s.recv(4096)!=expected: raise ValueError('Local UDP mismatch')
                result.update(http=True,udp=True)
            elif op in ('dns','online'):
                dns(False); dns(True)
                if not socket.getaddrinfo('example.com',443,socket.AF_INET,socket.SOCK_STREAM):
                    raise ValueError('libc DNS returned no addresses')
                result.update(dns_udp=True,dns_tcp=True,libc_dns=True)
                if op=='online':
                    response=curl('https://api.ipify.org')
                    if response.returncode: response=curl('https://icanhazip.com')
                    if response.returncode: raise RuntimeError('HTTPS failed: '+response.stderr.strip())
                    result['public_ip']=str(ipaddress.IPv4Address(response.stdout.strip()))
            elif op=='blocked':
                response=curl('https://1.1.1.1/',config['interface'])
                if response.returncode not in (7,28):
                    raise RuntimeError('Expected network refusal/timeout, curl code='+str(response.returncode))
                for tcp in (False,True):
                    # A configured LAN nameserver legitimately remains direct.
                    # Test this core's own listener, not that unrelated service.
                    try: dns(tcp,False,'127.0.0.1',1053)
                    except OSError: pass
                    else: raise RuntimeError('DNS replied while core was stopped')
                result.update(bound_tcp_blocked=True,core_dns_listener_blocked=True)
            else: raise ValueError('Unknown worker operation')
            print(json.dumps(result),flush=True)
        except Exception as exc:
            print(json.dumps({'ok':False,'error':str(exc)}),flush=True)
finally:
    stop.set()
    for s in sockets: s.close()
'''


class Worker:
    def __init__(self, uid, host, resolver, *, interface, serve=False):
        self.token = os.urandom(24).hex()
        gid = uid
        config = {'host': host, 'resolver': resolver, 'serve': serve, 'token': self.token,
                  'interface': checked_interface(interface)}
        command = ['/usr/bin/setpriv', '--reuid', str(uid), '--regid', str(gid),
                   '--clear-groups', '--inh-caps=-all', '--ambient-caps=-all',
                   '--bounding-set=-all', '--no-new-privs', '--',
                   '/usr/bin/python3', '-I', '-u', '-c', WORKER, json.dumps(config)]
        self.process = subprocess.Popen(command, env=ENV, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True, bufsize=1, close_fds=True)
        try:
            self.identity = self.response()
            security = self.identity['security']
            if (self.identity['uid'] != uid or self.identity['gid'] != gid
                    or self.identity['netns'] != os.readlink('/proc/self/ns/net')
                    or self.identity['resolver'] != Path('/etc/resolv.conf').read_text()
                    or security['NoNewPrivs'] != '1'
                    or any(int(security[k], 16) for k in ('CapEff', 'CapPrm', 'CapInh', 'CapAmb'))):
                raise RuntimeError('Worker identity, namespace, permissions or resolver mismatch')
        except BaseException:
            self.close()
            raise

    def response(self):
        with selectors.DefaultSelector() as poll:
            poll.register(self.process.stdout, selectors.EVENT_READ)
            if not poll.select(45):
                raise RuntimeError('Worker response timed out')
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('Worker exited before responding')
        result = json.loads(line)
        if result.get('ok') is False:
            raise RuntimeError(result['error'])
        return result

    def ask(self, operation, **values):
        self.process.stdin.write(json.dumps({'op': operation, **values}) + '\n')
        self.process.stdin.flush()
        return self.response()

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('{"op":"exit"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None: stream.close()


def old_service_state():
    return run([SYSTEMCTL, 'show', OLD_SERVICE, '-p', 'ActiveState', '-p', 'MainPID'])


def core_pid():
    return int(run([SYSTEMCTL, 'show', SERVICE, '-p', 'MainPID', '--value']).strip())


def ready():
    for _ in range(60):
        try:
            run([CTL, 'check'], timeout=10)
            return
        except RuntimeError:
            time.sleep(.25)
    raise RuntimeError('User proxy did not become ready')


def safety_guard(interface):
    interface_literal = json.dumps(checked_interface(interface))
    existing = json.loads(run([NFT, '--json', 'list', 'tables']))
    if any(entry.get('table', {}).get('name') == SAFETY_TABLE
           and entry.get('table', {}).get('family') == 'inet' for entry in existing.get('nftables', [])):
        raise RuntimeError('Safety-test table name already exists; refusing to overwrite')
    source = f'''table inet {SAFETY_TABLE} {{
  chain output {{
    type filter hook postrouting priority 200; policy accept;
    meta skuid 1006 ct direction original oifname {interface_literal} ip daddr 1.1.1.1 tcp dport 443 counter drop
  }}
}}
'''
    run([NFT, '--check', '-f', '-'], data=source)
    run([NFT, '-f', '-'], data=source)


def safety_hits():
    data = json.loads(run([NFT, '--json', 'list', 'table', 'inet', SAFETY_TABLE]))
    return sum(expression['counter']['packets'] for entry in data.get('nftables', [])
               for expression in entry.get('rule', {}).get('expr', []) if 'counter' in expression)


def verify(baseline, *, exercise_switches=False):
    before = json.loads(baseline.read_text())
    required = {'-4route', '-6route', '-4rule', '-6rule', 'resolver', 'nftables', 'forwarding'}
    if set(before) != required or strip_owned(before) != before:
        raise RuntimeError('Expected a pre-install host snapshot without this feature resources')
    host, interface, resolver, proxy_host, proxy_port = discover_network()
    unchanged_old = old_service_state()
    workers = []
    safety_installed = False
    stopped_by_test = False
    success = False
    try:
        if exercise_switches:
            run([CTL, 'on'], timeout=80)
        else:
            # This is a read-only readiness check. Live validation must not
            # turn an OFF/broken service on or replace firewall rules.
            run([CTL, 'check'])
        ready()
        initial_core_pid = core_pid()
        if initial_core_pid <= 0:
            raise RuntimeError('The user proxy has no running core PID')
        print('Network evidence: ' + canonical({'host_ip': host, 'interface': interface,
              'upstream': f'{proxy_host}:{proxy_port}', 'configured_ipv4_resolver': resolver,
              'resolver_policy': resolver_policy(resolver)}), flush=True)
        compare_baseline(before, on=True, destination=baseline.with_name('host-user-on.json'))
        for uid, serve in ((0, True), (65534, False), (1006, True)):
            workers.append(Worker(uid, host, resolver, interface=interface, serve=serve))
        root, other, target = workers
        target_identity = target.identity

        def unaffected(label):
            for client in (root, other):
                client.ask('local', token=root.token, **root.identity['ports'])
                client.ask('dns')
            root.ask('local', token=target.token, **target.identity['ports'])
            if old_service_state() != unchanged_old:
                raise RuntimeError('Independent xq-tun service state/PID changed')
            if not exercise_switches and core_pid() != initial_core_pid:
                raise RuntimeError('Core PID changed during live validation; no recovery was attempted')
            print('PASS: ' + label + ': root/UID65534 local HTTP+UDP and DNS; UID1006 service local replies', flush=True)

        print('PASS: UID1006 stays in host namespace; proxy-free HTTPS and configured DNS: '
              + canonical(target.ask('online')), flush=True)
        newcomer = Worker(1006, host, resolver, interface=interface)
        workers.append(newcomer)
        print('PASS: a new UID1006 process automatically uses the proxy: '
              + canonical(newcomer.ask('online')), flush=True)
        newcomer.close()
        workers.remove(newcomer)
        unaffected('ON')

        if not exercise_switches:
            unaffected('live final ON')
            compare_baseline(before, on=True, destination=baseline.with_name('host-user-final-on.json'))
            if core_pid() != initial_core_pid:
                raise RuntimeError('Core PID changed during live validation')
            success = True
            print('Live verification complete; core PID unchanged. No core stop, OFF/ON switch, '
                  'or nftables change was performed; outage/OFF restoration was not tested.', flush=True)
            return

        safety_guard(interface)
        safety_installed = True
        # Record our stop attempt before waiting, so a timeout after systemd
        # accepted the stop also restores this core without releasing its guard.
        stopped_by_test = True
        run([SYSTEMCTL, 'stop', SERVICE])
        run([NFT, 'list', 'table', 'inet', TABLE])
        print('PASS: stopped-core target test: ' + canonical(target.ask('blocked')), flush=True)
        if safety_hits():
            raise RuntimeError('Primary guard missed packets; independent test guard prevented direct public traffic')
        unaffected('core stopped')
        run([NFT, 'delete', 'table', 'inet', SAFETY_TABLE])
        safety_installed = False
        run([SYSTEMCTL, 'start', SERVICE], timeout=80)
        ready()
        stopped_by_test = False
        print('PASS: core recovery: ' + canonical(target.ask('online')), flush=True)

        run([CTL, 'off'], timeout=80)
        compare_baseline(before, on=False, destination=baseline.with_name('host-user-off.json'))
        after_identity = target.ask('identity')
        if any(after_identity[key] != target_identity[key] for key in ('pid', 'uid', 'gid', 'netns')):
            raise RuntimeError('OFF changed the existing user process identity/namespace')
        # Only local controlled endpoints and the existing resolver are used OFF.
        target.ask('local', token=root.token, **root.identity['ports'])
        target.ask('dns')
        unaffected('OFF')
        print('PASS: OFF restores host baseline and preserves the existing user process/netns', flush=True)

        run([CTL, 'on'], timeout=80)
        ready()
        print('PASS: ON again: ' + canonical(target.ask('online')), flush=True)
        unaffected('final ON')
        compare_baseline(before, on=True, destination=baseline.with_name('host-user-final-on.json'))
        success = True
        print('Verification complete; UID1006 proxy remains ON; independent xq-tun.service untouched.', flush=True)
    finally:
        try:
            for worker in reversed(workers):
                worker.close()
        finally:
            try:
                if stopped_by_test:
                    print('Restoring only the core stopped by this explicit test; guard retained.', file=sys.stderr)
                    run([SYSTEMCTL, 'start', SERVICE], timeout=80)
                    ready()
            finally:
                try:
                    if safety_installed:
                        run([NFT, 'delete', 'table', 'inet', SAFETY_TABLE])
                finally:
                    if not success:
                        print('Verification failed; no automatic OFF or direct-network restoration.', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--baseline', type=Path)
    mode.add_argument('--snapshot', type=Path)
    parser.add_argument('--exercise-switches', action='store_true',
                        help='Explicitly test stopping this core and switching OFF/ON; interrupts UID1006 public traffic')
    args = parser.parse_args()
    if args.snapshot and args.exercise_switches:
        parser.error('--exercise-switches requires --baseline')
    current, host = os.stat('/proc/self/ns/net'), os.stat('/proc/1/ns/net')
    if os.geteuid() != 0 or (current.st_dev, current.st_ino) != (host.st_dev, host.st_ino):
        parser.error('Run as root in the host network namespace')
    os.umask(0o077)
    if args.snapshot:
        args.snapshot.write_text(json.dumps(snapshot(), indent=2) + '\n')
        print('Saved host baseline: ' + str(args.snapshot))
    else:
        def interrupted(signum, _frame):
            raise RuntimeError('Verification interrupted by ' + signal.Signals(signum).name)
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        verify(args.baseline, exercise_switches=args.exercise_switches)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, StopIteration, RuntimeError, subprocess.SubprocessError) as error:
        print('Verification failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
