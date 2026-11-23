#!/usr/bin/python3 -I
"""The real controller with the real sing-box core on a real kernel, inside a
fresh, disposable network namespace only.

    sudo unshare --net python3 -I tests/core-check.py --core /path/to/sing-box

netns-check.py exercises the generated rules against listeners that stand in
for the core, and against packets it writes into a TUN itself. This test runs
the controller's own on/off/status/check and lets them start and stop the core
itself, so it can observe what only a real core produces: DNS answered inside
the TUN, answers that arrive after the owner has closed its socket, a core that
is down while the guard stays, a core that still runs a configuration which
was edited on disk afterwards, connections a stopped core leaves behind, a core
that is replaced while an owner program keeps asking.

Three real identities take part: the owner, another user and root (the core).
A dummy interface stands for the uplink; nothing can answer there, and the
test's own counters say which socket every IPv4 packet on it came from. The
core runs the package's configuration with two substitutions made by this test:
it answers DNS from a fixed table instead of DoH, and its outbound is direct
instead of the SOCKS proxy, since the namespace reaches neither.

systemd is not available in a network namespace. The controller's systemctl
calls are answered by a stand-in that does what the unit says: ExecStartPre
(sing-box check, then prepare), ExecStart, ExecStartPost (attach), and
ConditionPathExists. Every other command the controller may run is ip, nft or
conntrack, which act on this namespace. The controller's files live in a
root-only directory below /run that is removed at the end; no host route, rule,
sysctl, service or DNS setting is touched. The one sysctl written besides those
of the test's own TUN, ip_unprivileged_port_start, is this namespace's own.
"""
import contextlib
import fcntl
import io
import ipaddress
import json
import os
from pathlib import Path
import runpy
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
OWNER = 23456   # Deliberately unrelated to any real account.
OTHER = 23457
IP = '/usr/sbin/ip'
NFT = '/usr/sbin/nft'
CONNTRACK = '/usr/sbin/conntrack'
SYSTEMCTL = '/usr/bin/systemctl'
SS = '/usr/bin/ss'
SERVICE = 'xq-user-proxy.service'
TABLE = 'xq_user_proxy'
TUN = 'xq-utun'
WAN = 'test-wan'
WAN_ADDRESS = '198.18.0.2'
ZONE = 20261
THRESHOLD = Path('/proc/sys/net/ipv4/ip_unprivileged_port_start')  # per network namespace
UPSTREAM = ('198.51.100.10', 1080)
# Resolvers of every class. Each stand-in answers with its own address record.
STUB, HOST_LOCAL, LAN, ANY = '127.0.0.53', '203.0.113.99', '10.77.0.53', '0.0.0.0'
PUBLIC = '203.0.113.53'      # not on this host: only the uplink or the TUN leads there
# A public address "from" which somebody sends this host a packet before the owner turns to it,
# the device such packets arrive by, and this host's address on it.
SEEDED, SEED_TAP, SEED_LOCAL = '203.0.113.81', 'xq-seed-tap', '198.18.2.2'
V6_LOOPBACK = '::1'
CORE_ANSWER, FORGED = '192.0.2.99', '192.0.2.66'
STAND_INS = {STUB: '192.0.2.53', HOST_LOCAL: '192.0.2.54', LAN: '192.0.2.55', '127.0.0.1': '192.0.2.56'}
NAME = 'probe.xq-core-check.test'
USAGE = 'sudo unshare --net python3 -I tests/core-check.py --core /path/to/sing-box'
REFUSALS = (RuntimeError, OSError, ValueError, KeyError)
CHILDREN = {}

IDENTITY = 'if uid != os.getuid(): os.setgroups([]);os.setgid(uid);os.setuid(uid)'

# A resolver that answers every query with one address record.
RESOLVER = r'''
import os,socket,struct,sys,threading
uid,address,port,answer=int(sys.argv[1]),sys.argv[2],int(sys.argv[3]),sys.argv[4]
''' + IDENTITY + r'''
def reply(query):
    end=12
    while query[end]: end+=query[end]+1
    return (query[:2]+b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00'+query[12:end+5]
            +b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04'+socket.inet_aton(answer))
udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind((address,port))
tcp=socket.socket();tcp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);tcp.bind((address,port));tcp.listen(32)
def udp_loop():
    while True:
        data,peer=udp.recvfrom(1500)
        try: udp.sendto(reply(data),peer)
        except Exception: pass
def serve(conn):
    with conn:
        try:
            conn.settimeout(3);size=struct.unpack('>H',conn.recv(2))[0];data=b''
            while len(data)<size: data+=conn.recv(size-len(data))
            out=reply(data);conn.sendall(struct.pack('>H',len(out))+out)
            while conn.recv(100): pass
        except Exception: pass
threading.Thread(target=udp_loop,daemon=True).start()
print('ready',flush=True)
while True:
    conn,_=tcp.accept();threading.Thread(target=serve,args=(conn,),daemon=True).start()
'''

# One DNS query as `uid`. Mode udp/tcp waits for the answer; udp-giveup/tcp-giveup
# closes the socket right after sending, as a timeout or a cancelled lookup does.
PROBE = r'''
import json,os,socket,struct,sys,time
uid,dest,port,mode,source,name=int(sys.argv[1]),sys.argv[2],int(sys.argv[3]),sys.argv[4],int(sys.argv[5]),sys.argv[6]
''' + IDENTITY + r'''
query=(struct.pack('>HHHHHH',0x1234,0x0100,1,0,0,0)
       +b''.join(bytes([len(label)])+label.encode() for label in name.split('.'))+b'\0'+struct.pack('>HH',1,1))
family=socket.AF_INET6 if ':' in dest else socket.AF_INET
tcp=mode.startswith('tcp')
result={'answer':None,'error':None,'source':0}
started=time.monotonic()
s=socket.socket(family,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM)
s.settimeout(1.5)
try:
    if source: s.bind(('::' if family==socket.AF_INET6 else '0.0.0.0',source))
    s.connect((dest,port))
    result['source']=s.getsockname()[1]
    s.sendall(struct.pack('>H',len(query))+query if tcp else query)
    if not mode.endswith('giveup'):
        if tcp:
            head=s.recv(2)
            if len(head)<2: raise ConnectionError('closed without an answer')
            data=b''
            while len(data)<struct.unpack('>H',head)[0]:
                chunk=s.recv(2048)
                if not chunk: raise ConnectionError('closed inside an answer')
                data+=chunk
        else:
            data=s.recv(1500)
        result['answer']=socket.inet_ntoa(data[-4:]) if not data[3]&15 and data[7] else 'rcode %d'%(data[3]&15)
except OSError as error:
    result['error']=type(error).__name__
    try: result['tried']=s.getsockname()[1]
    except OSError: pass
s.close()
result['seconds']=round(time.monotonic()-started,3)
print(json.dumps(result))
'''

