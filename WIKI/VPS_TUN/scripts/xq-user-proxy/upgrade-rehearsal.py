#!/usr/bin/python3 -I
"""Rehearse upgrade-to-portable.py on a copy of the frozen installation: the
real upgrade script, both real controllers, the real unit files and the real
sing-box core on the real kernel, without touching the host.

The shell must read the host's namespaces before it enters the new ones:

    HOSTNS="$(readlink /proc/self/ns/net) $(readlink /proc/self/ns/mnt) $(readlink /proc/self/ns/pid)"
    sudo unshare --net --mount --pid --fork --mount-proc --kill-child \\
        env XQ_HOST_NS="$HOSTNS" python3 -I upgrade-rehearsal.py --user NAME --scenario on

Scenarios, each in namespaces of its own:

    on        the proxy is ON while it is upgraded (the case of Mico-system)
    off       the proxy is OFF while it is upgraded
    restore   the new core cannot start: the frozen version is brought back
    partial   an earlier upgrade stopped half way: this run completes it
    examine   without --apply nothing changes

How the host is kept out of it. The network namespace is new: its rules, routes,
conntrack entries, sysctls and ports are its own. The mount namespace is new and
private: empty tmpfs file systems are mounted over /run and over every
directory the installation and the upgrade write to, and a copy of the frozen
installation is put there, so the script under test and the controllers use
their ordinary absolute paths and reach only those copies. The PID namespace is
new, so /proc/1/ns/net is this namespace and the controllers accept it as "the
host". Before the first mount this script requires all three namespaces to
differ from the ones named in XQ_HOST_NS, and after mounting it checks that the
stand-ins below are really in place.

systemd does not run here. /usr/bin/systemctl is covered, in this mount
namespace only, by a stand-in that does what xq-user-proxy.service says:
ConditionPathExists, every ExecStartPre, ExecStart, every ExecStartPost, with
the unit's CapabilityBoundingSet and NoNewPrivileges. The core is started with
two substitutions, since the namespace reaches no proxy: it answers DNS from a
fixed table instead of DoH, and its outbound is direct.

While the upgrade runs, the owner and another user keep sending DNS queries.
The rehearsal counts every IPv4 packet on the stand-in uplink that is neither
root's nor the other user's, and every query of the other user that failed.
"""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import pwd
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
OLD = Path(__file__).resolve().parent
NEW = OLD.parent / 'xq-user-tun'
UPGRADE = OLD / 'upgrade-to-portable.py'
REHEARSAL = Path('/run/xq-rehearsal')
CONTROLLER = Path('/usr/local/sbin/xq-user-proxyctl')
CONFIG_DIR = Path('/etc/xq-user-proxy')
UNIT = Path('/etc/systemd/system/xq-user-proxy.service')
LIB_DIR = Path('/usr/local/lib/xq-user-proxy')
VAR_DIR = Path('/var/lib/xq-user-proxy')
STATE = Path('/run/xq-user-proxy')
COVERED = ('/run', '/etc/xq-user-proxy', '/usr/local/sbin', '/etc/systemd/system',
           '/usr/local/lib/xq-user-proxy', '/var/lib/xq-user-proxy', '/var/backups')
STAND_INS = ('/usr/bin/systemctl', '/usr/bin/systemd-analyze')
MOUNT = '/usr/bin/mount'
OLD_PORT, NEW_PORT = 1053, 40
USAGE = __doc__.split('\n\n')[1] + '\n\n' + __doc__.split('\n\n')[2]

