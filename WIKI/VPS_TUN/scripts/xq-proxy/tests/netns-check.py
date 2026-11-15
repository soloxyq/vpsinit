#!/usr/bin/python3 -I
"""Packet-level DNS regression tests in a fresh disposable network namespace.

Run: sudo unshare --net python3 -I tests/netns-check.py
The test refuses the host network and never calls controller lifecycle methods,
touches resolv.conf, or starts/stops a host service. Test sockets and processes
exist only in the caller-created namespace.
"""
import json
import os
from pathlib import Path
import runpy
import select
import socket
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parents[1]
IP = '/usr/sbin/ip'
NFT = '/usr/sbin/nft'
CORE_UID = 999
APP_UID = 23456
OTHER_UID = 23457
WSL_DNS = '10.255.255.254'
PUBLIC_DNS = '203.0.113.53'
HOST = '198.18.0.1'
TABLE = 'xq_proxy'


def run(args, *, data=None, check=True):
    r = subprocess.run(args, input=data, capture_output=True, text=True, timeout=15)
    if check and r.returncode:
        raise RuntimeError(f'{args!r}: exit {r.returncode}\n{r.stdout}\n{r.stderr}')
    return r.stdout


def read_line(process, timeout=4):
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    if not ready:
        raise RuntimeError('Probe/echo process did not respond within timeout')
    line = process.stdout.readline()
    if not line:
        raise RuntimeError('Probe/echo process exited: ' + process.stderr.read())
    return json.loads(line)


ECHO = r'''
import json,os,socket,sys,threading
uid,addr,port,label=sys.argv[1:]
os.setgroups([]); os.setgid(int(uid)); os.setuid(int(uid))
udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
udp.bind((addr,int(port)))
tcp=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
tcp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
tcp.bind((addr,int(port))); tcp.listen()
def udp_loop():
    while True:
        data,peer=udp.recvfrom(4096)
        udp.sendto(label.encode()+b':'+data,peer)
threading.Thread(target=udp_loop,daemon=True).start()
print(json.dumps({'ready':label}),flush=True)
while True:
    conn,peer=tcp.accept()
    with conn:
        conn.settimeout(2)
        data=conn.recv(4096)
        if data: conn.sendall(label.encode()+b':'+data)
'''

PROBE = r'''
import errno,json,os,socket,sys,time
uid,dest,port,tcp,source,sport,device,persistent=sys.argv[1:]
os.setgroups([]); os.setgid(int(uid)); os.setuid(int(uid))
s=socket.socket(socket.AF_INET,socket.SOCK_STREAM if int(tcp) else socket.SOCK_DGRAM)
s.settimeout(0.7)
if device != '-': s.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,device.encode()+b'\0')
if source != '-' or int(sport): s.bind(('0.0.0.0' if source == '-' else source,int(sport)))
connected=False
def probe():
    global connected
    result={}
    try:
        if not connected: s.connect((dest,int(port))); connected=True
        s.sendall(b'query')
        result['reply']=s.recv(4096).decode()
        result['peer']=s.getpeername()
    except OSError as exc:
        result.update(reply=None,error=type(exc).__name__,errno=exc.errno)
    result['source']=s.getsockname()
    return result
if int(persistent):
    print(json.dumps({'ready':True}),flush=True)
    for line in sys.stdin:
        if line.strip() == 'stop': break
        if line.strip() == 'drain_rejection':
            # An nft REJECT can fail send() immediately and also enqueue an
            # asynchronous ICMP error on this same connected UDP socket. Consume
            # only the known shutdown-stage error before testing restored DNS.
            time.sleep(0.1)
            errors=[]
            pending=s.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR)
            if pending: errors.append(pending)
            previous=s.gettimeout(); s.setblocking(False)
            try:
                while True:
                    try:
                        data=s.recv(4096)
                        raise RuntimeError('Unexpected successful DNS response during guard-only shutdown: '+repr(data))
                    except BlockingIOError: break
                    except OSError as exc: errors.append(exc.errno)
            finally: s.settimeout(previous)
            if any(code not in (errno.EPERM,errno.EACCES,errno.EHOSTUNREACH,errno.ENETUNREACH) for code in errors):
                raise RuntimeError('Unexpected pending socket error: '+repr(errors))
            print(json.dumps({'drained_rejection_errors':errors}),flush=True)
            continue
        print(json.dumps(probe()),flush=True)
else:
    print(json.dumps(probe()),flush=True)
s.close()
'''