BIND = r'''
import json,os,socket,sys
uid,port=int(sys.argv[1]),int(sys.argv[2])
''' + IDENTITY + r'''
outcome=[]
for kind in (socket.SOCK_DGRAM,socket.SOCK_STREAM):
    for address in ('127.0.0.1','0.0.0.0'):
        with socket.socket(socket.AF_INET,kind) as s:
            try: s.bind((address,port));outcome.append('bound')
            except OSError as error: outcome.append(type(error).__name__)
print(json.dumps(outcome))
'''

# An owner connection that stays open until its stdin closes.
HOLD = r'''
import os,socket,sys
uid,dest,port=int(sys.argv[1]),sys.argv[2],int(sys.argv[3])
''' + IDENTITY + r'''
s=socket.socket();s.settimeout(3);s.connect((dest,port));print('ready',flush=True);sys.stdin.read()
'''

# An owner program that keeps asking one resolver: twenty times a second, and again a
# millisecond after a refusal, as a resolver that does not pause between its attempts does.
# Told to end (SIGTERM), it says how its queries ended.
ASKER = r'''
import json,os,signal,socket,struct,sys,time
uid,dest,name=int(sys.argv[1]),sys.argv[2],sys.argv[3]
''' + IDENTITY + r'''
query=(struct.pack('>HHHHHH',0x1234,0x0100,1,0,0,0)
       +b''.join(bytes([len(label)])+label.encode() for label in name.split('.'))+b'\0'+struct.pack('>HH',1,1))
tally={'answered':0,'refused':0,'blocked':0,'other':0}
def report(*_):
    print(json.dumps(tally),flush=True);os._exit(0)
signal.signal(signal.SIGTERM,report)
print('ready',flush=True)
while True:
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(0.5);pause=0.05
    try: s.connect((dest,53));s.send(query);s.recv(1500);tally['answered']+=1
    except ConnectionRefusedError: tally['refused']+=1;pause=0.001
    except PermissionError: tally['blocked']+=1
    except OSError: tally['other']+=1
    s.close();time.sleep(pause)
'''

# Where IPv4 packets leave, and for the uplink whose socket sent them. A packet
# the kernel sends for a closed socket belongs to no socket at all.
COUNTERS = f'''table inet xq_core_check {{
  counter wan_all {{ }}
  counter wan_root {{ }}
  counter wan_other {{ }}
  counter tun_all {{ }}
  counter tun_icmp {{ }}
  counter tun_rst {{ }}
  chain postrouting {{
    type filter hook postrouting priority 300; policy accept;
    oifname "{WAN}" meta nfproto ipv4 counter name wan_all
    oifname "{WAN}" meta nfproto ipv4 meta skuid 0 counter name wan_root
    oifname "{WAN}" meta nfproto ipv4 meta skuid {OTHER} counter name wan_other
    oifname "{TUN}" meta nfproto ipv4 counter name tun_all
    oifname "{TUN}" icmp type destination-unreachable counter name tun_icmp
    oifname "{TUN}" tcp flags & rst == rst counter name tun_rst
  }}
}}
'''