SYSTEMCTL = r'''#!/usr/bin/python3 -I
"""Stand-in for systemctl in the upgrade rehearsal's private mount namespace."""
import json, os, signal, subprocess, sys, time
from pathlib import Path
HOME = Path('/run/xq-rehearsal')
SERVICE = 'xq-user-proxy.service'
UNIT = Path('/etc/systemd/system') / SERVICE
PIDFILE = HOME / 'core.pid'
FAILED = f'Job for {SERVICE} failed because the control process exited with error code.\n'

def note(text):
    with (HOME / 'journal.log').open('a') as stream:
        stream.write(text.rstrip('\n') + '\n')

def core():
    try:
        pid = int(PIDFILE.read_text())
        state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
    except (OSError, ValueError, IndexError):
        return 0
    return 0 if state == 'Z' else pid

def options():
    found = {}
    for line in UNIT.read_text().splitlines():
        if '=' in line and not line.startswith(('#', '[')):
            key, value = line.split('=', 1)
            found.setdefault(key, []).append(value)
    return found

def confined(unit, command):
    keep = ''.join(',+' + name[4:].lower() for name in unit.get('CapabilityBoundingSet', [''])[-1].split())
    wrapper = ['/usr/bin/setpriv', '--bounding-set=-all' + keep, '--inh-caps=-all', '--ambient-caps=-all']
    if unit.get('NoNewPrivileges', ['no'])[-1] == 'yes':
        wrapper.append('--no-new-privs')
    return wrapper + ['--'] + command

def substituted(command):
    position = command.index('-c') + 1
    config = json.loads(Path(command[position]).read_text())
    config['dns'] = {'servers': [{'type': 'hosts', 'tag': 'proxied-dns',
                                  'predefined': json.loads((HOME / 'answers.json').read_text())}],
                     'final': 'proxied-dns', 'strategy': 'ipv4_only'}
    config['outbounds'] = [{'type': 'direct', 'tag': 'upstream'}]
    path = HOME / 'core-run.json'
    path.write_text(json.dumps(config))
    return command[:position] + [str(path)] + command[position + 1:]

def stop():
    pid = core()
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(150):
            if not core():
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
            while core():
                time.sleep(0.05)
    PIDFILE.unlink(missing_ok=True)

def start():
    unit = options()
    condition = unit.get('ConditionPathExists', [''])[-1]
    if core() or (condition and not os.path.exists(condition)):
        return 0
    os.umask(int(unit.get('UMask', ['0022'])[-1], 8))
    if (HOME / 'new-core-cannot-start').exists() and any(line.endswith(' prepare') for line in unit.get('ExecStartPre', [])):
        note('rehearsal: the new core is made to fail')
        return 1
    for line in unit.get('ExecStartPre', []):
        done = subprocess.run(confined(unit, line.split()), capture_output=True, text=True, timeout=30)
        note(f'ExecStartPre {line}: exit {done.returncode} {done.stdout}{done.stderr}')
        if done.returncode:
            return 1
    with (HOME / 'core.log').open('ab') as log:
        process = subprocess.Popen(confined(unit, substituted(unit['ExecStart'][-1].split())), stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, start_new_session=True, close_fds=True)
    PIDFILE.write_text(str(process.pid))
    for line in unit.get('ExecStartPost', []):
        done = subprocess.run(confined(unit, line.split()), capture_output=True, text=True, timeout=30)
        note(f'ExecStartPost {line}: exit {done.returncode} {done.stdout}{done.stderr}')
        if done.returncode:
            stop()
            return 1
    return 0

def main(argv):
    note('systemctl ' + ' '.join(argv))
    quiet = '--quiet' in argv
    words = [word for word in argv if word != '--quiet']
    if words[:1] == ['daemon-reload'] or words[:1] == ['reset-failed']:
        return 0
    if words[:1] == ['is-active'] and len(words) == 2:
        active = words[1] == SERVICE and core()
        if not quiet:
            print('active' if active else 'inactive')
        return 0 if active else (3 if words[1] == SERVICE else 4)
    if words[:1] == ['show'] and len(words) == 3 and words[2] == '--property=MainPID,ActiveState':
        pid = core() if words[1] == SERVICE else 0
        print(f'MainPID={pid}\nActiveState={"active" if pid else "inactive"}')
        return 0
    if words == ['start', SERVICE]:
        code = start()
        if code:
            sys.stderr.write(FAILED)
        return code
    if words == ['stop', SERVICE]:
        stop()
        return 0
    sys.stderr.write('rehearsal systemctl: unexpected call: ' + ' '.join(argv) + '\n')
    return 97

sys.exit(main(sys.argv[1:]))
'''

