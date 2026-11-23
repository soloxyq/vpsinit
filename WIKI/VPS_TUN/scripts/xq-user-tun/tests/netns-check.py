#!/usr/bin/python3 -I
"""Exercise the generated rules and the route cleanup on a real kernel, inside
a fresh, disposable network namespace only.

    sudo unshare --net python3 -I tests/netns-check.py

runs every check with three real identities: the owner, another user and root
(the core). Without root, a rootless user namespace has one identity only. Two
commands: the shell must know HOSTNS before it expands the second one:

    HOSTNS=$(readlink /proc/self/ns/net)
    unshare --user --map-root-user --net env XQ_HOST_NETNS="$HOSTNS" python3 -I tests/netns-check.py

There the same checks run with that one identity cast as the owner, as a
bystander or as a sender that is not the core, by changing the UID constants
the rules are generated from. Checks that need two users at the same time are
reported as skipped, and a process without CAP_NET_BIND_SERVICE stands in for
"another user" where only the right to bind a port matters.

No service and no controller lifecycle call; no host route, rule, sysctl or DNS
change. Every controller path is redirected to a temporary directory, and the
controller may only run ip, nft and conntrack, which act on this namespace. The
sysctls written are this namespace's own: ip_unprivileged_port_start, and
rp_filter and disable_ipv6 of the xq-utun that exists only here.
"""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import runpy
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

BASE = Path(__file__).resolve().parents[1]
OWNER = 23456  # Deliberately unrelated to the development server's account.
OTHER = 23457
NOBODY = 23458  # the UID of no socket in this test
IP = '/usr/sbin/ip'
NFT = '/usr/sbin/nft'
CONNTRACK = '/usr/sbin/conntrack'
SETPRIV = '/usr/bin/setpriv'
TABLE = 'xq_user_proxy'
THRESHOLD = Path('/proc/sys/net/ipv4/ip_unprivileged_port_start')  # per network namespace
# Resolvers of every class, each with its own listener. PUBLIC is a public address this host
# itself has; REMOTE is a public address elsewhere, where nobody answers: by the uplink for
# everybody else, through the TUN for the owner.
STUB, PUBLIC, REMOTE, LAN = '127.0.0.53', '203.0.113.53', '203.0.113.54', '10.77.0.53'
STRANGER = '203.0.113.80'   # a public address no flow of this test goes to
WAN_ADDRESS = '198.18.0.2'
# A public resolver "from" whose port 53 somebody sends this host a datagram before the owner
# asks it, the interface that datagram arrives by, and this host's address on it.
SEEDED, SEED_UPLINK, SEED_LOCAL = '203.0.113.81', 'xq-seed-up', '198.18.1.2'
SEEDED6, SEED_LOCAL6 = '2001:db8:5eed::81', '2001:db8:5eed::2'
V6_LOOPBACK, ULA, V6_PUBLIC = '::1', 'fd00:77::53', '2001:db8::53'
RESOLVERS = {STUB: 'stub', PUBLIC: 'public', REMOTE: None, LAN: 'lan',
             V6_LOOPBACK: 'v6-loopback', ULA: 'ula', V6_PUBLIC: 'v6-public'}
USAGE = 'sudo unshare --net python3 -I tests/netns-check.py   (or the rootless form described in this file)'
LISTENERS = {}