def run(args, *, data=None, check=True):
    result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError(f'{args!r}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def count(name):
    return json.loads(run([NFT, '-j', 'list', 'counter', 'inet', 'xq_core_check', name]))['nftables'][-1]['counter']['packets']


def stray():
    """IPv4 packets on the uplink that neither root's nor the other user's sockets sent:
    the owner's own, and those the kernel sent for a socket that is gone."""
    return count('wan_all') - count('wan_root') - count('wan_other')


def hits(chain, verdict):
    data = json.loads(run([NFT, '-j', 'list', 'chain', 'inet', TABLE, chain]))
    return sum(expr['counter']['packets']
               for item in data['nftables']
               if any(verdict in e for e in item.get('rule', {}).get('expr', []))
               for expr in item.get('rule', {}).get('expr', []) if 'counter' in expr)


def child(name, code, *arguments, stdin=None):
    process = subprocess.Popen([sys.executable, '-I', '-u', '-c', code, *map(str, arguments)],
                               stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ready, _, _ = select.select([process.stdout], [], [], 5)
    if not ready or not process.stdout.readline():
        process.kill()
        raise RuntimeError(f'{name} did not start: {process.stderr.read()}')
    CHILDREN[name] = process
    return process


def stop(name):
    process = CHILDREN.pop(name)
    process.kill()
    process.wait(timeout=5)


LEFT_BEHIND = []


def left_behind(port):
    """Sockets of a core that still wait for the end of a connection from this source port.

    A known limit, not checked for here but met by chance: when a program gives
    up a TCP query to an address of this host, what the kernel then sends for
    its closed socket has no UID, misses the zone and never reaches the core,
    whose socket lives on until its retransmissions give up. A later connection
    that happens to get the same source port is answered by that socket.
    """
    # Only a connection that was established once: SYN-RECV would be the failed attempt itself.
    return [' '.join(line.split()) for line in run([SS, '-H', '-tan']).splitlines()
            if line.split()[0] in ('LAST-ACK', 'CLOSE-WAIT', 'CLOSING', 'FIN-WAIT-1', 'FIN-WAIT-2', 'ESTAB')
            and line.split()[-1].endswith(f':{port}') and line.split()[-2].startswith('127.0.0.1:')]


def probe(uid, dest, mode='udp', port=53, source=0):
    command = [sys.executable, '-I', '-c', PROBE, str(uid), dest, str(port), mode, str(source), NAME]
    result = json.loads(run(command))
    if mode == 'tcp' and not source and result['error'] == 'TimeoutError' and left_behind(result.get('tried', 0)):
        LEFT_BEHIND.append((dest, result['tried'], left_behind(result['tried'])))   # any other timeout stays a failure
        result = json.loads(run(command))
    return result


def expect(result, answer, what):
    if result['answer'] != answer:
        sockets = [' '.join(line.split()) for line in run([SS, '-H', '-tan']).splitlines()
                   if result.get('tried') and line.split()[-1].endswith(f':{result["tried"]}')]
        raise AssertionError(f'{what}: expected {answer!r}, got {result!r}; sockets with that peer port: {sockets}')


def refuse_unsafe_namespace():
    if os.geteuid() != 0:
        raise SystemExit('Needs root inside a new network namespace: ' + USAGE)
    here, host = os.stat('/proc/self/ns/net'), os.stat('/proc/1/ns/net')
    if (here.st_dev, here.st_ino) == (host.st_dev, host.st_ino):
        raise SystemExit('Refusing host network: ' + USAGE)
    if [item['ifname'] for item in json.loads(run([IP, '-j', 'link', 'show']))] != ['lo']:
        raise SystemExit('Refusing a namespace that is not fresh (expected only lo)')


class Unit:
    """What systemd does with xq-user-proxy.service, for a core in this namespace."""

    def __init__(self, scope, core, base):
        self.scope, self.core, self.base = scope, core, base
        self.process, self.starts = None, 0
        self.log = (base / 'core.log').open('ab')

    def active(self):
        return self.process is not None and self.process.poll() is None

    def derived(self):
        """The installed configuration with the two substitutions named in this file's header."""
        config = json.loads(self.scope['CONFIG'].read_text())
        config['dns'] = {'servers': [{'type': 'hosts', 'tag': 'proxied-dns', 'predefined': {NAME: [CORE_ANSWER]}}],
                         'final': 'proxied-dns', 'strategy': 'ipv4_only'}
        config['outbounds'] = [{'type': 'direct', 'tag': 'upstream'}]
        path = self.base / 'core-run.json'
        path.write_text(json.dumps(config))
        return str(path)

    def start(self):
        if self.active() or not self.scope['ENABLED'].exists():   # ConditionPathExists
            return 0, ''
        try:                                                      # ExecStartPre, twice
            config = self.derived()
            checked = subprocess.run([self.core, 'check', '-c', config], capture_output=True, text=True, timeout=30)
            if checked.returncode:
                return 1, 'sing-box check: ' + checked.stderr.strip()
            self.scope['prepare']()
        except REFUSALS as error:
            return 1, f'ExecStartPre: {error}'
        self.process = subprocess.Popen([self.core, 'run', '-c', config], stdout=subprocess.DEVNULL, stderr=self.log)
        try:                                                      # ExecStartPost
            self.scope['attach']()
        except REFUSALS as error:
            self.stop()
            return 1, f'ExecStartPost: {error}'
        self.starts += 1
        # systemd does not wait for this; the probes of this test start at once.
        port = self.scope['DNS_PORT']
        for _ in range(50):
            if all(run([SS, '-Hln', kind, 'src', '127.0.0.1', 'sport', '=', f':{port}']).strip() for kind in ('-t', '-u')):
                return 0, ''
            time.sleep(0.1)
        return 1, f'the core did not listen on 127.0.0.1:{port}'

    def stop(self, crash=False):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGKILL if crash else signal.SIGTERM)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        for _ in range(50):                                       # the TUN leaves with its owner
            if subprocess.run([IP, 'link', 'show', TUN], capture_output=True).returncode:
                return
            time.sleep(0.1)
        raise RuntimeError('the TUN outlived the core')

    def answer(self, verb):
        if verb in (['is-active', '--quiet', SERVICE], ['is-active', SERVICE]):
            return (0, 'active\n', '') if self.active() else (3, 'inactive\n', '')
        if verb == ['is-active', '--quiet', 'nscd.service']:
            return 4, '', ''
        if verb == ['reset-failed', SERVICE]:
            return 0, '', ''
        if verb == ['start', SERVICE]:
            code, reason = self.start()
            return code, '', f'Job for {SERVICE} failed: {reason}\n' if code else ''
        if verb == ['stop', SERVICE]:
            self.stop()
            return 0, '', ''
        raise AssertionError('Unexpected systemctl call in the namespace test: ' + repr(verb))


def sandbox(ctl, base, core):
    """The namespace shares the host file system: keep the controller inside `base`."""
    scope = ctl['firewall'].__globals__
    for directory in ('state', 'etc'):
        (base / directory).mkdir(mode=0o700)
    scope.update(STATE=base / 'state', STATEFILE=base / 'state/state.json', ENABLED=base / 'state/enabled',
                 CORE_RECORD=base / 'state/core.json', CONFIG=base / 'etc/sing-box.json',
                 SETTINGS=base / 'etc/settings.json', RESOLV=base / 'etc/resolv.conf')
    config = json.loads((BASE / 'sing-box.template.json').read_text())
    config['outbounds'][0].update(server=UPSTREAM[0], server_port=UPSTREAM[1])
    write_config(scope, config, UPSTREAM)
    scope['RESOLV'].write_text(f'nameserver {STUB}\noptions edns0 trust-ad\n')
    unit = Unit(scope, core, base)
    atomic, command = scope['atomic'], scope['run']

    def checked_atomic(path, content):
        if not Path(path).resolve().is_relative_to(base):
            raise AssertionError('Controller attempted a write outside the test directory: ' + str(path))
        return atomic(path, content)

    def checked_run(args, *, check=True, **kwargs):
        if args[0] == SYSTEMCTL:
            code, out, err = unit.answer(args[1:])
            if check and code:
                raise RuntimeError(' '.join(args) + ': ' + err.strip())
            return SimpleNamespace(returncode=code, stdout=out, stderr=err)
        if args[0] not in (IP, NFT, CONNTRACK):
            raise AssertionError('Unexpected controller command in the namespace test: ' + repr(args))
        return command(args, check=check, **kwargs)

    def account(name):
        if name != 'test-owner':
            raise KeyError(name)
        return SimpleNamespace(pw_uid=OWNER, pw_gid=OWNER)

    # The host's NSS configuration is not what this test is about.
    scope.update(atomic=checked_atomic, run=checked_run, pwd=SimpleNamespace(getpwnam=account), check_nss=lambda: None)
    scope['load_settings']()
    return scope, unit


def write_config(scope, config, upstream):
    for path, data in ((scope['CONFIG'], config),
                       (scope['SETTINGS'], dict(schema=1, user='test-owner', uid=OWNER, gid=OWNER,
                                                proxy_ip=upstream[0], proxy_port=upstream[1]))):
        path.write_text(json.dumps(data, indent=2) + '\n')
        path.chmod(0o600)


def call(scope, name):
    """One controller command, as its own invocation would run it."""
    scope['load_settings']()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = scope[name]()
    return result or 0, output.getvalue()


def refused(scope, name):
    try:
        call(scope, name)
    except REFUSALS as error:
        return str(error)
    raise AssertionError(f'{name} was expected to be refused')


def owner_dns_works(scope, what):
    for mode in ('udp', 'tcp'):
        expect(probe(OWNER, STUB, mode), CORE_ANSWER, f'owner DNS to the stub ({mode}) {what}')
        expect(probe(OWNER, PUBLIC, mode), CORE_ANSWER, f'owner DNS to a public resolver ({mode}) {what}')


def check_fresh_on(scope, unit):
    code, text = call(scope, 'status')
    assert code == 0 and '开关：OFF' in text, text
    expect(probe(OWNER, STUB), STAND_INS[STUB], 'owner DNS before the switch is on')
    call(scope, 'on')
    call(scope, 'check')
    code, text = call(scope, 'status')
    assert code == 0 and '开关：ON' in text and f'{UPSTREAM[0]}:{UPSTREAM[1]}' in text, text
    record = json.loads(scope['CORE_RECORD'].read_text())
    assert record['loaded'] and record['upstream'] == f'{UPSTREAM[0]}:{UPSTREAM[1]}', record
    assert unit.active() and unit.starts == 1
    print('PASS: on() from a clean boot starts the real core through the unit steps; check and status agree', flush=True)


def check_owner_paths(scope):
    port, local = scope['DNS_PORT'], scope['host_addresses']()
    kinds = {address: scope['nameserver_path'](ipaddress.ip_address(address), local)[0]
             for address in (STUB, ANY, HOST_LOCAL, PUBLIC, LAN, V6_LOOPBACK)}
    assert kinds == {STUB: 'proxied', ANY: 'proxied', HOST_LOCAL: 'proxied', PUBLIC: 'tunnel',
                     LAN: 'lan', V6_LOOPBACK: 'blocked'}, kinds
    before, tunnelled = stray(), count('tun_all')
    for mode in ('udp', 'tcp'):
        for address, kind in kinds.items():
            answer = {'proxied': CORE_ANSWER, 'tunnel': CORE_ANSWER, 'lan': STAND_INS.get(address), 'blocked': None}[kind]
            expect(probe(OWNER, address, mode), answer, f'owner DNS to {address} ({kind}, {mode})')
        expect(probe(OWNER, '127.0.0.1', mode, port=port), CORE_ANSWER, 'owner asking the private entry directly')
    assert count('tun_all') > tunnelled, 'the query to the public resolver did not enter the TUN'
    assert stray() == before, f'{stray() - before} owner packets left by the uplink'
    flows = run([CONNTRACK, '-L'])
    public = [line for line in flows.splitlines() if f'dst={PUBLIC} ' in line and 'dport=53 ' in line]
    stub = [line for line in flows.splitlines() if f'dst={STUB} ' in line and 'dport=53 ' in line]
    assert public and not any('zone=' in line or f'sport={port} ' in line for line in public), public
    assert stub and all(f'zone={ZONE}' in line and f'sport={port} ' in line for line in stub), stub
    # What the TUN delivered was accepted as answers to the owner. The one exception is the
    # core's own doing: at each start sing-box writes one probe packet from the TUN's address
    # to itself, which the kernel would discard as martian anyway.
    assert hits('from_tun', 'return') > 0 and hits('from_tun', 'drop') <= 1, \
        run([NFT, 'list', 'chain', 'inet', TABLE, 'from_tun'])
    print(f'PASS: owner DNS over UDP and TCP is answered by the core on both paths: addresses of this host '
          f'(stub, 0.0.0.0, a public address of the host) through 127.0.0.1:{port} in zone {ZONE}, a public '
          'resolver untranslated through the TUN in the default zone; a LAN resolver directly; ::1 blocked; '
          'nothing of it on the uplink; the classifier says the same', flush=True)


def check_closed_sockets(scope):
    """Answers that arrive after the owner closed its socket: the kernel's replies must not take the uplink."""
    before, icmp, reset = stray(), count('tun_icmp'), count('tun_rst')
    for address in (PUBLIC, STUB, HOST_LOCAL):
        for mode in ('udp-giveup', 'tcp-giveup'):
            for _ in range(20):
                probe(OWNER, address, mode)
    time.sleep(3)                               # retransmissions of the unanswered side
    late_icmp, late_reset = count('tun_icmp') - icmp, count('tun_rst') - reset
    assert stray() == before, f'{stray() - before} packets for closed owner sockets left by the uplink'
    assert late_icmp and late_reset, ('the scenario did not happen: the kernel sent no reply for a closed socket '
                                      f'into the TUN (ICMP {late_icmp}, RST {late_reset})')
    owner_dns_works(scope, 'after the abandoned queries')
    print(f'PASS: 120 owner queries abandoned before their answer (UDP and TCP; public resolver, stub, host '
          f'address): the kernel\'s replies for the closed sockets ({late_icmp} ICMP errors, {late_reset} TCP '
          'resets) followed the flows into the TUN, none left by the uplink', flush=True)


def check_forgotten_connection(scope):
    """The owner closes a public connection that conntrack no longer knows.

    The FIN cannot start a conntrack entry. Whatever the core answers would not
    be let in, and the retransmissions of the then orphaned socket would carry
    neither a UID nor a marked flow: they would leave by the uplink.
    """
    held = child('held', HOLD, OWNER, PUBLIC, 53, stdin=subprocess.PIPE)
    known = [line for line in run([CONNTRACK, '-L', '-p', 'tcp']).splitlines()
             if f'dst={PUBLIC} ' in line and 'ESTABLISHED' in line]
    assert len(known) == 1, known
    run([CONNTRACK, '-D', '-p', 'tcp', '-d', PUBLIC, '--dport', '53'], check=False)   # what a flushed table has lost
    assert not [line for line in run([CONNTRACK, '-L', '-p', 'tcp']).splitlines() if f'dst={PUBLIC} ' in line]
    before, refused = stray(), hits('classify_output', 'reject')
    held.stdin.close()
    CHILDREN.pop('held').wait(timeout=5)
    time.sleep(3)                               # several retransmission timeouts of an orphaned socket
    assert hits('classify_output', 'reject') == refused + 1, 'the FIN did not meet the rule for unknown connections'
    assert stray() == before, f'{stray() - before} packets of the forgotten connection left by the uplink'
    owner_dns_works(scope, 'after the forgotten connection')
    print('PASS: an owner connection that conntrack has forgotten is reset locally when the owner closes it: '
          'nothing of it is retransmitted and nothing leaves by the uplink', flush=True)


def checksum(data):
    data += b'\0' * (len(data) % 2)
    total = sum(struct.unpack(f'>{len(data) // 2}H', data))
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return ~total & 0xffff


def packet(protocol, source, dest, payload):
    """An IPv4 packet; for TCP the payload is a bare segment whose checksum is filled in here."""
    if protocol == socket.IPPROTO_TCP:
        pseudo = socket.inet_aton(source) + socket.inet_aton(dest) + struct.pack('>BBH', 0, protocol, len(payload))
        payload = payload[:16] + struct.pack('>H', checksum(pseudo + payload)) + payload[18:]
    header = struct.pack('>BBHHHBBH4s4s', 0x45, 0, 20 + len(payload), 0, 0, 64, protocol, 0,
                         socket.inet_aton(source), socket.inet_aton(dest))
    return header[:10] + struct.pack('>H', checksum(header)) + header[12:] + payload


class Outside:
    """A second uplink, towards SEEDED only, whose far end this test holds.

    A TAP device: the test writes the frames that arrive from outside and
    reads every IPv4 packet the host sends that way, whoever sent it.
    """

    def __init__(self):
        self.fd = os.open('/dev/net/tun', os.O_RDWR)
        fcntl.ioctl(self.fd, 0x400454ca, struct.pack('16sH22x', SEED_TAP.encode(), 0x1002))   # TUNSETIFF: IFF_TAP | IFF_NO_PI
        run([IP, 'address', 'add', SEED_LOCAL + '/24', 'dev', SEED_TAP])
        run([IP, 'link', 'set', SEED_TAP, 'up'])
        run([IP, 'route', 'add', SEEDED + '/32', 'dev', SEED_TAP])
        run([IP, 'neigh', 'replace', SEEDED, 'lladdr', '02:00:00:00:00:81', 'dev', SEED_TAP, 'nud', 'permanent'])
        self.mac = bytes.fromhex(json.loads(run([IP, '-j', 'link', 'show', 'dev', SEED_TAP]))[0]['address'].replace(':', ''))
        os.set_blocking(self.fd, False)

    def arrives(self, protocol, payload, broadcast=False):
        os.write(self.fd, (b'\xff' * 6 if broadcast else self.mac) + bytes.fromhex('020000000081') + b'\x08\x00'
                 + packet(protocol, SEEDED, SEED_LOCAL, payload))

    def sent(self, wait=0.4):
        """The IPv4 packets the host sent to SEEDED by this uplink since the last call, as
        (protocol number, source port); the port is None for what is neither TCP nor UDP."""
        time.sleep(wait)
        seen = []
        while True:
            try:
                frame = os.read(self.fd, 4096)
            except BlockingIOError:
                return seen
            if frame[12:14] == b'\x08\x00' and socket.inet_ntoa(frame[30:34]) == SEEDED:
                transport = 14 + (frame[14] & 15) * 4
                ported = frame[23] in (socket.IPPROTO_TCP, socket.IPPROTO_UDP)
                seen.append((frame[23], struct.unpack('>H', frame[transport:transport + 2])[0] if ported else None))

    def close(self):
        os.close(self.fd)


def check_preseeded_flows(scope):
    """An owner flow whose conntrack entry somebody else began: not by the uplink, and not answered.

    A packet from outside for a port of this host leaves a conntrack entry even
    when no socket has that port. What the owner later sends from that port to
    that sender is the reply direction of the entry. It enters the TUN like
    every owner packet for a public address. The core's answer, however, is for
    conntrack a packet of the direction the stranger began, and what the TUN
    delivers must answer a flow the owner started: the answer is dropped on
    arrival. The flow fails for as long as the entry lives; it does not leave
    by the uplink, and a flow from any other port is not concerned.
    """
    outside, before = Outside(), stray()
    try:
        outside.sent(0.3)

        def begun_outside(mode, peer, port):
            return [line for line in run([CONNTRACK, '-L', '-p', mode]).splitlines()
                    if f'src={SEEDED} dst={SEED_LOCAL} sport={peer} dport={port} ' in line]

        def seed(mode, peer, port):
            if mode == 'udp':
                outside.arrives(socket.IPPROTO_UDP, struct.pack('>HHHH', peer, port, 8 + 4, 0) + b'seed')
            else:
                # In a broadcast frame: the kernel sends no RST for such a SYN, and a RST would end the entry.
                outside.arrives(socket.IPPROTO_TCP, struct.pack('>HHIIBBHHH', peer, port, 1000, 0, 5 << 4, 0x02, 65535, 0, 0),
                                broadcast=True)
            outside.sent()                      # what the kernel itself answers the stranger is not the owner's
            assert len(begun_outside(mode, peer, port)) == 1, f'the {mode} packet from outside left no conntrack entry'

        def owners(port, wait=0.4):
            return [item for item in outside.sent(wait) if item[1] == port]

        # DNS for a public resolver: the core answers it inside the TUN, so a flow that works is told
        # from one that does not.
        for mode, port in (('udp', 47011), ('tcp', 47031)):
            expect(probe(OWNER, SEEDED, mode, source=port - 1), CORE_ANSWER, f'owner DNS ({mode}) to a peer nobody seeded')
            seed(mode, 53, port)
            dropped = hits('from_tun', 'drop')
            result = probe(OWNER, SEEDED, mode, source=port)
            left = owners(port)
            assert not left, f'owner DNS ({mode}) taken for a reply left by the uplink: {left}'
            assert result['answer'] is None and result['error'] == 'TimeoutError', \
                f'the owner flow ({mode}) from the seeded port was expected to stay unanswered: {result!r}'
            assert hits('from_tun', 'drop') > dropped, f'the scenario did not happen: no answer of the core ({mode}) was dropped'
            expect(probe(OWNER, SEEDED, mode, source=port + 1), CORE_ANSWER, f'owner DNS ({mode}) from another port')
        # Any other port. Nobody answers such a flow in this namespace either way (public UDP is
        # refused by the core, and its outbound, direct here, reaches no one: what root's socket
        # sends for it is the core's own connection). What counts is where the owner's packets go.
        for mode, port in (('udp', 47051), ('tcp', 47061)):
            seed(mode, 443, port)
            routed = count('tun_all')
            assert probe(OWNER, SEEDED, mode, port=443, source=port)['answer'] is None
            left = owners(port)
            assert not left, f'owner {mode} packets for port 443 taken for replies left by the uplink: {left}'
            assert count('tun_all') > routed, f'the owner {mode} packet for port 443 did not enter the TUN'
        # Once the entry is gone (it expires; deleted here), the same port serves again. Shown for
        # UDP only: how long the core keeps the half-open TCP connection is the core's own matter.
        run([CONNTRACK, '-D', '-p', 'udp', '--orig-src', SEEDED, '--orig-port-dst', '47011'], check=False)
        assert not begun_outside('udp', 53, 47011)
        expect(probe(OWNER, SEEDED, 'udp', source=47011), CORE_ANSWER, 'owner DNS (udp) from the seeded port once the entry is gone')
        late = [item for item in outside.sent(1.0) if item[1] in (47011, 47031, 47051, 47061)]
        assert not late and stray() == before, f'packets left by an uplink afterwards: {late}, {stray() - before} on {WAN}'
    finally:
        outside.close()
    owner_dns_works(scope, 'after the seeded flows')
    print('PASS: an owner flow whose conntrack entry somebody else began from outside (DNS and port 443, UDP and TCP) '
          'enters the TUN and nothing of it leaves by the uplink; the core\'s answer is dropped at the TUN entry, so '
          'that flow stays unanswered while the entry lives, a flow from another port is answered at once, and so is '
          'the same port once the entry is gone', flush=True)


def check_bystanders(scope):
    port = scope['DNS_PORT']
    for uid, who, sent in ((0, 'root', 'wan_root'), (OTHER, 'another UID', 'wan_other')):
        rejected, tunnelled, unowned = hits('private_dns_access', 'reject'), count('tun_all'), stray()
        for mode in ('udp', 'tcp'):
            for address in (STUB, HOST_LOCAL, LAN):
                expect(probe(uid, address, mode), STAND_INS[address], f'{who} DNS to {address} ({mode})')
            left = count(sent)
            expect(probe(uid, PUBLIC, mode), None, f'{who} DNS to a public resolver ({mode})')
            assert count(sent) > left, f'{who} DNS to a public resolver did not leave by the uplink'
            expect(probe(uid, '127.0.0.1', mode, port=port), None, f'{who} asking the private entry')
        assert hits('private_dns_access', 'reject') >= rejected + 2
        assert (count('tun_all'), stray()) == (tunnelled, unowned), f'{who} traffic was taken over'
    first = probe(OWNER, STUB)
    expect(first, CORE_ANSWER, 'owner DNS')
    expect(probe(OTHER, STUB, source=first['source']), STAND_INS[STUB], 'another UID reusing the owner source port')
    second = probe(OTHER, STUB)
    expect(second, STAND_INS[STUB], 'another UID DNS')
    expect(probe(OWNER, STUB, source=second['source']), CORE_ANSWER, 'owner reusing the other source port')
    before = hits('private_tun_access', 'drop')
    with socket.socket() as sock:
        sock.settimeout(0.6)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, 0x40000000)
        try:
            sock.connect((PUBLIC, 443))
        except OSError:
            pass
        else:
            raise AssertionError('Marked root unexpectedly connected through the TUN')
    assert hits('private_tun_access', 'drop') > before
    print('PASS: root and another UID keep every original resolver (a public one by the uplink), are refused '
          'the private entry and the TUN, and a reused UDP source port carries no translation between UIDs',
          flush=True)