# Queries of one user, one after another until the process is terminated; one JSON line per query.
LOAD = r'''
import json,os,socket,struct,sys,time
uid,name=int(sys.argv[1]),sys.argv[3]
targets=[item.split('/') for item in sys.argv[4:]]
log=open(sys.argv[2],'w')            # opened as root; the queries below are the user's
os.setgroups([]);os.setgid(uid);os.setuid(uid)
query=(struct.pack('>HHHHHH',0x1234,0x0100,1,0,0,0)
       +b''.join(bytes([len(label)])+label.encode() for label in name.split('.'))+b'\0'+struct.pack('>HH',1,1))
def ask(dest,mode):
    tcp=mode=='tcp'
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM);s.settimeout(1.0)
    try:
        s.connect((dest,53));s.sendall(struct.pack('>H',len(query))+query if tcp else query)
        if tcp:
            head=s.recv(2);data=b''
            while len(head)==2 and len(data)<struct.unpack('>H',head)[0]:
                chunk=s.recv(2048)
                if not chunk: break
                data+=chunk
        else: data=s.recv(1500)
        return socket.inet_ntoa(data[-4:]) if len(data)>12 and not data[3]&15 and data[7] else None
    except OSError: return None
    finally: s.close()
while True:
    for dest,mode,expected in targets:
        started=time.time();answer=ask(dest,mode)
        log.write(json.dumps({'t':started,'to':dest,'mode':mode,'ok':answer==expected})+'\n');log.flush()
    time.sleep(0.05)
'''


# One user's resolver that keeps a single socket for all its queries, as some long-running programs do.
KEPT = r'''
import json,os,socket,struct,sys,time
uid,dest,name,expected=int(sys.argv[1]),sys.argv[3],sys.argv[4],sys.argv[5]
log=open(sys.argv[2],'w')
os.setgroups([]);os.setgid(uid);os.setuid(uid)
query=(struct.pack('>HHHHHH',0x4321,0x0100,1,0,0,0)
       +b''.join(bytes([len(label)])+label.encode() for label in name.split('.'))+b'\0'+struct.pack('>HH',1,1))
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(0.5);s.connect((dest,53))
while True:
    started=time.time()
    try:
        s.send(query);data=s.recv(1500)
        ok=len(data)>12 and not data[3]&15 and data[7] and socket.inet_ntoa(data[-4:])==expected
    except OSError: ok=False
    log.write(json.dumps({'t':started,'ok':bool(ok)})+'\n');log.flush()
    time.sleep(0.2)
'''