def echo(uid, address, port, label):
    p = subprocess.Popen([sys.executable, '-I', '-u', '-c', ECHO, str(uid),
                          address, str(port), label], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    assert read_line(p) == {'ready': label}
    return p


def probe(uid, address, port=53, *, tcp=False, source='-', sport=0, device='-'):
    return json.loads(run([sys.executable, '-I', '-c', PROBE, str(uid), address,
                           str(port), str(int(tcp)), source, str(sport), device, '0']))


def expect(result, label, context):
    expected = None if label is None else label + ':query'
    assert result.get('reply') == expected, f'{context}: {result!r}, expected {expected!r}'


def reject_hits():
    data = json.loads(run([NFT, '-j', 'list', 'chain', 'inet', TABLE, 'output']))
    count = 0
    for item in data.get('nftables', []):
        expressions = item.get('rule', {}).get('expr', [])
        if any('reject' in expression for expression in expressions):
            count += sum(expression['counter']['packets']
                         for expression in expressions if 'counter' in expression)
    return count


class PersistentProbe:
    def __init__(self, uid, address, source):
        self.process = subprocess.Popen(
            [sys.executable, '-I', '-u', '-c', PROBE, str(uid), address, '53',
             '0', source, '0', '-', '1'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert read_line(self.process) == {'ready': True}

    def query(self):
        self.process.stdin.write('probe\n')
        self.process.stdin.flush()
        return read_line(self.process)

    def drain_rejection(self):
        self.process.stdin.write('drain_rejection\n')
        self.process.stdin.flush()
        result = read_line(self.process)
        print('Known guard-only socket errors consumed:', result, flush=True)
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.write('stop\n')
            self.process.stdin.flush()
            self.process.wait(timeout=3)


def main():
    if os.geteuid() != 0 or os.stat('/proc/self/ns/net') == os.stat('/proc/1/ns/net'):
        raise SystemExit('Refusing host network: use sudo unshare --net python3 -I tests/netns-check.py')
    interfaces = json.loads(run([IP, '-j', 'link', 'show']))
    if [item['ifname'] for item in interfaces] != ['lo']:
        raise SystemExit('Refusing a non-fresh namespace (expected only lo)')
    ctl = runpy.run_path(str(BASE / 'xq-proxyctl'))
    # A network namespace shares the host filesystem. Redirect every controller
    # file path to a private temporary directory, and reject unexpected disk
    # writes and commands even if a called helper changes in a future revision.
    with tempfile.TemporaryDirectory(prefix='xq-proxy-netns-test-') as directory:
        base = Path(directory)
        scope = ctl['guard_text'].__globals__
        paths = {
            'STATE': base / 'state',
            'STATEFILE': base / 'state' / 'state.json',
            'ENABLED': base / 'state' / 'enabled',
            'RESOLV': base / 'etc' / 'resolv.conf',
            'CONF': base / 'etc' / 'sing-box.json',
            'WSL_RESOLV': base / 'wsl' / 'resolv.conf',
        }
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        paths['STATE'].mkdir(exist_ok=True)
        paths['WSL_RESOLV'].write_text('nameserver ' + WSL_DNS + '\n')
        paths['RESOLV'].symlink_to(paths['WSL_RESOLV'])
        scope.update(paths)
        original_atomic, original_run = scope['atomic'], scope['run']

        def test_atomic(path, *args, **kwargs):
            if not Path(path).resolve().is_relative_to(base):
                raise AssertionError('Controller attempted a write outside test directory: ' + str(path))
            return original_atomic(path, *args, **kwargs)

        def test_run(args, **kwargs):
            if args[0] not in ('nft', NFT, '/usr/sbin/conntrack'):
                raise AssertionError('Unexpected controller command in network-only test: ' + repr(args))
            return original_run(args, **kwargs)

        scope.update(atomic=test_atomic, run=test_run)
        exercise(ctl)


def exercise(ctl):
    state = {'uid': CORE_UID, 'host': HOST, 'interface': 'test-wan', 'port': 4066}
    run([IP, 'link', 'set', 'lo', 'up'])
    run([IP, 'address', 'add', WSL_DNS + '/32', 'dev', 'lo'])
    for device in ('xq-tun', 'test-wan'):
        run([IP, 'link', 'add', device, 'type', 'dummy'])
        run([IP, 'link', 'set', device, 'up'])
    run([IP, 'address', 'add', '198.18.0.2/24', 'dev', 'test-wan'])
    run([IP, 'address', 'add', '172.30.255.1/30', 'dev', 'xq-tun'])
    run([IP, 'route', 'add', 'default', 'dev', 'test-wan'])
    run([IP, 'route', 'add', 'default', 'dev', 'xq-tun', 'table', '20260'])
    run([IP, 'rule', 'add', 'pref', '18400', 'iif', 'xq-tun', 'lookup', 'main'])
    run([IP, 'rule', 'add', 'pref', '18401', 'uidrange', f'{CORE_UID}-{CORE_UID}', 'lookup', 'main'])
    run([IP, 'rule', 'add', 'pref', '18402', 'lookup', '20260'])
    run([IP, '-6', 'route', 'add', 'unreachable', 'default', 'table', '20260'])
    run([IP, '-6', 'rule', 'add', 'pref', '18402', 'lookup', '20260'])
    assert json.loads(run([IP, '-j', 'route', 'get', WSL_DNS]))[0]['dev'] == 'lo'
    children = []
    persistent = None
    try:
        children.append(echo(0, WSL_DNS, 53, 'original-wsl'))
        children.append(echo(0, '127.0.0.53', 53, 'original-stub'))
        children.append(echo(0, '127.0.0.1', 18080, 'ordinary'))
        private = echo(CORE_UID, ctl['DNS_LISTEN'], ctl['DNS_PORT'], 'private')
        children.append(private)
        for active in (False, True):
            run([NFT, '--check', '-f', '-'], data=ctl['guard_text'](state, dns_active=active))
        ctl['install_guard'](state)

        # The original incident's source and destination are both 10.255.255.254.
        # Loopback stub and nonlocal DNS destinations exercise distinct reroutes.
        for uid in (0, APP_UID, OTHER_UID):
            for tcp in (False, True):
                for address, source in ((WSL_DNS, WSL_DNS),
                                        ('127.0.0.53', '127.0.0.2'),
                                        (PUBLIC_DNS, '-')):
                    result = probe(uid, address, tcp=tcp, source=source)
                    expect(result, 'private', f'DNS uid={uid} tcp={tcp} dst={address}')
                    assert result['peer'] == [address, 53], result
                expect(probe(uid, '127.0.0.1', 18080, tcp=tcp), 'ordinary', 'non-DNS loopback')
        print('PASS: TCP/UDP DNS works for all application UIDs, including exact WSL local tuple, loopback stub and public DNS; ordinary loopback unaffected', flush=True)

        for tcp in (False, True):
            expect(probe(0, WSL_DNS, tcp=tcp, source='127.0.0.2', sport=53),
                   'private', f'DNS reply to client port 53 tcp={tcp}')
            expect(probe(CORE_UID, WSL_DNS, tcp=tcp, source=WSL_DNS), None,
                   'core UID must not bypass guard or borrow application DNS')
        blocked_before = reject_hits()
        expect(probe(CORE_UID, '203.0.113.10', 443, tcp=True), None,
               'core UID arbitrary direct internet is blocked')
        assert reject_hits() > blocked_before, 'Core Internet probe did not hit the guard'
        print('PASS: client source port 53 replies work; core UID has no unrestricted DNS/Internet bypass', flush=True)

        first = probe(APP_UID, WSL_DNS, source=WSL_DNS)
        expect(first, 'private', 'first application tuple')
        expect(probe(CORE_UID, WSL_DNS, source=WSL_DNS, sport=first['source'][1]),
               None, 'core must not inherit application NAT tuple')
        core_first = probe(CORE_UID, WSL_DNS, source=WSL_DNS)
        expect(core_first, None, 'first core tuple')
        expect(probe(APP_UID, WSL_DNS, source=WSL_DNS, sport=core_first['source'][1]),
               'private', 'application must not inherit untranslated core tuple')
        print('PASS: reused UDP source ports cannot transfer DNS mappings between the core and applications in either direction', flush=True)

        persistent = PersistentProbe(APP_UID, WSL_DNS, WSL_DNS)
        initial = persistent.query()
        expect(initial, 'private', 'persistent socket before OFF')
        ctl['install_guard'](state, dns_active=False)
        ctl['delete_dns_connections']()
        # No new NAT should be created while the guard-only shutdown stage runs.
        expect(persistent.query(), None, 'guard-only shutdown stage')
        persistent.drain_rejection()
        run([NFT, 'delete', 'table', 'inet', TABLE])
        after_off = persistent.query()
        expect(after_off, 'original-wsl', 'same socket after OFF')
        assert after_off['source'] == initial['source']
        ctl['install_guard'](state)
        after_on = persistent.query()
        expect(after_on, 'private', 'same socket after ON')
        assert after_on['source'] == initial['source']
        print('PASS: one connected UDP socket and source port survives ON -> guarded shutdown -> OFF -> ON with the correct DNS server each time', flush=True)

        # Losing the private listener must not fall back to the still-running
        # original WSL resolver. Losing TUN must not allow physical direct traffic.
        private.terminate()
        private.wait(timeout=3)
        ctl['delete_dns_connections']()
        for tcp in (False, True):
            expect(probe(APP_UID, WSL_DNS, tcp=tcp, source=WSL_DNS), None,
                   'private DNS service loss must fail closed')
        run([IP, 'link', 'delete', 'xq-tun'])
        blocked_before = reject_hits()
        expect(probe(0, '203.0.113.10', 443, tcp=True, device='test-wan'), None,
               'TUN loss must not allow forced physical egress')
        assert reject_hits() > blocked_before, 'Physical egress probe did not hit the guard'
        run([NFT, 'list', 'table', 'inet', TABLE])
        print('PASS: DNS listener/TUN loss preserves the independent fail-closed guard', flush=True)
    finally:
        if persistent is not None:
            persistent.close()
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=3)


if __name__ == '__main__':
    main()