def check_core_down(scope, unit):
    port, before = scope['DNS_PORT'], stray()
    unit.stop(crash=True)                       # the guard and the blackhole stay
    # A translated query is refused by the empty entry; a datagram for the TUN
    # fails in the blackhole. A TCP connection for the TUN is blackholed like
    # every public TCP connection of the owner: until the program gives up.
    for address, mode, at_once in ((STUB, 'udp', True), (STUB, 'tcp', True), (PUBLIC, 'udp', True), (PUBLIC, 'tcp', False)):
        result = probe(OWNER, address, mode)
        assert result['answer'] is None and result['error'] and (result['seconds'] < 0.5 or not at_once), \
            f'owner DNS to {address} ({mode}) with the core down: {result!r}'
    outcome = json.loads(run([sys.executable, '-I', '-c', BIND, str(OTHER), str(port)]))
    assert outcome == ['PermissionError'] * 4, outcome
    assert stray() == before, f'{stray() - before} owner packets left by the uplink while the core was down'
    expect(probe(OTHER, STUB), STAND_INS[STUB], 'another UID DNS while the core is down')
    code, text = call(scope, 'status')
    assert code == 1 and '核心未运行' in text, text
    call(scope, 'on')
    owner_dns_works(scope, 'after on() restarted the core')
    assert call(scope, 'status')[0] == 0
    print(f'PASS: with the core killed nothing of the owner leaves by the uplink: DNS to the stub and UDP DNS '
          f'to a public resolver fail at once, TCP to a public resolver is blackholed; another UID cannot bind '
          f'port {port}; status says the core is down, and on() brings it back', flush=True)


