#!/usr/bin/python3 -I
"""Exercise generated ACLs in a fresh, disposable network namespace only.

Run: sudo unshare --net python3 -I tests/netns-check.py
No service/controller lifecycle calls, host routes or host DNS changes.
"""
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import threading

BASE = Path(__file__).resolve().parents[1]
OWNER = 23456  # Deliberately unrelated to the development server's account.
OTHER = 23457
IP = '/usr/sbin/ip'
NFT = '/usr/sbin/nft'


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True,
                          timeout=15, **kwargs).stdout


def start_echo(port, response):
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(('127.0.0.1', port))
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind(('127.0.0.1', port))
    tcp.listen()

    def udp_loop():
        while True:
            _, peer = udp.recvfrom(1024)
            udp.sendto(response, peer)

    def tcp_loop():
        while True:
            conn, _ = tcp.accept()
            with conn:
                conn.settimeout(2)
                conn.recv(1024)
                conn.sendall(response)

    for worker in (udp_loop, tcp_loop):
        threading.Thread(target=worker, daemon=True).start()


PROBE = r'''
import json,os,socket,sys
uid,port,tcp,source,mark=map(int,sys.argv[1:])
os.setgroups([]);os.setgid(uid);os.setuid(uid)
with socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
    s.settimeout(0.5)
    s.bind(('127.0.0.1',source))
    if mark: s.setsockopt(socket.SOL_SOCKET,socket.SO_MARK,mark)
    port_used=s.getsockname()[1]
    try:
        s.connect(('127.0.0.1',port));s.sendall(b'query');reply=s.recv(1024).decode()
    except OSError: reply=None
print(json.dumps({'reply':reply,'source':port_used}))
'''


def probe(uid, port, tcp=False, source=0):
    return json.loads(run(['/usr/bin/python3', '-I', '-c', PROBE,
                           str(uid), str(port), str(int(tcp)), str(source), '0']))


def hits(chain, verdict):
    data = json.loads(run([NFT, '-j', 'list', 'chain', 'inet', 'xq_user_proxy', chain]))
    return sum(expr['counter']['packets']
               for item in data['nftables']
               if any(verdict in e for e in item.get('rule', {}).get('expr', []))
               for expr in item.get('rule', {}).get('expr', []) if 'counter' in expr)


def main():
    if os.geteuid() != 0 or os.stat('/proc/self/ns/net') == os.stat('/proc/1/ns/net'):
        raise SystemExit('Refusing host network: run sudo unshare --net python3 -I tests/netns-check.py')
    interfaces = json.loads(run([IP, '-j', 'link', 'show']))
    if [item['ifname'] for item in interfaces] != ['lo']:
        raise SystemExit('Refusing a namespace that is not fresh (expected only lo)')
    ctl = runpy.run_path(str(BASE / 'xq-user-proxyctl'))
    scope = ctl['firewall'].__globals__
    scope.update(UID=OWNER, GID=OWNER, USER='test-owner', HOST='198.51.100.10', PORT=1080)
    run([IP, 'link', 'set', 'lo', 'up'])
    for name in ('xq-utun', 'test-wan'):
        run([IP, 'link', 'add', name, 'type', 'dummy'])
        run([IP, 'link', 'set', name, 'up'])
    run([IP, 'address', 'add', '198.18.0.2/24', 'dev', 'test-wan'])
    run([IP, 'route', 'add', 'default', 'dev', 'test-wan'])
    run([IP, 'route', 'add', 'blackhole', 'default', 'metric', '32760', 'table', '20261'])
    run([IP, 'route', 'add', 'default', 'dev', 'xq-utun', 'metric', '10', 'table', '20261'])
    run([IP, 'rule', 'add', 'pref', '18410', 'fwmark', '0x40000000/0x40000000', 'table', '20261'])
    for active in (True, False):
        run([NFT, '--check', '-f', '-'], input=ctl['firewall'](active))
    run([NFT, '-f', '-'], input=ctl['firewall']())
    for port, reply in ((53, b'original'), (1053, b'private'), (18080, b'ordinary')):
        start_echo(port, reply)

    for uid in (OWNER, 0, OTHER):
        for tcp in (False, True):
            assert probe(uid, 18080, tcp)['reply'] == 'ordinary'
            assert probe(uid, 53, tcp)['reply'] == ('private' if uid == OWNER else 'original')
            assert probe(uid, 1053, tcp)['reply'] == ('private' if uid == OWNER else None)
    assert hits('private_dns_access', 'reject') >= 4
    print('PASS: arbitrary owner UID gets proxied DNS; root/other UID retain original DNS and ordinary TCP/UDP, private DNS denied', flush=True)

    first = probe(OWNER, 1053)
    assert first['reply'] == 'private'
    assert probe(OTHER, 1053, source=first['source'])['reply'] is None
    print('PASS: another UID cannot borrow an owner conntrack tuple', flush=True)

    # All users share one conntrack table, and a just-closed UDP source port
    # can be reused by another UID within the conntrack timeout. In neither
    # order may one UID inherit the other's DNS translation.
    owner_first = probe(OWNER, 53)
    assert owner_first['reply'] == 'private'
    assert probe(OTHER, 53, source=owner_first['source'])['reply'] == 'original'
    other_first = probe(OTHER, 53)
    assert other_first['reply'] == 'original'
    assert probe(OWNER, 53, source=other_first['source'])['reply'] == 'private'
    print('PASS: a reused UDP source port never carries DNS translation between UIDs', flush=True)

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
    print('PASS: marked root traffic denied at the TUN ACL', flush=True)

    # Simulate core/TUN loss: only the test namespace changes, guard stays.
    run([IP, 'link', 'delete', 'xq-utun'])
    result = subprocess.run([IP, '-j', 'route', 'get', '203.0.113.10', 'mark', '0x40000000'],
                            text=True, capture_output=True)
    # Linux blackhole routes may return EINVAL ("Invalid argument"), whereas
    # unreachable routes return ENETUNREACH. Verify the route, not error prose.
    assert result.returncode != 0, result.stdout
    remaining = json.loads(run([IP, '-j', 'route', 'show', 'table', '20261']))
    assert any(r.get('type') == 'blackhole' and r.get('dst') == 'default' for r in remaining)
    assert not any(r.get('dev') == 'xq-utun' for r in remaining)
    root_route = json.loads(run([IP, '-j', 'route', 'get', '203.0.113.10']))
    assert root_route[0]['dev'] == 'test-wan'
    assert probe(0, 53)['reply'] == 'original'
    print('PASS: core loss leaves owner blackhole while unmarked root routing/DNS remain available', flush=True)


if __name__ == '__main__':
    main()