def load_module(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


cc = load_module(NEW / 'tests/core-check.py', 'xq_core_check')   # its probes, stand-in resolvers and counters
run = cc.run


def refuse_unless_isolated():
    """Nothing below may run in the host's network, mount or PID namespace."""
    if os.geteuid() != 0:
        raise SystemExit('Needs root inside new namespaces:\n\n' + USAGE)
    declared = os.environ.get('XQ_HOST_NS', '').split()
    kinds = ('net', 'mnt', 'pid')
    if len(declared) != 3 or any(not value.startswith(kind + ':[') for kind, value in zip(kinds, declared)):
        raise SystemExit('XQ_HOST_NS must name the host namespaces:\n\n' + USAGE)
    for kind, host in zip(kinds, declared):
        if os.readlink(f'/proc/self/ns/{kind}') == host:
            raise SystemExit(f'Refusing the host {kind} namespace:\n\n' + USAGE)
    if os.getpid() != 1:
        raise SystemExit('Expected to be PID 1 of a new PID namespace:\n\n' + USAGE)
    if [item['ifname'] for item in json.loads(run([cc.IP, '-j', 'link', 'show']))] != ['lo']:
        raise SystemExit('Refusing a network namespace that is not fresh (expected only lo)')
    for path in (*COVERED, *STAND_INS):
        if not os.path.exists(path):
            raise SystemExit(f'{path} does not exist on this host; the rehearsal covers existing paths only')


def cover_the_installation():
    """Private, empty file systems over everything the installation and the upgrade write to."""
    # /etc/resolv.conf usually points below /run: keep what it says readable at the same place.
    resolver, said = Path(os.path.realpath('/etc/resolv.conf')), Path('/etc/resolv.conf').read_bytes()
    run([MOUNT, '--make-rprivate', '/'])
    for path in COVERED:
        run([MOUNT, '-t', 'tmpfs', '-o', 'mode=0700' if path == '/var/lib/xq-user-proxy' else 'mode=0755', 'tmpfs', path])
        if os.listdir(path):
            raise SystemExit(f'{path} was not covered')
    if not resolver.exists():
        resolver.parent.mkdir(parents=True)
        resolver.write_bytes(said)
        resolver.chmod(0o644)
    REHEARSAL.mkdir(mode=0o700)
    for name, text in (('systemctl', SYSTEMCTL), ('systemd-analyze', '#!/bin/sh\nexit 0\n')):
        (REHEARSAL / name).write_text(text)
        (REHEARSAL / name).chmod(0o755)
        run([MOUNT, '--bind', REHEARSAL / name, '/usr/bin/' + name])
        if Path('/usr/bin/' + name).read_text() != text:
            raise SystemExit(f'/usr/bin/{name} was not covered')
    (REHEARSAL / 'answers.json').write_text(json.dumps({cc.NAME: [cc.CORE_ANSWER]}))


def install_frozen():
    """The frozen package as its installer left it."""
    for source, target, mode in ((OLD / 'xq-user-proxyctl', CONTROLLER, 0o755),
                                 (OLD / 'xq-user-proxy.service', UNIT, 0o644),
                                 (OLD / 'sing-box.json', CONFIG_DIR / 'sing-box.json', 0o600),
                                 (OLD / 'verify.py', LIB_DIR / 'verify.py', 0o755)):
        target.write_bytes(source.read_bytes())
        target.chmod(mode)
    for target, text in ((CONFIG_DIR / 'managed-by', 'xq-user-proxy-v1\n'),
                         (VAR_DIR / 'latest-backup', '/var/backups/xq-user-proxy-rehearsal\n')):
        target.write_text(text)
        target.chmod(0o600)


def network():
    run([cc.IP, 'link', 'set', 'lo', 'up'])
    run([cc.IP, 'link', 'add', cc.WAN, 'type', 'dummy'])
    run([cc.IP, 'link', 'set', cc.WAN, 'up'])
    run([cc.IP, 'address', 'add', cc.WAN_ADDRESS + '/24', 'dev', cc.WAN])
    run([cc.IP, 'route', 'add', 'default', 'dev', cc.WAN])
    for address in (cc.LAN, cc.HOST_LOCAL):
        run([cc.IP, 'address', 'add', address + '/32', 'dev', 'lo'])
    for address, answer in cc.STAND_INS.items():
        cc.child('resolver ' + address, cc.RESOLVER, 0, address, 53, answer)
    run([cc.NFT, '-f', '-'], data=cc.COUNTERS)


def controller(verb, check=True):
    done = subprocess.run([str(CONTROLLER), verb], capture_output=True, text=True, timeout=200,
                          env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    if check and done.returncode:
        raise AssertionError(f'{CONTROLLER} {verb}: exit {done.returncode}\n{done.stdout}{done.stderr}\n' + journal())
    return done


def journal():
    path = REHEARSAL / 'journal.log'
    return '--- stand-in journal ---\n' + path.read_text()[-3000:] if path.exists() else ''


def upgrade(user, *extra):
    return subprocess.run([sys.executable, '-I', str(UPGRADE), '--user', user, '--probe-name', cc.NAME,
                           '--probe-resolver', cc.PUBLIC, '--egress-url', '', *extra],
                          capture_output=True, text=True, timeout=400)


def listening(port):
    return tuple(bool(run([cc.SS, '-Hln', kind, 'src', '127.0.0.1', 'sport', '=', f':{port}']).strip()) for kind in ('-t', '-u'))


def wait_listening(port):
    for _ in range(50):
        if listening(port) == (True, True):
            return
        time.sleep(0.1)
    raise AssertionError(f'nothing listens on 127.0.0.1:{port}\n' + journal())


def core_pid():
    shown = run(['/usr/bin/systemctl', 'show', 'xq-user-proxy.service', '--property=MainPID,ActiveState'])
    return int(shown.split('MainPID=')[1].split()[0])


def owner_dns_works(owner, what):
    for mode in ('udp', 'tcp'):
        for address in (cc.STUB, cc.PUBLIC):
            cc.expect(cc.probe(owner, address, mode), cc.CORE_ANSWER, f'owner DNS to {address} ({mode}) {what}')


def installed():
    """sha256 of every file of the installation, to compare whole states."""
    found = {}
    for top in (CONTROLLER, UNIT, CONFIG_DIR, LIB_DIR, VAR_DIR):
        for path in ([top] if top.is_file() else sorted(top.rglob('*'))):
            if path.is_file():
                found[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def expect_new_installation(owner):
    files = installed()
    assert hashlib.sha256((NEW / 'xq-user-proxyctl').read_bytes()).hexdigest() == files[str(CONTROLLER)]
    assert ' prepare' in UNIT.read_text() and 'CAP_NET_BIND_SERVICE' in UNIT.read_text()
    config = json.loads((CONFIG_DIR / 'sing-box.json').read_text())
    assert [item['listen_port'] for item in config['inbounds'] if item['tag'] == 'uid-dns'] == [NEW_PORT]
    assert json.loads((CONFIG_DIR / 'settings.json').read_text())['uid'] == owner
    assert (CONFIG_DIR / 'managed-by').read_text() == 'xq-user-tun-portable-v1\n'
    assert not (LIB_DIR / 'verify.py').exists() and (LIB_DIR / 'bin/sing-box').stat().st_mode & 0o777 == 0o755
    assert str(VAR_DIR / 'upgrade-backup') in files


class Load:
    """The owner and another user asking DNS without pause, as real sessions would during the upgrade."""

    def __init__(self, owner):
        self.logs = {'owner': REHEARSAL / 'owner.jsonl', 'other': REHEARSAL / 'other.jsonl'}
        stub = cc.STAND_INS[cc.STUB]
        targets = {'owner': (owner, [f'{cc.STUB}/udp/{cc.CORE_ANSWER}', f'{cc.PUBLIC}/udp/{cc.CORE_ANSWER}',
                                     f'{cc.STUB}/tcp/{cc.CORE_ANSWER}', f'{cc.PUBLIC}/tcp/{cc.CORE_ANSWER}']),
                   'other': (cc.OTHER, [f'{cc.STUB}/udp/{stub}', f'{cc.STUB}/tcp/{stub}'])}
        self.children = [subprocess.Popen([sys.executable, '-I', '-c', LOAD, str(uid), str(self.logs[who]),
                                           cc.NAME, *items]) for who, (uid, items) in targets.items()]
        self.kept = REHEARSAL / 'kept.jsonl'
        self.children.append(subprocess.Popen([sys.executable, '-I', '-c', KEPT, str(owner), str(self.kept),
                                               cc.STUB, cc.NAME, cc.CORE_ANSWER]))
        # Every packet on the stand-in uplink, to name what a non-zero count consists of, and the
        # public resolver's side of loopback, to know which connections the frozen rules translated.
        self.captures = {}
        for name, interface, what in (('uplink', cc.WAN, 'ip'), ('loopback', 'lo', f'ip and host {cc.PUBLIC}')):
            target = open(REHEARSAL / f'{name}.capture', 'w')
            self.captures[name] = (subprocess.Popen(['/usr/bin/tcpdump', '-ni', interface, '-l', '-tt', what],
                                                    stdout=target, stderr=subprocess.DEVNULL), target)
        time.sleep(1.0)
        self.started, self.base = time.time(), cc.stray()

    def finish(self):
        returned = time.time()
        time.sleep(2.0)
        finished = time.time()
        for child in self.children:
            child.terminate()
            child.wait(timeout=20)
        counted = cc.stray() - self.base        # read first: the captures then hold at least these packets
        seen = {}
        for name, (process, target) in self.captures.items():
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            target.close()
            seen[name] = [f'+{float(line.split()[0]) - self.started:.3f}s ' + ' '.join(line.split()[1:])
                          for line in (REHEARSAL / f'{name}.capture').read_text().splitlines() if line[:1].isdigit()]
        out = [line for line in seen['uplink'] if f' IP {cc.WAN_ADDRESS}.' in line]
        # A connection whose answers came in on loopback was translated by the frozen rules.
        translated = {line.split(f'> {cc.WAN_ADDRESS}.')[1].split(':')[0] for line in seen['loopback']
                      if f' IP {cc.PUBLIC}.53 > {cc.WAN_ADDRESS}.' in line}
        # The one thing the switch itself is allowed: closing segments of such a connection that ended
        # in the instant before the rules were replaced. The far end acknowledges a FIN up to 40 ms late;
        # when the rules change inside that time the acknowledgement is lost, and what the kernel then
        # repeats for the closed socket has neither a UID nor a flow under the new rules. Nothing with
        # payload, and nothing of a connection begun under the new rules.
        self.closing = [line for line in out if 'Flags [F.]' in line and line.rstrip().endswith('length 0')
                        and line.split(f'{cc.WAN_ADDRESS}.')[1].split()[0] in translated]
        self.uplink = [line for line in out if line not in self.closing]
        results = {who: [json.loads(line) for line in path.read_text().splitlines()] for who, path in self.logs.items()}
        during = {who: [item for item in items if self.started <= item['t'] <= finished] for who, items in results.items()}
        failed = {who: [item for item in items if not item['ok']] for who, items in during.items()}
        outage = (max(item['t'] for item in failed['owner']) - min(item['t'] for item in failed['owner'])
                  if failed['owner'] else 0.0)
        kept = [json.loads(line) for line in self.kept.read_text().splitlines()]
        self.kept_before = [item['ok'] for item in kept if item['t'] < self.started]
        self.kept_after = [item['ok'] for item in kept if item['t'] >= returned]
        assert counted <= len(self.closing) + len(self.uplink), (counted, seen['uplink'])
        return dict(owner=len(during['owner']), owner_failed=len(failed['owner']), outage=outage,
                    other=len(during['other']), other_failed=len(failed['other']),
                    last_owner_ok=bool(during['owner']) and during['owner'][-1]['ok'], stray=len(self.uplink),
                    closing=len(self.closing))


def frozen_on(owner):
    controller('on')
    controller('check')
    wait_listening(OLD_PORT)
    owner_dns_works(owner, 'under the frozen controller')
    cc.expect(cc.probe(cc.OTHER, cc.STUB), cc.STAND_INS[cc.STUB], 'another UID DNS under the frozen controller')
    assert 'guard_source' not in json.loads((STATE / 'state.json').read_text()) and not (STATE / 'core.json').exists()


def abandoned(owner):
    """Owner queries given up before their answer; returns what of them then left by the uplink.

    Counted by source port, so that repeats still due for a connection of the
    switch itself (see Load.finish) are not taken for these.
    """
    capture = subprocess.Popen(['/usr/bin/tcpdump', '-ni', cc.WAN, '-l', '-tt', 'ip'], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    time.sleep(1.0)
    ports = [str(cc.probe(owner, cc.PUBLIC, mode)['source']) for mode in ('udp-giveup', 'tcp-giveup') for _ in range(10)]
    assert len(set(ports)) == 20 and '0' not in ports, ports
    time.sleep(2)
    capture.send_signal(signal.SIGINT)
    try:
        seen = capture.communicate(timeout=5)[0]
    except subprocess.TimeoutExpired:
        capture.kill()
        seen = capture.communicate()[0]
    return [line for line in seen.splitlines()
            if any(f'{cc.WAN_ADDRESS}.{port} ' in line or f'udp port {port} ' in line for port in ports)]


def scenario_on(user, owner):
    frozen_on(owner)
    old_pid, load = core_pid(), Load(owner)
    done = upgrade(user, '--apply')
    result = load.finish()
    print(done.stdout.rstrip(), flush=True)
    assert done.returncode == 0, done.stdout + done.stderr + journal()
    expect_new_installation(owner)
    assert listening(NEW_PORT) == (True, True) and listening(OLD_PORT) == (False, False)
    assert core_pid() not in (0, old_pid)
    assert result['stray'] == 0, (f'{result["stray"]} owner packets left by the uplink during the upgrade:\n'
                                  + '\n'.join(load.uplink))
    if result['closing']:
        print(f'INFO: {result["closing"]} bare FIN segments left by the uplink: repeats for a connection to the public '
              'resolver that the frozen rules had translated and that ended in the instant before the switch', flush=True)
    assert result['other_failed'] == 0, f'{result["other_failed"]} of {result["other"]} queries of another user failed'
    assert result['last_owner_ok'] and result['owner_failed'] < result['owner'], result
    assert load.kept_before and all(load.kept_before), load.kept_before
    assert len(load.kept_after) >= 3 and all(load.kept_after), (
        'an owner program that keeps one socket for its DNS queries gets no answers after the upgrade: '
        f'{load.kept_after}\n' + run([cc.CONNTRACK, '-L', '-f', 'ipv4', '--mark', '0x20000000/0x20000000']))
    print(f'PASS: upgraded while ON. During the upgrade the owner sent {result["owner"]} DNS queries, '
          f'{result["owner_failed"]} failed within {result["outage"]:.1f} s around the core restart; none of its packets '
          f'left by the uplink; all {result["other"]} queries of another user were answered by the host resolver', flush=True)
    owner_dns_works(owner, 'after the upgrade')
    leaked = abandoned(owner)
    assert not leaked, 'packets for closed owner sockets left by the uplink after the upgrade:\n' + '\n'.join(leaked)
    print('PASS: after the upgrade, 20 owner queries abandoned before their answer: nothing left by the uplink', flush=True)
    state = json.loads((STATE / 'state.json').read_text())
    assert state['phase'] == 'on' and state.get('guard_source') and json.loads((STATE / 'core.json').read_text())['loaded']
    marked = run([cc.CONNTRACK, '-L', '-f', 'ipv4', '--mark', '0x20000000/0x20000000'])
    assert f'sport={OLD_PORT} ' not in marked, 'translations to the frozen entry are still in conntrack:\n' + marked
    controller('off')
    status = controller('status')
    assert '开关：OFF' in status.stdout and '残留检查：未发现' in status.stdout, status.stdout
    assert 'xq_user_proxy' not in run([cc.NFT, 'list', 'tables']) and '18410' not in run([cc.IP, 'rule', 'show'])
    assert not run([cc.CONNTRACK, '-L', '-f', 'ipv4', '--mark', '0x20000000/0x20000000']).strip()
    cc.expect(cc.probe(owner, cc.STUB), cc.STAND_INS[cc.STUB], 'owner DNS after OFF')
    controller('on')
    wait_listening(NEW_PORT)
    owner_dns_works(owner, 'after OFF and ON with the new controller')
    controller('off')
    print('PASS: an owner program that keeps one socket for its DNS queries is answered again after the upgrade '
          '(no translation to the frozen entry is left); the new controller then switches OFF cleanly, ON again '
          'and OFF again', flush=True)


def scenario_off(user, owner):
    before = run([cc.NFT, 'list', 'ruleset']), run([cc.IP, 'rule', 'show']), run([cc.IP, 'route', 'show', 'table', 'all'])
    done = upgrade(user, '--apply')
    print(done.stdout.rstrip(), flush=True)
    assert done.returncode == 0, done.stdout + done.stderr
    expect_new_installation(owner)
    assert before == (run([cc.NFT, 'list', 'ruleset']), run([cc.IP, 'rule', 'show']),
                      run([cc.IP, 'route', 'show', 'table', 'all'])), 'the network changed although the proxy was OFF'
    assert core_pid() == 0 and not STATE.exists()
    controller('on')
    wait_listening(NEW_PORT)
    owner_dns_works(owner, 'after the first ON of the new controller')
    assert not abandoned(owner)
    controller('off')
    print('PASS: upgraded while OFF without any change to the network; the new controller then switches ON and OFF', flush=True)


def scenario_restore(user, owner):
    frozen_on(owner)
    before, old_pid = installed(), core_pid()
    (REHEARSAL / 'new-core-cannot-start').write_text('')
    load = Load(owner)
    done = upgrade(user, '--apply')
    result = load.finish()
    print(done.stdout.rstrip(), flush=True)
    assert done.returncode == 1 and '已恢复' in done.stdout, done.stdout + done.stderr + journal()
    after = installed()
    assert after == dict(before, **{str(VAR_DIR / 'upgrade-backup'): after.get(str(VAR_DIR / 'upgrade-backup'))}), \
        sorted(set(before.items()) ^ set(after.items()))
    assert not (STATE / 'core.json').exists()
    controller('check')
    wait_listening(OLD_PORT)
    assert listening(NEW_PORT) == (False, False) and core_pid() not in (0, old_pid)
    owner_dns_works(owner, 'after the frozen version was brought back')
    assert result['stray'] == 0, f'{result["stray"]} owner packets left by the uplink during the failed upgrade'
    if result['closing']:
        print(f'INFO: {result["closing"]} bare FIN segments of a translated connection that ended at the switch', flush=True)
    assert result['other_failed'] == 0, f'{result["other_failed"]} of {result["other"]} queries of another user failed'
    assert result['last_owner_ok'], result
    assert len(load.kept_after) >= 3 and all(load.kept_after), (
        'an owner program that keeps one socket for its DNS queries gets no answers after the restore: '
        f'{load.kept_after}\n' + run([cc.CONNTRACK, '-L', '-f', 'ipv4', '--mark', '0x20000000/0x20000000']))
    print(f'PASS: the new core could not start; every file of the frozen installation is back and its controller, '
          f'rules and core work again. Meanwhile the owner sent {result["owner"]} DNS queries, {result["owner_failed"]} '
          f'failed within {result["outage"]:.1f} s; none of its packets left by the uplink; all {result["other"]} queries '
          'of another user were answered', flush=True)
    controller('off')


def scenario_partial(user, owner):
    frozen_on(owner)
    rendered = REHEARSAL / 'rendered'
    rendered.mkdir()
    installer = load_module(NEW / 'install.py', 'xq_rehearsal_installer')
    account = pwd.getpwnam(user)
    installer.render(rendered, dict(schema=1, user=user, uid=account.pw_uid, gid=account.pw_gid,
                                    proxy_ip='192.168.5.34', proxy_port=4066))
    # As if an earlier run had been killed after its third file: the unit and the marker are still the old ones.
    for name, target, mode in (('settings.json', CONFIG_DIR / 'settings.json', 0o600),
                               ('sing-box.json', CONFIG_DIR / 'sing-box.json', 0o600),
                               ('xq-user-proxyctl', CONTROLLER, 0o755)):
        target.write_bytes((rendered / name).read_bytes())
        target.chmod(mode)
    assert controller('status', check=False).returncode == 1
    owner_dns_works(owner, 'in the half-upgraded state (the old core and rules still serve)')
    load = Load(owner)
    done = upgrade(user, '--apply')
    result = load.finish()
    print(done.stdout.rstrip(), flush=True)
    assert done.returncode == 0 and '上次升级没有完成' in done.stdout, done.stdout + done.stderr + journal()
    expect_new_installation(owner)
    assert listening(NEW_PORT) == (True, True) and listening(OLD_PORT) == (False, False)
    assert result['stray'] == 0 and result['other_failed'] == 0 and result['last_owner_ok'], result
    if result['closing']:
        print(f'INFO: {result["closing"]} bare FIN segments of a translated connection that ended at the switch', flush=True)
    owner_dns_works(owner, 'after the upgrade was completed')
    controller('off')
    print('PASS: an upgrade that had stopped after replacing the configuration and the controller is completed by '
          'running the script again; nothing left by the uplink, another user unaffected', flush=True)


def scenario_examine(user, owner):
    frozen_on(owner)
    before = (installed(), run([cc.NFT, '--stateless', 'list', 'ruleset']), run([cc.IP, 'rule', 'show']),
              (STATE / 'state.json').read_text(), core_pid(), sorted(os.listdir('/var/backups')))
    done = upgrade(user)
    print(done.stdout.rstrip(), flush=True)
    assert done.returncode == 0 and '未改动任何东西' in done.stdout, done.stdout + done.stderr
    assert before == (installed(), run([cc.NFT, '--stateless', 'list', 'ruleset']), run([cc.IP, 'rule', 'show']),
                      (STATE / 'state.json').read_text(), core_pid(), sorted(os.listdir('/var/backups')))
    owner_dns_works(owner, 'after the examination')
    # A listener on the new private DNS port is found before anything is changed.
    cc.child('squatter', cc.RESOLVER, 0, '127.0.0.1', NEW_PORT, cc.FORGED)
    refused = upgrade(user, '--apply')
    assert refused.returncode == 1 and f'127.0.0.1:{NEW_PORT}' in refused.stderr, refused.stdout + refused.stderr
    assert before[0] == installed() and before[4] == core_pid() and not os.listdir('/var/backups')
    cc.stop('squatter')
    controller('off')
    print('PASS: without --apply nothing changes; with --apply an occupied new DNS port is refused before any change', flush=True)


def main():
    parser = argparse.ArgumentParser(description='在一次性命名空间中演练 upgrade-to-portable.py。')
    parser.add_argument('--user', required=True, help='冻结版控制器中固定的用户名')
    parser.add_argument('--scenario', required=True, choices=('on', 'off', 'restore', 'partial', 'examine'))
    args = parser.parse_args()
    refuse_unless_isolated()
    # `unshare --fork` (util-linux 2.37) starts its child with SIGINT and SIGTERM ignored, and an
    # ignored signal stays ignored in every program started from here that installs no handler.
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    owner = pwd.getpwnam(args.user).pw_uid
    cover_the_installation()
    try:
        install_frozen()
        network()
        globals()['scenario_' + args.scenario](args.user, owner)
        print(f'REHEARSAL PASSED: scenario {args.scenario}', flush=True)
    except BaseException:
        print(journal(), file=sys.stderr)
        log = REHEARSAL / 'core.log'
        if log.exists():
            print('--- core log ---\n' + log.read_text(errors='replace')[-2000:], file=sys.stderr)
        raise
    finally:
        subprocess.run(['/usr/bin/systemctl', 'stop', 'xq-user-proxy.service'], capture_output=True)
        for name in list(cc.CHILDREN):
            cc.CHILDREN.pop(name).kill()


if __name__ == '__main__':
    main()