def check_forged_answers(scope, unit):
    port, original = scope['DNS_PORT'], THRESHOLD.read_text()
    THRESHOLD.write_text('0\n')                 # this namespace only: ordinary users may now bind the entry
    try:
        assert 'ip_unprivileged_port_start' in refused(scope, 'check')
        code, text = call(scope, 'status')
        assert code == 1 and 'ip_unprivileged_port_start' in text, text
        unit.stop(crash=True)
        child('squatter', RESOLVER, OTHER, '127.0.0.1', port, FORGED)
        dropped = hits('dns_zone_output', 'drop')
        for mode in ('udp', 'tcp'):
            expect(probe(OWNER, STUB, mode), None, f'owner DNS answered by another UID ({mode})')
        assert hits('dns_zone_output', 'drop') > dropped, 'the forged answers did not hit the identity rule'
        stop('squatter')
    finally:
        THRESHOLD.write_text(original)
    call(scope, 'on')
    owner_dns_works(scope, 'after the squatter left and the core is back')
    print(f'PASS: with ip_unprivileged_port_start lowered in this namespace check and status report it, and '
          f'answers another UID then sends from port {port} never reach the owner', flush=True)


def check_edited_configuration(scope, unit):
    """What is on disk is not what a running core uses until it is started again."""
    starts, pid = unit.starts, unit.process.pid
    edited = (UPSTREAM[0], UPSTREAM[1] + 1)
    config = json.loads(scope['CONFIG'].read_text())
    config['outbounds'][0]['server_port'] = edited[1]
    write_config(scope, config, edited)
    message = refused(scope, 'check')
    assert '尚未加载' in message and f'{UPSTREAM[0]}:{UPSTREAM[1]}' in message, message
    code, text = call(scope, 'status')
    assert code == 1, text
    assert f'SOCKS5 {UPSTREAM[0]}:{UPSTREAM[1]}（运行中的核心实际使用' in text, text
    assert f'磁盘上的配置已改为 SOCKS5 {edited[0]}:{edited[1]}，尚未加载' in text, text
    assert unit.process.pid == pid, 'status or check restarted the core'
    call(scope, 'on')
    assert (unit.starts, unit.active()) == (starts + 1, True) and unit.process.pid != pid, 'on() kept the stale core'
    call(scope, 'check')
    code, text = call(scope, 'status')
    assert code == 0 and f'上游：SOCKS5 {edited[0]}:{edited[1]}' in text and '尚未加载' not in text, text
    owner_dns_works(scope, 'after the reload')
    starts, pid = unit.starts, unit.process.pid
    call(scope, 'on')                           # healthy and current: the core is kept
    assert (unit.starts, unit.process.pid) == (starts, pid)
    print('PASS: after the upstream is edited on disk, check and status name the configuration the running '
          'core really uses and that the new one is not loaded; on() restarts the core, and a further on() '
          'keeps it', flush=True)