def run(args, *, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=15)
    if result.returncode:
        raise RuntimeError(f'{args!r}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result.stdout


# Children take the identity they are told, when it is not already theirs.
IDENTITY = 'if uid != os.getuid(): os.setgroups([]);os.setgid(uid);os.setuid(uid)'

ECHO = r'''
import json,os,socket,sys,threading
uid,address,port,label=int(sys.argv[1]),sys.argv[2],int(sys.argv[3]),sys.argv[4]
''' + IDENTITY + r'''
family=socket.AF_INET6 if ':' in address else socket.AF_INET
udp=socket.socket(family,socket.SOCK_DGRAM);udp.bind((address,port))
tcp=socket.socket(family,socket.SOCK_STREAM);tcp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
tcp.bind((address,port));tcp.listen()
def udp_loop():
    while True:
        _,peer=udp.recvfrom(1024);udp.sendto(label.encode(),peer)
threading.Thread(target=udp_loop,daemon=True).start()
print(json.dumps({'ready':label}),flush=True)
while True:
    conn,_=tcp.accept()
    with conn:
        conn.settimeout(2)
        try: conn.recv(1024);conn.sendall(label.encode())
        except OSError: pass
'''

PROBE = r'''
import json,os,socket,sys,time
uid,dest,port,tcp,source=sys.argv[1:]
uid,port,tcp,source=int(uid),int(port),int(tcp),int(source)
''' + IDENTITY + r'''
family=socket.AF_INET6 if ':' in dest else socket.AF_INET
result={'reply':None,'error':None}
with socket.socket(family,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
    s.settimeout(1.0)
    if source: s.bind(('::' if family==socket.AF_INET6 else '0.0.0.0',source))
    started=time.monotonic()
    try:
        s.connect((dest,port));s.sendall(b'query');result['reply']=s.recv(1024).decode()
    except OSError as error: result['error']=type(error).__name__
    result['seconds']=round(time.monotonic()-started,3)
    result['source']=s.getsockname()[1]
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


def echo(name, uid, address, port, label):
    child = subprocess.Popen([sys.executable, '-I', '-u', '-c', ECHO, str(uid), address, str(port), label],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ready, _, _ = select.select([child.stdout], [], [], 5)
    if not ready or not child.stdout.readline():
        child.kill()
        raise RuntimeError(f'listener {label} on {address}:{port} did not start: {child.stderr.read()}')
    LISTENERS[name] = child


def stop(name):
    child = LISTENERS.pop(name)
    child.terminate()
    child.wait(timeout=5)


def probe(uid, dest, port=53, tcp=False, source=0):
    return json.loads(run([sys.executable, '-I', '-c', PROBE, str(uid), dest, str(port), str(int(tcp)), str(source)]))


def expect(result, reply, what):
    assert result['reply'] == reply, f'{what}: expected {reply!r}, got {result!r}'


def hits(chain, verdict):
    data = json.loads(run([NFT, '-j', 'list', 'chain', 'inet', TABLE, chain]))
    return sum(expr['counter']['packets']
               for item in data['nftables']
               if any(verdict in e for e in item.get('rule', {}).get('expr', []))
               for expr in item.get('rule', {}).get('expr', []) if 'counter' in expr)


# The test's own counters of where its probes leave the host. Interface
# statistics would also count the kernel's IPv6 housekeeping packets.
EXITS = f'''table inet xq_netns_check {{
  counter tun {{ }}
  counter wan {{ }}
  counter dns_tun {{ }}
  counter dns_wan {{ }}
  counter stranger {{ }}
  counter seeded {{ }}
  counter seeded_tcp {{ }}
  counter seeded6 {{ }}
  chain postrouting {{
    type filter hook postrouting priority 100; policy accept;
    udp dport 9999 oifname "xq-utun" counter name tun
    udp dport 9999 oifname "test-wan" counter name wan
    ip daddr {REMOTE} meta l4proto {{ tcp, udp }} th dport 53 oifname "xq-utun" counter name dns_tun
    ip daddr {REMOTE} meta l4proto {{ tcp, udp }} th dport 53 oifname "test-wan" counter name dns_wan
    ip daddr {STRANGER} oifname "test-wan" counter name stranger
    ip daddr {SEEDED} udp dport {{ 53, 443, 40000-49999 }} oifname "{SEED_UPLINK}" counter name seeded
    ip daddr {SEEDED} tcp dport 443 tcp flags & (syn | rst) == syn oifname "{SEED_UPLINK}" counter name seeded_tcp
    ip6 daddr {SEEDED6} udp dport 443 oifname "{SEED_UPLINK}" counter name seeded6
  }}
}}
'''


def counted(*names):
    return tuple(json.loads(run([NFT, '-j', 'list', 'counter', 'inet', 'xq_netns_check', name]))
                 ['nftables'][-1]['counter']['packets'] for name in names)


def exits():
    """Probes to UDP port 9999 that left through (the TUN, the uplink) so far."""
    return counted('tun', 'wan')


def dns_exits():
    """DNS packets for REMOTE that left through (the TUN, the uplink) so far."""
    return counted('dns_tun', 'dns_wan')


def refuse_unsafe_namespace():
    if os.geteuid() != 0:
        raise SystemExit('Needs root inside a new network namespace: ' + USAGE)
    try:
        here, host = os.stat('/proc/self/ns/net'), os.stat('/proc/1/ns/net')
        on_host = (here.st_dev, here.st_ino) == (host.st_dev, host.st_ino)
    except PermissionError:
        # A rootless user namespace may not look at PID 1, so its caller names
        # the host namespace. Such a namespace has no privilege over the host
        # network in any case.
        declared = os.environ.get('XQ_HOST_NETNS', '')
        on_host = not declared.startswith('net:[') or os.readlink('/proc/self/ns/net') == declared
    if on_host:
        raise SystemExit('Refusing host network: ' + USAGE)
    interfaces = json.loads(run([IP, '-j', 'link', 'show']))
    if [item['ifname'] for item in interfaces] != ['lo']:
        raise SystemExit('Refusing a namespace that is not fresh (expected only lo)')


def can_switch_to(*uids):
    ranges = [tuple(map(int, line.split())) for line in Path('/proc/self/uid_map').read_text().splitlines()]
    return all(any(first <= uid < first + count for first, _, count in ranges) for uid in uids)


def sandbox(ctl, base):
    """The namespace shares the host file system: keep the controller inside `base`."""
    scope = ctl['firewall'].__globals__
    for directory in ('state', 'etc'):
        (base / directory).mkdir()
    scope.update(STATE=base / 'state', STATEFILE=base / 'state/state.json', ENABLED=base / 'state/enabled',
                 CONFIG=base / 'etc/sing-box.json', SETTINGS=base / 'etc/settings.json',
                 RESOLV=base / 'etc/resolv.conf', HOST='198.51.100.10', PORT=1080)
    atomic, command = scope['atomic'], scope['run']

    def checked_atomic(path, content):
        if not Path(path).resolve().is_relative_to(base):
            raise AssertionError('Controller attempted a write outside the test directory: ' + str(path))
        return atomic(path, content)

    def checked_run(args, **kwargs):
        if args == [scope['SYSTEMCTL'], 'is-active', '--quiet', scope['SERVICE']]:
            # No systemd here: the core unit is simply "not running". Nothing is executed.
            return subprocess.CompletedProcess(args, 3, '', '')
        if args[0] not in (IP, NFT, CONNTRACK):
            raise AssertionError('Unexpected controller command in the namespace test: ' + repr(args))
        return command(args, **kwargs)

    scope.update(atomic=checked_atomic, run=checked_run)
    return scope


def cast(scope, owner, core):
    """Load the guard for this owner UID and core UID; forget earlier connections."""
    scope.update(UID=owner, GID=owner, USER='test-owner', CORE_UID=core)
    for active in (True, False):
        run([NFT, '--check', '-f', '-'], data=scope['firewall'](active))
    scope['install_firewall']({})        # the controller's own load: replaces an existing table
    assert scope['table_exists']()
    run([CONNTRACK, '-F'])


def check_route_cleanup(scope):
    """A1: cleanup where the routing table never existed, exists in part, and is already clean."""
    remove, routes, rules = scope['remove_routes'], scope['routes'], scope['rules']
    for family in ('-4', '-6'):
        # The answer of the real tool that used to make OFF fail on every retry.
        listing = subprocess.run([IP, '-j', family, 'route', 'show', 'table', '20261'], capture_output=True)
        assert listing.returncode != 0, 'this namespace already has routing table 20261'
        assert routes(family) == []
    remove()
    remove()
    print('PASS: remove_routes() twice where routing table 20261 was never created', flush=True)

    def owned():
        return ([scope['has_route'](item) for item in (scope['TUN_ROUTE'], scope['BLACKHOLE'], scope['UNREACHABLE'])],
                [any(map(scope['own_rule'], rules(family))) for family in ('-4', '-6')])

    run(scope['route_command'](scope['BLACKHOLE'], 'replace'))      # ON stopped between its two routes
    assert owned() == ([False, True, False], [False, False])
    remove()
    assert owned() == ([False, False, False], [False, False])
    remove()                                                        # the table now exists and is empty
    scope['install_routes']()
    scope['install_routes']()                                       # repeating ON's step adds nothing
    run(scope['route_command'](scope['TUN_ROUTE'], 'replace'))
    assert owned() == ([True, True, True], [True, True])
    foreign = [IP, '-4', 'route', 'add', '198.51.100.0/24', 'dev', 'test-wan', 'table', '20261']
    run(foreign)
    remove()
    assert owned() == ([False, False, False], [False, False])
    assert [route['dst'] for route in routes('-4')] == ['198.51.100.0/24'], routes('-4')
    remove()
    foreign[3] = 'del'
    run(foreign)
    print('PASS: partial and complete sets of owned routes and rules are removed; '
          'a foreign route in the same table is kept', flush=True)


def check_owner(scope, owner):
    """What the owner gets for every class of resolver, against the classifier's answer."""
    port = scope['DNS_PORT']
    for tcp in (False, True):
        expect(probe(owner, '127.0.0.1', 18080, tcp), 'ordinary', 'owner ordinary loopback traffic')
        expect(probe(owner, '127.0.0.1', port, tcp), 'private', 'owner asking the private entry directly')
        for address, original in RESOLVERS.items():
            kind = scope['nameserver_path'](ipaddress.ip_address(address))[0]
            # Nothing answers inside this test's TUN; where the query left is counted instead.
            reply = {'proxied': 'private', 'tunnel': None, 'lan': original, 'blocked': None}[kind]
            before = dns_exits()
            expect(probe(owner, address, tcp=tcp), reply, f'owner DNS to {address} ({kind}, tcp={tcp})')
            entered, leaked = (now - then for now, then in zip(dns_exits(), before))
            assert (entered > 0, leaked) == (kind == 'tunnel', 0), \
                f'owner DNS to {address} ({kind}, tcp={tcp}): {entered} packets into the TUN, {leaked} by the uplink'
    kinds = {address: scope['nameserver_path'](ipaddress.ip_address(address))[0] for address in RESOLVERS}
    assert kinds == {STUB: 'proxied', PUBLIC: 'proxied', REMOTE: 'tunnel', LAN: 'lan',
                     V6_LOOPBACK: 'blocked', ULA: 'lan', V6_PUBLIC: 'blocked'}, kinds
    flows = run([CONNTRACK, '-L'])
    remote = [line for line in flows.splitlines() if f'dst={REMOTE} ' in line]
    assert remote and not any('zone=' in line or f'sport={port} ' in line for line in remote), remote
    print(f'PASS: owner DNS over UDP and TCP: the loopback stub and a public address of this host go to '
          f'127.0.0.1:{port}; a public resolver elsewhere enters the TUN untranslated, in the default zone, and '
          'never the uplink; LAN and ULA resolvers are reached directly; ::1 and public IPv6 are blocked; '
          'the classifier says the same', flush=True)


def check_bystander(scope, uid, who):
    """Root and other users keep the original servers and are refused the private entry."""
    rejected = hits('private_dns_access', 'reject')
    for tcp in (False, True):
        expect(probe(uid, '127.0.0.1', 18080, tcp), 'ordinary', f'{who} ordinary loopback traffic')
        for address, original in RESOLVERS.items():
            expect(probe(uid, address, tcp=tcp), original, f'{who} DNS to {address} (tcp={tcp})')
        expect(probe(uid, '127.0.0.1', scope['DNS_PORT'], tcp), None, f'{who} asking the private entry')
    assert hits('private_dns_access', 'reject') >= rejected + 2
    print(f'PASS: {who} reaches every original resolver and ordinary TCP/UDP; the private entry is refused', flush=True)


def check_cross_identity(scope, owner, other):
    first = probe(owner, '127.0.0.1', scope['DNS_PORT'])
    expect(first, 'private', 'owner asking the private entry')
    expect(probe(other, '127.0.0.1', scope['DNS_PORT'], source=first['source']), None,
           'another UID reusing the owner tuple to the private entry')
    print('PASS: another UID cannot borrow an owner conntrack tuple', flush=True)
    # All users share one conntrack table, and a just-closed UDP source port
    # can be reused by another UID within the conntrack timeout. In neither
    # order may one UID inherit the other's DNS translation.
    owner_first = probe(owner, STUB)
    expect(owner_first, 'private', 'owner DNS')
    expect(probe(other, STUB, source=owner_first['source']), 'stub', 'another UID reusing the owner source port')
    other_first = probe(other, STUB)
    expect(other_first, 'stub', 'another UID DNS')
    expect(probe(owner, STUB, source=other_first['source']), 'private', 'owner reusing the other source port')
    print('PASS: a reused UDP source port never carries DNS translation between UIDs', flush=True)


def check_dns_cleanup(scope, owner):
    """OFF's conntrack step: only this feature's DNS mappings go, and it can be repeated."""
    expect(probe(owner, STUB), 'private', 'owner DNS')
    expect(probe(owner, '127.0.0.1', 18080), 'ordinary', 'owner ordinary traffic')
    assert scope['dns_connections'](), 'the owner query left no marked DNS mapping'
    scope['delete_dns_connections']()
    assert scope['dns_connections']() == []
    assert 'dport=18080' in run([CONNTRACK, '-L']), 'an ordinary connection was deleted too'
    scope['delete_dns_connections']()
    print('PASS: delete_dns_connections() removes only the DNS mappings and succeeds again with none left', flush=True)


def check_listener_restart(scope, owner, core, unprivileged, who):
    """While the core is down nobody else can take the entry, and the owner fails fast."""
    port = scope['DNS_PORT']
    stop('private')
    assert unprivileged(port) == ['PermissionError'] * 4, unprivileged(port)
    assert unprivileged(port + 20000) == ['bound'] * 4, 'the control port should be bindable'
    for tcp in (False, True):
        result = probe(owner, STUB, tcp=tcp)
        assert (result['reply'], result['error']) == (None, 'ConnectionRefusedError') and result['seconds'] < 0.5, \
            f'owner DNS with the core down must fail at once, without the port 53 resolver: {result!r}'
    echo('private', core, '127.0.0.1', port, 'private')
    for tcp in (False, True):
        expect(probe(owner, STUB, tcp=tcp), 'private', 'owner DNS after the core listener came back')
    print(f'PASS: with the core listener stopped, {who} cannot bind 127.0.0.1:{port} or 0.0.0.0:{port} '
          '(PermissionError), the owner gets ECONNREFUSED at once instead of the port 53 resolver, '
          'and a restarted listener serves again', flush=True)


def check_forged_reply(scope, owner, squatter, who):
    """Even where the port can be squatted, an answer that is not the core's never arrives."""
    port, original = scope['DNS_PORT'], THRESHOLD.read_text()
    assert scope['endpoint_fault']() is None
    stop('private')
    THRESHOLD.write_text('0\n')             # this namespace only: ordinary users may now bind the entry
    try:
        assert 'ip_unprivileged_port_start' in scope['endpoint_fault']()
        echo('squatter', squatter, '127.0.0.1', port, 'forged')
        dropped = hits('dns_zone_output', 'drop')
        for tcp in (False, True):
            expect(probe(owner, STUB, tcp=tcp), None, f'owner DNS answered by {who} (tcp={tcp})')
        assert hits('dns_zone_output', 'drop') > dropped, 'the forged replies did not hit the identity rule'
        stop('squatter')
    finally:
        THRESHOLD.write_text(original)
    assert scope['endpoint_fault']() is None
    print(f'PASS: with ip_unprivileged_port_start lowered in this namespace, replies of {who} on port {port} '
          'are dropped and never reach the owner; the controller reports the lowered threshold', flush=True)


def check_flushed_ruleset(scope, owner):
    """A5: selection lives in nft, so without the table the owner's new connections go direct."""
    probe(owner, '203.0.113.10', 9999)
    assert exits() == (1, 0), f'an owner packet should enter the TUN: {exits()}'
    run([NFT, 'delete', 'table', 'inet', TABLE])        # what `nft flush ruleset` does to this table
    assert not scope['table_exists']()
    probe(owner, '203.0.113.10', 9999)
    assert exits() == (1, 1), f'without the table an owner packet should leave by the main route: {exits()}'
    expect(probe(owner, STUB), 'stub', 'owner DNS without the table')
    print('PASS: once the table is gone, a new owner connection leaves by the main route and owner DNS '
          'reaches the system resolver directly; table_exists() sees it', flush=True)


def check_tun_acl():
    before = hits('private_tun_access', 'drop')
    marked_route = json.loads(run([IP, '-j', 'route', 'get', '203.0.113.10', 'mark', '0x40000000']))
    assert marked_route[0]['dev'] == 'xq-utun'
    with socket.socket() as sock:
        sock.settimeout(0.6)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, 0x40000000)
        try:
            sock.connect(('203.0.113.10', 443))
        except OSError:
            pass
        else:
            raise AssertionError('Marked root unexpectedly connected through TUN')
    assert hits('private_tun_access', 'drop') > before
    print('PASS: marked traffic of a non-owner is denied at the TUN ACL', flush=True)


def check_core_loss(scope, owner, core, bystander):
    # Simulate core/TUN loss: only the test namespace changes, guard stays.
    run([IP, 'link', 'delete', 'xq-utun'])
    result = subprocess.run([IP, '-j', 'route', 'get', '203.0.113.10', 'mark', '0x40000000'],
                            text=True, capture_output=True)
    # Linux blackhole routes may return EINVAL ("Invalid argument"), whereas
    # unreachable routes return ENETUNREACH. Verify the route, not error prose.
    assert result.returncode != 0, result.stdout
    assert scope['has_route'](scope['BLACKHOLE']) and not scope['has_route'](scope['TUN_ROUTE'])
    root_route = json.loads(run([IP, '-j', 'route', 'get', '203.0.113.10']))
    assert root_route[0]['dev'] == 'test-wan'
    expect(probe(bystander, STUB), 'stub', 'non-owner DNS after the TUN disappeared')
    cast(scope, owner, core)
    before = dns_exits()
    result = probe(owner, REMOTE)
    assert result['reply'] is None and result['error'] and result['seconds'] < 0.5, \
        f'an owner datagram for the TUN must fail at once in the blackhole: {result!r}'
    # A TCP connection is blackholed like every public connection of the owner: until the program gives up.
    assert probe(owner, REMOTE, tcp=True)['reply'] is None
    assert dns_exits() == before, f'owner DNS for the lost TUN left the host: {dns_exits()} after {before}'
    print('PASS: core loss leaves the owner blackhole, for its DNS to a public resolver as for the rest, '
          'while unmarked routing/DNS of others remain available', flush=True)


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


def packet6(source, dest, sport, dport, data):
    """An IPv6 UDP datagram."""
    src, dst = socket.inet_pton(socket.AF_INET6, source), socket.inet_pton(socket.AF_INET6, dest)
    udp = struct.pack('>HHHH', sport, dport, 8 + len(data), 0) + data
    value = checksum(src + dst + struct.pack('>I3xB', len(udp), socket.IPPROTO_UDP) + udp) or 0xffff
    return (struct.pack('>IHBB', 6 << 28, len(udp), socket.IPPROTO_UDP, 64) + src + dst
            + udp[:6] + struct.pack('>H', value) + udp[8:])


def check_preseeded_flows(scope, owner, core):
    """An owner packet that conntrack takes for a reply still does not leave by the uplink.

    A packet from outside to a port of this host leaves a conntrack entry even
    when no socket has that port. What the owner then sends from that port to
    that sender is the reply direction of the entry. The core is absent here,
    so whatever is sent towards the TUN ends in the blackhole.
    """
    cast(scope, owner, core)

    def left_by_the_uplink(counter, seed, flow, ask, stays=True):
        os.write(fd, seed)
        time.sleep(0.3)
        known = ' '.join((run([CONNTRACK, '-L']) + run([CONNTRACK, '-L', '-f', 'ipv6'])).split())
        assert (flow in known) == stays, f'conntrack entry of the packet from outside: expected {stays} for {flow}'
        before = counted(counter)[0]
        result = ask()
        assert result['reply'] is None, result
        return counted(counter)[0] - before

    def outcomes(first):
        udp = lambda port, to: packet(socket.IPPROTO_UDP, SEEDED, SEED_LOCAL, struct.pack('>HHHH', to, port, 8 + 4, 0) + b'seed')
        syn = packet(socket.IPPROTO_TCP, SEEDED, SEED_LOCAL,
                     struct.pack('>HHIIBBHHH', 443, first + 3, 1000, 0, 5 << 4, 0x02, 65535, 0, 0))
        return {
            'DNS over UDP': left_by_the_uplink(
                'seeded', udp(first, 53), f'src={SEEDED} dst={SEED_LOCAL} sport=53 dport={first} ',
                lambda: probe(owner, SEEDED, source=first)),
            'UDP to port 443': left_by_the_uplink(
                'seeded', udp(first + 1, 443), f'src={SEEDED} dst={SEED_LOCAL} sport=443 dport={first + 1} ',
                lambda: probe(owner, SEEDED, port=443, source=first + 1)),
            'UDP to port 443 over IPv6': left_by_the_uplink(
                'seeded6', packet6(SEEDED6, SEED_LOCAL6, 443, first + 2, b'seed'),
                f'src={SEEDED6} dst={SEED_LOCAL6} sport=443 dport={first + 2} ',
                lambda: probe(owner, SEEDED6, port=443, source=first + 2)),
            # The kernel answers a SYN for a closed port with a RST, and conntrack drops an entry
            # whose only answer was a RST: a connection the owner then opens from that port is a
            # new one of its own.
            'TCP to port 443': left_by_the_uplink(
                'seeded_tcp', syn, f'src={SEEDED} dst={SEED_LOCAL} sport=443 dport={first + 3} ',
                lambda: probe(owner, SEEDED, port=443, tcp=True, source=first + 3), stays=False),
        }

    # The ruleset as it was before this leak was fixed: the reply direction kept
    # the host route (target_route) and passed the guard (target_output).
    bit = scope['ROUTE_BIT']
    before_fix = scope['firewall']()
    before_fix = before_fix.replace(
        f'meta mark set meta mark | {bit:#x} return\n',
        f'meta mark set meta mark | {bit:#x} return\n    ct direction reply meta mark set meta mark & {0xffffffff ^ bit:#x} return\n', 1)
    before_fix = before_fix.replace(
        'fib daddr type != local counter drop\n    ip daddr @lan_v4 counter accept',
        'fib daddr type != local counter drop\n    ct direction reply counter accept\n    ip daddr @lan_v4 counter accept', 1)
    assert before_fix.count('ct direction reply') == 4, before_fix   # from_tun, private_dns_access, and the two restored

    fd = os.open('/dev/net/tun', os.O_RDWR)
    try:
        fcntl.ioctl(fd, 0x400454ca, struct.pack('16sH22x', SEED_UPLINK.encode(), 0x1001))   # TUNSETIFF: IFF_TUN | IFF_NO_PI
        run([IP, 'address', 'add', SEED_LOCAL + '/32', 'dev', SEED_UPLINK])
        run([IP, '-6', 'address', 'add', SEED_LOCAL6 + '/128', 'dev', SEED_UPLINK, 'nodad'])
        run([IP, 'link', 'set', SEED_UPLINK, 'up'])
        run([IP, 'route', 'add', SEEDED + '/32', 'dev', SEED_UPLINK])
        run([IP, '-6', 'route', 'add', SEEDED6 + '/128', 'dev', SEED_UPLINK])
        found = outcomes(45000)
        assert not any(found.values()), f'owner packets taken for replies left by the uplink: {found}'
        # Control: restore the reply exception exactly as it was before the fix; the same
        # owner UDP and IPv6 packets now leave by the uplink. This proves the check can fail.
        run([NFT, '-f', '-'], data=f'delete table inet {TABLE}\n' + before_fix)
        leaked = outcomes(45010)
    finally:
        os.close(fd)
    scope['install_firewall']({})
    assert leaked['UDP to port 443'] == 1 and leaked['UDP to port 443 over IPv6'] == 1, \
        f'control did not reproduce the leak with the reply exception restored: {leaked}'
    print('PASS: owner packets that conntrack takes for the reply of a flow somebody else began (DNS, other UDP, '
          'UDP over IPv6, TCP) do not leave by the uplink; with the old reply exception restored the UDP and IPv6 '
          'packets leave by it (control)', flush=True)


def check_unsolicited_tun_packets(scope):
    """What the TUN delivers without answering an owner flow gets no reply from the kernel.

    Such a reply (a RST, an ICMP error quoting the packet) belongs to no socket
    and to no marked flow, so nothing would keep it off the uplink. Here the
    test holds a real TUN of the core's name and writes the packets itself.
    """
    fd = os.open('/dev/net/tun', os.O_RDWR)
    try:
        fcntl.ioctl(fd, 0x400454ca, struct.pack('16sH22x', b'xq-utun', 0x1001))   # TUNSETIFF: IFF_TUN | IFF_NO_PI
        # As the controller leaves the core's TUN: its address, loose reverse path filtering.
        run([IP, 'address', 'add', scope['ADDRESS'], 'dev', 'xq-utun'])
        run([IP, 'link', 'set', 'xq-utun', 'up'])
        Path('/proc/sys/net/ipv4/conf/xq-utun/rp_filter').write_text('2\n')
        unsolicited = [
            # a TCP segment of a connection nobody has: the kernel would answer with a RST
            packet(socket.IPPROTO_TCP, STRANGER, WAN_ADDRESS,
                   struct.pack('>HHIIBBHHH', 443, 40001, 1000, 2000, 5 << 4, 0x10, 65535, 0, 0)),
            # a datagram for a port nobody listens on: the kernel would answer with an ICMP error quoting it
            packet(socket.IPPROTO_UDP, STRANGER, WAN_ADDRESS, struct.pack('>HHHH', 53, 40002, 8 + 11, 0) + b'late answer'),
        ]
        # A RST is let in: the kernel never answers one.
        reset = packet(socket.IPPROTO_TCP, STRANGER, WAN_ADDRESS,
                       struct.pack('>HHIIBBHHH', 443, 40003, 1000, 0, 5 << 4, 0x04, 0, 0, 0))
        dropped, passed = hits('from_tun', 'drop'), hits('from_tun', 'return')
        for item in (*unsolicited, reset):
            os.write(fd, item)
        time.sleep(0.5)
        assert hits('from_tun', 'drop') == dropped + len(unsolicited), 'the packets did not arrive from the TUN'
        assert hits('from_tun', 'return') == passed + 1, 'the RST was not let in'
        assert counted('stranger') == (0,), f'the kernel answered {counted("stranger")[0]} unsolicited TUN packets by the uplink'
        assert STRANGER not in run([CONNTRACK, '-L']), 'a flow that started from the TUN was recorded'
        # The same packets with that one rule taken away, to know the check above can fail.
        run([NFT, 'flush', 'chain', 'inet', TABLE, 'tun_input'])
        for item in unsolicited:
            os.write(fd, item)
        time.sleep(0.5)
        answered = counted('stranger')[0]
        assert answered == len(unsolicited), f'control: expected {len(unsolicited)} kernel replies on the uplink, saw {answered}'
    finally:
        os.close(fd)
    for _ in range(50):
        if subprocess.run([IP, 'link', 'show', 'xq-utun'], capture_output=True).returncode:
            break
        time.sleep(0.1)
    print('PASS: a TCP segment and a datagram arriving from the TUN that answer no owner flow are dropped on '
          'arrival: no RST or ICMP error goes out by the uplink and no backwards flow is recorded '
          f'(control without the rule: the kernel sent {answered} such replies by the uplink); a RST is let in '
          'and answered by nothing', flush=True)


def check_attach_waits_for_the_link(scope):
    """ExecStartPost's own step on a real TUN: the route is asked for once the link is up.

    The core gives its TUN the address before it sets the link up, and the
    kernel refuses a route through a device that is not up. Here the test holds
    the TUN, gives it the address and sets it up half a second after
    attach_routes() has begun to wait.
    """
    config = json.loads((BASE / 'sing-box.template.json').read_text())
    config['outbounds'][0].update(server=scope['HOST'], server_port=scope['PORT'])
    scope['CONFIG'].write_text(json.dumps(config))
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    scope['install_firewall']({'owner': 'xq-user-proxy-v1', 'boot_id': boot, 'uid': scope['UID']})
    scope['install_routes']()
    trusted, outcome, fd = scope['trusted'], [], None

    def attach():
        try:
            scope['attach_routes']()
            outcome.append(None)
        except (RuntimeError, OSError, ValueError) as error:
            outcome.append(str(error))
    try:
        scope['trusted'] = lambda path, directory=False: None    # the test directory is not a root-owned path
        scope['ENABLED'].write_text('on\n')
        fd = os.open('/dev/net/tun', os.O_RDWR)
        fcntl.ioctl(fd, 0x400454ca, struct.pack('16sH22x', b'xq-utun', 0x1001))   # TUNSETIFF: IFF_TUN | IFF_NO_PI
        run([IP, 'address', 'add', scope['ADDRESS'], 'dev', 'xq-utun'])
        refused = subprocess.run(scope['route_command'](scope['TUN_ROUTE'], 'replace'), capture_output=True)
        assert refused.returncode and not scope['has_route'](scope['TUN_ROUTE']), 'a route through the TUN was taken while it is down'
        worker, started = threading.Thread(target=attach, daemon=True), time.monotonic()
        worker.start()
        time.sleep(0.5)
        run([IP, 'link', 'set', 'xq-utun', 'up'])
        worker.join(timeout=15)
        waited = time.monotonic() - started
        assert outcome == [None], f'attach_routes() did not wait for the link: {outcome}'
        assert scope['has_route'](scope['TUN_ROUTE']) and waited >= 0.5, (waited, scope['routes']('-4'))
    finally:
        if fd is not None:
            os.close(fd)
        scope['trusted'] = trusted
        scope['ENABLED'].unlink(missing_ok=True)
    for _ in range(50):                                        # the TUN goes with its file descriptor
        if subprocess.run([IP, 'link', 'show', 'xq-utun'], capture_output=True).returncode:
            break
        time.sleep(0.1)
    else:
        raise AssertionError('the TUN of this check outlived its file descriptor')
    print('PASS: while the TUN has its address but is not up the kernel refuses a route through it; '
          f'attach_routes() waits and gives the route once the link is up ({waited:.2f} s)', flush=True)


def check_shutdown(scope, owner, core):
    """OFF's own steps in OFF's order, and what status would find before and after."""
    cast(scope, owner, core)
    expect(probe(owner, STUB), 'private', 'owner DNS before the shutdown')
    found, unchecked = scope['kernel_leftovers']()
    # The table, two rules and two routes (the TUN route left with its device), and the
    # mapping of the query above, which OFF's conntrack step below must remove.
    fixed = [item for item in found if 'DNS conntrack' not in item]
    assert (len(fixed), len(found) - len(fixed), unchecked) == (5, 1, []), found
    scope['install_firewall']({}, active=False)          # stop translating before the mappings are deleted
    assert 'dnat' not in run([NFT, 'list', 'table', 'inet', TABLE])
    before, mappings = dns_exits(), len(scope['dns_connections']())
    for tcp in (False, True):
        expect(probe(owner, STUB, tcp=tcp), None, 'owner DNS while only the guard is left')
        expect(probe(owner, REMOTE, tcp=tcp), None, 'owner DNS to a public resolver while only the guard is left')
    assert dns_exits() == before, f'with only the guard left, owner DNS left the host: {dns_exits()} after {before}'
    # What lets the mappings be counted: a query that arrives meanwhile does not add one.
    assert len(scope['dns_connections']()) == mappings, 'an owner query left a mapping while only the guard was loaded'
    for _ in range(2):                                   # the second round finds nothing left to do
        scope['delete_dns_connections']()
        scope['remove_routes']()
        if scope['table_exists']():
            run([NFT, 'delete', 'table', 'inet', TABLE])
        assert scope['kernel_leftovers']() == ([], []), scope['kernel_leftovers']()
    expect(probe(owner, STUB), 'stub', 'owner DNS after the cleanup')
    print('PASS: the steps of OFF in order: the guard-only stage blocks owner DNS instead of leaking it and '
          'records no new mapping, then nothing of this feature is left and repeating the cleanup changes nothing',
          flush=True)


def exercise(scope, single):
    me = os.getuid()
    run([IP, 'link', 'set', 'lo', 'up'])
    for name in ('xq-utun', 'test-wan'):
        run([IP, 'link', 'add', name, 'type', 'dummy'])
        run([IP, 'link', 'set', name, 'up'])
    run([IP, 'address', 'add', '198.18.0.2/24', 'dev', 'test-wan'])
    run([IP, 'route', 'add', 'default', 'dev', 'test-wan'])
    run([IP, '-6', 'address', 'add', '2001:db8:1::2/64', 'dev', 'test-wan', 'nodad'])
    run([IP, '-6', 'route', 'add', 'default', 'dev', 'test-wan'])
    for address in (LAN, PUBLIC):
        run([IP, 'address', 'add', address + '/32', 'dev', 'lo'])
    for address in (ULA, V6_PUBLIC):
        run([IP, '-6', 'address', 'add', address + '/128', 'dev', 'lo', 'nodad'])

    check_route_cleanup(scope)
    run([NFT, '-f', '-'], data=EXITS)
    port = scope['DNS_PORT']
    scope['install_routes']()
    run(scope['route_command'](scope['TUN_ROUTE'], 'replace'))
    echo('private', me, '127.0.0.1', port, 'private')
    echo('ordinary', me, '127.0.0.1', 18080, 'ordinary')
    for address, label in RESOLVERS.items():
        if label:
            echo(label, me, address, 53, label)

    if single:
        # One identity: it plays each role in turn.
        owner, bystanders, squatter = me, [(me, 'a non-owner identity')], me
        restricted = [SETPRIV, '--bounding-set=-net_bind_service', '--inh-caps=-net_bind_service',
                      '--ambient-caps=-net_bind_service', '--']
        who = 'a process without CAP_NET_BIND_SERVICE'
    else:
        owner, bystanders, squatter = OWNER, [(0, 'root'), (OTHER, 'another UID')], OTHER
        restricted, who = [], 'another UID'

    def unprivileged(number):
        return json.loads(run([*restricted, sys.executable, '-I', '-c', BIND,
                               str(me if single else OTHER), str(number)]))

    cast(scope, owner, me)
    print('PASS: active and inactive guard pass nft --check and load through install_firewall()', flush=True)
    check_owner(scope, owner)
    if not single:
        for uid, name in bystanders:
            check_bystander(scope, uid, name)
        check_cross_identity(scope, owner, OTHER)
    check_dns_cleanup(scope, owner)
    check_listener_restart(scope, owner, me, unprivileged, who)
    check_flushed_ruleset(scope, owner)

    # In the single-identity run the listener's own identity is cast out of the core role.
    cast(scope, owner, NOBODY if single else me)
    check_forged_reply(scope, owner, squatter, 'a sender that is not the core' if single else 'another UID')
    cast(scope, owner, me)
    echo('private', me, '127.0.0.1', port, 'private')
    for tcp in (False, True):
        expect(probe(owner, STUB, tcp=tcp), 'private', 'owner DNS once the core listener is back')
    print('PASS: the legitimate core listener answers again after the squatter', flush=True)

    if single:
        cast(scope, NOBODY, me)
        for uid, name in bystanders:
            check_bystander(scope, uid, name)
    check_tun_acl()
    check_core_loss(scope, owner, me, bystanders[0][0])
    check_preseeded_flows(scope, owner, me)
    check_unsolicited_tun_packets(scope)
    check_attach_waits_for_the_link(scope)
    check_shutdown(scope, owner, me)
    if single:
        print('SKIPPED (needs a second UID at the same time; run as root): borrowing an owner conntrack tuple, '
              'source-port reuse between UIDs, and binding/answering as a real other UID', flush=True)
    print('ALL CHECKS PASSED: ' + ('single identity (rootless user namespace)' if single else
                                   f'owner UID {OWNER}, other UID {OTHER}, root'), flush=True)


def main():
    refuse_unsafe_namespace()
    single = not can_switch_to(OWNER, OTHER)
    if single and not os.access(SETPRIV, os.X_OK):
        raise SystemExit('The single-identity run needs ' + SETPRIV)
    print('MODE: ' + ('single identity; roles are cast through the UID constants of the rules' if single
                      else 'three identities'), flush=True)
    ctl = runpy.run_path(str(BASE / 'xq-user-proxyctl'))
    with tempfile.TemporaryDirectory(prefix='xq-user-tun-netns-') as directory:
        try:
            exercise(sandbox(ctl, Path(directory).resolve()), single)
        finally:
            for name in list(LISTENERS):
                LISTENERS.pop(name).kill()


if __name__ == '__main__':
    main()