def check_replaced_controller(scope, unit):
    """Rules loaded by an earlier controller, and a core nobody recorded, are replaced by on()."""
    starts, pid = unit.starts, unit.process.pid
    state = json.loads(scope['STATEFILE'].read_text())
    scope['STATEFILE'].write_text(json.dumps(dict(state, guard_source='an earlier version')))
    assert '不是当前' in refused(scope, 'check')
    assert call(scope, 'status')[0] == 1
    call(scope, 'on')
    assert (unit.starts, unit.process.pid) == (starts, pid), 'replacing the rules restarted a current core'
    call(scope, 'check')
    scope['CORE_RECORD'].unlink()
    assert '记录' in refused(scope, 'check')
    call(scope, 'on')
    assert unit.starts == starts + 1 and unit.process.pid != pid
    call(scope, 'check')
    run([NFT, 'delete', 'table', 'inet', TABLE])                  # what `nft flush ruleset` does to this table
    assert '不存在' in refused(scope, 'check')
    starts, pid = unit.starts, unit.process.pid
    call(scope, 'on')
    assert (unit.starts, unit.process.pid) == (starts, pid)
    owner_dns_works(scope, 'after the rules were rebuilt')
    print('PASS: rules from an earlier controller are replaced without restarting a current core; a core '
          'without a start record is restarted; a deleted table is rebuilt around the running core', flush=True)


def check_unrecorded_core_under_queries(scope, unit):
    """on() replaces a core nobody recorded while an owner program keeps asking.

    The translations of such a core may lead to an entry the rules no longer
    send to, so on() deletes them between the old core and the new one and
    proves them gone. With the old core stopped the entry refuses at once, and
    a program that asks again at once adds translations faster than they can be
    counted. on() therefore stops translating for that moment; otherwise it
    fails there, with the core left stopped.
    """
    starts, pid, before = unit.starts, unit.process.pid, stray()
    asker = child('asker', ASKER, OWNER, STUB, NAME)
    time.sleep(0.5)
    scope['CORE_RECORD'].unlink()
    assert '记录' in refused(scope, 'check')
    try:
        call(scope, 'on')
    finally:
        CHILDREN.pop('asker')
        asker.terminate()
        said = asker.communicate(timeout=5)[0]
    tally = json.loads(said.splitlines()[-1])
    assert unit.starts == starts + 1 and unit.process.pid != pid, 'on() kept the unrecorded core'
    assert tally['answered'] and tally['refused'] and tally['blocked'], f'the scenario did not happen: {tally}'
    assert stray() == before, f'{stray() - before} owner packets left by the uplink while the core was replaced'
    call(scope, 'check')
    assert call(scope, 'status')[0] == 0
    owner_dns_works(scope, 'after the unrecorded core was replaced')
    print(f'PASS: on() replaces a core without a start record while an owner program keeps asking the stub, again '
          f'a millisecond after each refusal ({tally["refused"]} queries refused by the empty entry, '
          f'{tally["blocked"]} dropped by the guard while the old translations were deleted, {tally["answered"]} '
          'answered): the translations are proven gone, the new core answers, nothing left by the uplink', flush=True)


def check_off_and_on_again(scope, unit):
    held = child('held', HOLD, OWNER, LAN, 53, stdin=subprocess.PIPE)   # an owner connection that outlives OFF
    call(scope, 'off')
    assert not unit.active() and scope['kernel_leftovers']() == ([], []), scope['kernel_leftovers']()
    assert not scope['CORE_RECORD'].exists() and not scope['ENABLED'].exists()
    code, text = call(scope, 'status')
    assert code == 0 and '开关：OFF' in text, text
    expect(probe(OWNER, STUB), STAND_INS[STUB], 'owner DNS after OFF')
    marked = run([CONNTRACK, '-L', '-f', 'ipv4', '--mark', '0x10000000/0x10000000'])
    assert marked.strip(), 'the held owner connection left no marked conntrack entry'
    call(scope, 'on')                           # the trusted OFF record of this boot allows the leftover marks
    owner_dns_works(scope, 'after OFF and ON')
    call(scope, 'off')
    scope['STATEFILE'].unlink()                 # without the record the same marks are somebody's unknown state
    assert 'conntrack 标记' in refused(scope, 'on')
    assert scope['kernel_leftovers']() == ([], []) and not unit.active()
    held.stdin.close()
    stop('held')
    print('PASS: off() leaves nothing and restores the host resolver; on() after it accepts the owner marks '
          'still held by a live connection because the OFF record of this boot vouches for them, and refuses '
          'them, changing nothing, once that record is gone', flush=True)


def exercise(scope, unit):
    run([IP, 'link', 'set', 'lo', 'up'])
    run([IP, 'link', 'add', WAN, 'type', 'dummy'])
    run([IP, 'link', 'set', WAN, 'up'])
    run([IP, 'address', 'add', WAN_ADDRESS + '/24', 'dev', WAN])
    run([IP, 'route', 'add', 'default', 'dev', WAN])
    for address in (LAN, HOST_LOCAL):
        run([IP, 'address', 'add', address + '/32', 'dev', 'lo'])
    for address, answer in STAND_INS.items():
        child('resolver ' + address, RESOLVER, 0, address, 53, answer)
    run([NFT, '-f', '-'], data=COUNTERS)
    check_fresh_on(scope, unit)
    check_owner_paths(scope)
    check_closed_sockets(scope)
    check_forgotten_connection(scope)
    check_preseeded_flows(scope)
    check_bystanders(scope)
    check_core_down(scope, unit)
    check_forged_answers(scope, unit)
    check_edited_configuration(scope, unit)
    check_replaced_controller(scope, unit)
    check_unrecorded_core_under_queries(scope, unit)
    check_off_and_on_again(scope, unit)
    if LEFT_BEHIND:
        print(f'INFO: {len(LEFT_BEHIND)} TCP query(ies) got the source port of a connection that an abandoned query '
              f'had left on the core ({LEFT_BEHIND}) and timed out; repeated from another port', flush=True)
    print(f'ALL CHECKS PASSED: real core, owner UID {OWNER}, other UID {OTHER}, root', flush=True)


def main():
    arguments = sys.argv[1:]
    core = arguments[1] if len(arguments) == 2 and arguments[0] == '--core' else os.environ.get('XQ_CORE', '')
    if not core or not os.access(core, os.X_OK):
        raise SystemExit('Needs the sing-box binary the package installs: ' + USAGE)
    refuse_unsafe_namespace()
    ctl = runpy.run_path(str(BASE / 'xq-user-proxyctl'))
    base = Path(tempfile.mkdtemp(prefix='xq-user-tun-core-check-', dir='/run')).resolve()
    unit = None
    try:
        scope, unit = sandbox(ctl, base, os.path.abspath(core))
        exercise(scope, unit)
    except BaseException:
        log = base / 'core.log'
        if log.is_file() and log.stat().st_size:
            print('--- core log ---\n' + log.read_text(errors='replace')[-3000:], file=sys.stderr)
        raise
    finally:
        if unit is not None:
            with contextlib.suppress(Exception):
                unit.stop(crash=True)
        for name in list(CHILDREN):
            CHILDREN.pop(name).kill()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    main()
