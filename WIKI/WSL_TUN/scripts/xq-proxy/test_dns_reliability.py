#!/usr/bin/env python3
"""Offline controller regressions: temporary files, fake kernel, no network/root.

The fake kernel answers only the exact commands the controller is expected to
issue and runs no process. Sockets, subprocesses and syslog are replaced too, so
no test reaches the network, the journal or the host configuration.
"""
import base64
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import socket
import stat
import struct
import sys
import syslog
import tempfile
import time
from types import SimpleNamespace
import unittest

CONTROLLER = Path(__file__).with_name('xq-proxyctl')
if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
    CONTROLLER = Path(sys.argv.pop(1))

DNS_MARK = 0x02000000
DELETE_TABLE = 'delete table inet xq_proxy\n'
CONNTRACK_DELETE = ('-D', '-f', 'ipv4', '--zone', '20262', '--mark', '0x2000000/0x2000000')
ZONE_ENTRY = ('udp      17 25 src=127.0.0.1 dst=10.255.255.254 sport=40000 dport=53 src=127.0.0.1 '
              'dst=127.0.0.1 sport=1053 dport=40000 mark={mark} zone=20262 use=1')
PROBE_OK = (True, '成功（默认 DNS 10.255.255.254，example.com A）')
DNS_TAKEOVER = 'DNS 接管：应用 IPv4 TCP/UDP 53 → 127.0.0.1:1053 → 代理 DoH；WSL 继续管理 resolver'
CHECK_OK = '配置检查：DNS 入口、接管规则、路由和运行版本正常'
NOT_PROBED = '默认 DNS 连通性：未探测（先修复配置异常）'
NEED_CONNTRACK = '需要安装 conntrack，才能精确清理本功能的 DNS 映射；未改变网络'


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def marked(entry):
    mark = next((part[5:] for part in entry.split() if part.startswith('mark=')), '0')
    return bool(int(mark, 0) & DNS_MARK)


def chains(text):
    """Map each chain of an nft guard text to its stripped, non-empty lines."""
    result, current = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('chain ') and line.endswith('{'):
            current = result.setdefault(line.split()[1], [])
        elif line == '}':
            current = None
        elif line and current is not None:
            current.append(line)
    return result


class NoHostAccess:
    """Replaces a host-facing module: any use fails the test instead of escaping."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attribute):
        raise AssertionError(f'offline test attempted {self._name}.{attribute}')


class FakeSyslog:
    """Records the controller's journal events instead of writing to /dev/log."""
    LOG_INFO, LOG_WARNING, LOG_ERR = syslog.LOG_INFO, syslog.LOG_WARNING, syslog.LOG_ERR
    LOG_PID, LOG_DAEMON = syslog.LOG_PID, syslog.LOG_DAEMON

    def __init__(self):
        self.idents, self.records = set(), []

    def openlog(self, ident, logoption, facility):
        self.idents.add((ident, logoption, facility))

    def syslog(self, priority, message):
        self.records.append((priority, message))


class FakeResolverNetwork:
    """socket stand-in for dns_probe: per-server answers, every datagram recorded."""
    AF_INET, SOCK_DGRAM = socket.AF_INET, socket.SOCK_DGRAM

    def __init__(self, answers):
        self.answers, self.sent, self.timeouts = answers, [], []

    def socket(self, family, kind):
        assert (family, kind) == (socket.AF_INET, socket.SOCK_DGRAM)
        return FakeDatagram(self)


class FakeDatagram:
    def __init__(self, network):
        self.network, self.server = network, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def settimeout(self, value):
        self.network.timeouts.append(value)

    def connect(self, address):
        self.server = address

    def send(self, packet):
        self.network.sent.append((self.server, packet))
        return len(packet)

    def recv(self, size):
        answer = self.network.answers[self.server[0]]
        if isinstance(answer, BaseException):
            raise answer
        return answer(self.network.sent[-1][1])


def dns_answer(flags=0x8180, questions=1, answers=1, same_id=True):
    """Build a reply to the probe's query: header, echoed question, one A record."""
    def build(query):
        ident = query[:2] if same_id else bytes(b ^ 0xff for b in query[:2])
        return (ident + struct.pack('!HHHHH', flags, questions, answers, 0, 0) + query[12:]
                + b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\x5d\xb8\xd7\x0e')
    return build


class FakeKernel:
    """Answers only the exact commands the controller is expected to issue."""

    def __init__(self, conntrack, core):
        self.conntrack, self.core_path = conntrack, core
        self.calls = []
        self.loads = []                 # rulesets applied with nft -f
        self.core = True
        self.guard = True
        self.link_up = True
        self.table = ''                 # nft --stateless listing of inet xq_proxy
        self.foreign_rules = []         # other tables' rules in nft -j list ruleset
        self.zone_entries = []          # conntrack entries in zone 20262
        self.zone_list_error = None
        self.delete_error = None        # (returncode, stderr) for conntrack -D
        self.listening = {'-t': True, '-u': True}
        self.dns_bind = '127.0.0.1:1053'
        self.foreign_listeners = []     # ss -p lines of other processes on port 1053
        self.main_pid = '4242'
        self.on_restart = None          # systemd ExecStartPost=+xq-proxyctl attach
        self.on_stop = None
        self.rules4 = [
            {'priority': 0, 'table': 'local'},
            {'priority': 18400, 'iif': 'xq-tun', 'table': 'main'},
            {'priority': 18401, 'uid_start': 999, 'uid_end': 999, 'table': 'main'},
            {'priority': 18402, 'table': 20260},
        ]
        self.rules6 = [{'priority': 0, 'table': 'local'},
                       {'priority': 18402, 'table': 20260}]
        self.routes4 = [{'dst': 'default', 'dev': 'xq-tun', 'flags': []}]
        self.routes6 = [{'dst': 'default', 'type': 'unreachable', 'dev': 'lo'}]

    def remove_routes(self):
        self.calls.append(('remove-owned-routes',))
        self.rules4 = [r for r in self.rules4 if r.get('priority') not in (18400,18401,18402)]
        self.rules6 = [r for r in self.rules6 if r.get('priority') not in (18400,18401,18402)]
        self.routes4 = []
        self.routes6 = []

    def clear(self):
        self.core = self.guard = self.link_up = False
        self.table = ''
        self.remove_routes()
        self.calls.clear()
        self.loads.clear()

    def ruleset(self):
        items = [{'metainfo': {'json_schema_version': 1}}, *self.foreign_rules]
        if self.guard:
            # The controller's own table legitimately sets ct zone and ct mark.
            items += [{'table': {'family': 'inet', 'name': 'xq_proxy', 'handle': 9}},
                      {'rule': {'family': 'inet', 'table': 'xq_proxy', 'chain': 'dns_zone_output',
                                'expr': [{'mangle': {'key': {'ct': {'key': 'zone'}}, 'value': 20262}}]}}]
        return json.dumps({'nftables': items})

    def listeners(self, transport):
        if not (self.core and self.listening[transport]):
            return []
        state = 'LISTEN 0      4096  ' if transport == '-t' else 'UNCONN 0      0     '
        return [f'{state} {self.dns_bind} 0.0.0.0:*']

    def run(self, args, *, check=True, data=None):
        a = tuple(args)
        self.calls.append(a)
        code, stdout, stderr = 0, '', ''
        if a == ('systemctl','is-active','--quiet','xq-proxy.service'):
            code = 0 if self.core else 3
        elif a == ('systemctl','stop','xq-proxy.service'):
            if self.on_stop:
                self.on_stop()
            self.core = self.link_up = False
        elif a == ('systemctl','stop','xq-proxy-boot.service'):
            pass
        elif a == ('systemctl','restart','xq-proxy.service'):
            self.core = self.link_up = True
            if self.on_restart:
                try:
                    self.on_restart()
                except RuntimeError:
                    # Real systemd reports only a generic job failure for a failed ExecStartPost;
                    # attach()'s own reason reaches the journal, not systemctl's stderr.
                    self.core = self.link_up = False
                    code, stderr = 1, ('Job for xq-proxy.service failed because the control process '
                                       'exited with error code.\nSee "systemctl status xq-proxy.service" '
                                       'and "journalctl -xeu xq-proxy.service" for details.')
        elif a == ('systemctl','show','--property=MainPID','--value','xq-proxy.service'):
            stdout = (self.main_pid if self.core else '0') + '\n'
        elif a == ('nft','list','table','inet','xq_proxy'):
            code = 0 if self.guard else 1
        elif a == ('nft','--stateless','list','table','inet','xq_proxy'):
            code, stdout = (0, self.table) if self.guard else (1, '')
        elif a in (('nft','--check','-f','-'), ('nft','-f','-')):
            text = data or ''
            body = text[len(DELETE_TABLE):] if text.startswith(DELETE_TABLE) else text
            if text.startswith(DELETE_TABLE) and not self.guard:
                code, stderr = 1, 'Error: No such file or directory'
            elif not body.startswith('table inet xq_proxy {') or body.count('{') != body.count('}'):
                code, stderr = 1, 'Error: syntax error'
            elif a[1] == '-f':
                self.loads.append(body)
                self.guard, self.table = True, body
        elif a == ('nft','delete','table','inet','xq_proxy'):
            if not self.guard:
                code, stderr = 1, 'Error: No such file or directory'
            self.guard, self.table = False, ''
        elif a == ('nft','-j','list','ruleset'):
            stdout = self.ruleset()
        elif a == (self.conntrack,'-L','-f','ipv4','--zone','20262'):
            if self.zone_list_error:
                code, stderr = 1, self.zone_list_error
            else:
                stdout = ''.join(entry+'\n' for entry in self.zone_entries)
                stderr = f'conntrack v1.4.8 (conntrack-tools): {len(self.zone_entries)} flow entries have been shown.\n'
        elif a == (self.conntrack, *CONNTRACK_DELETE):
            if self.delete_error:
                code, stderr = self.delete_error
            else:
                owned = [entry for entry in self.zone_entries if marked(entry)]
                self.zone_entries = [entry for entry in self.zone_entries if not marked(entry)]
                # conntrack-tools exits 1 when nothing matched.
                code = 0 if owned else 1
                stderr = f'conntrack v1.4.8 (conntrack-tools): {len(owned)} flow entries have been deleted.\n'
        elif a in (('ss','-H','-l','-n','-t','sport','=',':1053'),
                   ('ss','-H','-l','-n','-u','sport','=',':1053')):
            stdout = ''.join(line+'\n' for line in self.listeners(a[4]))
        elif a == ('ss','-H','-l','-n','-t','-u','-p','sport','=',':1053'):
            own = [f'{netid} {line} users:(("sing-box",pid={self.main_pid},fd=9))'
                   for netid, transport in (('udp','-u'), ('tcp','-t')) for line in self.listeners(transport)]
            stdout = ''.join(line+'\n' for line in own + self.foreign_listeners)
        elif a == ('ip','-j','-4','rule','show'):
            stdout = json.dumps(self.rules4)
        elif a == ('ip','-j','-6','rule','show'):
            stdout = json.dumps(self.rules6)
        elif a == ('ip','-j','-4','route','show','table','20260'):
            stdout = json.dumps(self.routes4)
        elif a == ('ip','-j','-6','route','show','table','20260'):
            stdout = json.dumps(self.routes6)
        elif a in (('ip','-4','route','show','table','20260'),
                   ('ip','-6','route','show','table','20260')):
            routes = self.routes4 if a[1] == '-4' else self.routes6
            stdout = 'default dev xq-tun' if routes else ''
        elif a == ('ip','-j','-4','route','show','table','main'):
            stdout = json.dumps([{'dst':'default','gateway':'172.21.32.1','dev':'eth0'},
                                 {'dst':'172.21.32.0/20','dev':'eth0'}])
        elif a == ('ip','-j','link','show','xq-tun'):
            stdout = json.dumps([{'flags':['UP']}]) if self.link_up else '[]'
        elif a == ('ip','link','show','xq-tun'):
            code = 0 if self.link_up else 1
        elif a == ('ip','-j','-4','addr','show','dev','eth0'):
            stdout = json.dumps([{'addr_info':[{'family':'inet','local':'172.21.38.15'}]}])
        elif a == ('ip','-4','route','replace','default','dev','xq-tun','table','20260'):
            self.routes4 = [{'dst':'default','dev':'xq-tun','flags':[]}]
        elif a == ('ip','-6','route','replace','unreachable','default','table','20260'):
            self.routes6 = [{'dst':'default','type':'unreachable','dev':'lo'}]
        elif a == ('ip','-4','rule','add','pref','18400','iif','xq-tun','lookup','main'):
            self.rules4.append({'priority':18400,'iif':'xq-tun','table':'main'})
        elif a == ('ip','-4','rule','add','pref','18401','uidrange','999-999','lookup','main'):
            self.rules4.append({'priority':18401,'uid_start':999,'uid_end':999,'table':'main'})
        elif a in (('ip','-4','rule','add','pref','18402','lookup','20260'),
                   ('ip','-6','rule','add','pref','18402','lookup','20260')):
            (self.rules4 if a[1] == '-4' else self.rules6).append({'priority':18402,'table':20260})
        elif a[:3] == (self.core_path,'check','-c'):
            pass
        else:
            raise AssertionError('Unexpected simulated command; no process was run: '+repr(a))
        if check and code:
            raise RuntimeError(' '.join(a) + ': ' + stderr.strip())
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xq-dns-offline-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mod = runpy.run_path(str(CONTROLLER), run_name='offline_controller_test')
        self.g = mod['on'].__globals__
        # Unpatched functions: run directly or restored by reset().
        self.original = {name: mod[name] for name in ('attach', 'dns_probe', 'status')}
        self.state_dir = self.root/'state'
        self.state_dir.mkdir()
        self.resolv = self.root/'etc'/'resolv.conf'
        self.resolv.parent.mkdir()
        self.wsl = self.root/'wsl'/'resolv.conf'
        self.wsl.parent.mkdir()
        self.runtime = self.root/'runtime-enabled'
        self.enabled = self.state_dir/'enabled'
        self.statefile = self.state_dir/'state.json'
        self.config = self.root/'config'/'sing-box.json'
        self.config.parent.mkdir()
        self.core_binary = self.root/'bin'/'sing-box'
        self.core_binary.parent.mkdir()
        self.conntrack = self.root/'bin'/'conntrack'
        self.good = {'kind':'symlink','target':str(self.wsl)}
        self.managed = (self.g['DNS_HEADER']+'\nnameserver 172.30.255.2\noptions timeout:2 attempts:2\n').encode()
        self.reset()

    def reset(self):
        """Build a healthy ON installation as a completed ON and attach leave it."""
        for path in (self.resolv, self.enabled, self.runtime, self.statefile, self.config):
            if os.path.lexists(path):
                path.unlink()
        self.wsl.write_text('nameserver 10.255.255.254\n')
        # WSL owns resolv.conf: a link to its generated file (DNS tunneling address on lo).
        self.resolv.symlink_to(self.wsl)
        self.core_binary.write_bytes(b'simulated sing-box 1.14.4\n')
        # Present and executable for the controller's checks; the fake kernel never runs it.
        self.conntrack.write_text('#!/bin/sh\nexit 99\n')
        self.conntrack.chmod(0o755)
        self.kernel = FakeKernel(str(self.conntrack), str(self.core_binary))
        self.syslog = FakeSyslog()
        self.probe_result, self.probes, self.sleeps = PROBE_OK, [], []
        # Only the hardcoded runtime marker is remapped; all other filesystem work
        # already uses the temporary paths injected below.
        def mapped_path(value):
            p = Path(value)
            return self.runtime if str(p) == '/run/xq-proxy-enabled' else p
        self.g.update(STATE=self.state_dir, ENABLED=self.enabled, STATEFILE=self.statefile,
                      RESOLV=self.resolv, WSL_RESOLV=self.wsl, CONF=self.config,
                      CORE=self.core_binary, CONNTRACK=str(self.conntrack),
                      Path=mapped_path, run=self.kernel.run,
                      gateway=lambda: ('172.21.32.1','eth0'),
                      pwd=SimpleNamespace(getpwnam=lambda _:SimpleNamespace(pw_uid=999)),
                      preflight=lambda _:None, remove_routes=self.kernel.remove_routes,
                      status=self.original['status'], dns_probe=self.fake_probe, syslog=self.syslog,
                      time=SimpleNamespace(time=time.time, monotonic=time.monotonic, sleep=self.sleeps.append),
                      socket=NoHostAccess('socket'), subprocess=NoHostAccess('subprocess'))
        # systemd runs ExecStartPost=+/usr/local/sbin/xq-proxyctl attach after each start.
        self.kernel.on_restart = self.original['attach']
        self.state = {'phase':'active','host':'172.21.32.1','interface':'eth0',
                      'uid':999,'port':4066,'resolver_before':self.good,'activated_at':1.0}
        self.kernel.table = self.g['guard_text'](self.state)
        self.config.write_text(json.dumps(self.g['config'](self.state), indent=2) + '\n')
        self.state.update(guard_digest=sha256(self.kernel.table), dns_active=True,
                          dns_zone=20262, dns_mark=DNS_MARK,
                          running_config_digest=sha256(self.config.read_bytes()),
                          running_core_digest=sha256(self.core_binary.read_bytes()))
        self.enabled.write_text('on\n')
        self.runtime.write_text('on\n')
        self.save(self.state)

    def save(self, value):
        self.statefile.write_text(json.dumps(value))

    def load_state(self):
        return json.loads(self.statefile.read_text())

    def patch_state(self, **values):
        self.state.update(values)
        self.save(self.state)

    def set_resolver(self, data, mode=0o644):
        """Replace resolv.conf with a regular file, as WSL or a user may do."""
        if os.path.lexists(self.resolv):
            self.resolv.unlink()
        self.resolv.write_bytes(data)
        self.resolv.chmod(mode)

    def resolver_identity(self):
        info = os.lstat(self.resolv)
        content = os.readlink(self.resolv) if stat.S_ISLNK(info.st_mode) else self.resolv.read_bytes()
        return info.st_ino, info.st_mtime_ns, info.st_mode, content, self.wsl.read_bytes()

    def fake_probe(self, timeout=4):
        self.probes.append(timeout)
        return self.probe_result

    def conntrack_calls(self):
        return [call for call in self.kernel.calls if call[:1] == (str(self.conntrack),)]

    def file_snapshot(self, data=b'nameserver 9.9.9.9\n', mode=0o640):
        return {'kind':'file','mode':mode,'data':base64.b64encode(data).decode()}

    def capture(self, name, *args, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = self.g[name](*args, **kwargs)
        return result, out.getvalue()

    def make_off(self):
        self.enabled.unlink(missing_ok=True)
        self.runtime.unlink(missing_ok=True)
        self.kernel.clear()
        self.state.update(phase='off', dns_active=False)
        self.save(self.state)

    def world(self):
        return (self.resolver_identity(), self.statefile.read_bytes(), self.enabled.exists(),
                self.runtime.exists(), self.kernel.guard, self.kernel.table, self.kernel.core,
                copy.deepcopy(self.kernel.rules4), copy.deepcopy(self.kernel.rules6))

    def assert_on_refused(self, message):
        """ON must fail with this message before changing anything."""
        before, loads, events = self.world(), len(self.kernel.loads), len(self.syslog.records)
        with self.assertRaisesRegex(RuntimeError, re.escape(message)):
            self.capture('on')
        self.assertEqual(self.world(), before)
        self.assertEqual(len(self.kernel.loads), loads)
        self.assertEqual(len(self.syslog.records), events)
        self.assertFalse([call for call in self.kernel.calls
                          if call[:2] in (('systemctl','restart'), ('systemctl','stop'))])

    def real_probe(self, resolver, answers, timeout=4):
        self.set_resolver(resolver)
        network = FakeResolverNetwork(answers)
        self.g['socket'] = network
        return self.original['dns_probe'](timeout=timeout), network

    # Resolver snapshot, restore and recovery: unchanged by the DNS redesign.

    def test_regular_snapshot_roundtrip_preserves_bytes_and_mode(self):
        snapshot = self.file_snapshot(b'# original\nsearch example.test\nnameserver 9.9.9.9\n')
        self.assertTrue(self.g['safe_snapshot'](snapshot))
        self.g['restore_resolver'](snapshot)
        self.assertEqual(self.resolv.read_bytes(),base64.b64decode(snapshot['data']))
        self.assertEqual(stat.S_IMODE(self.resolv.stat().st_mode),0o640)

    def test_relative_symlink_roundtrip_preserves_literal(self):
        target = self.resolv.parent/'dns'/'original'
        target.parent.mkdir()
        target.write_text('nameserver 9.9.9.9\n')
        snapshot = {'kind':'symlink','target':'dns/original'}
        self.assertTrue(self.g['safe_snapshot'](snapshot))
        self.g['restore_resolver'](snapshot)
        self.assertEqual(os.readlink(self.resolv),'dns/original')
        self.assertEqual(self.resolv.read_text(),target.read_text())

    def test_self_and_indirect_self_links_rejected(self):
        self.assertFalse(self.g['safe_snapshot']({'kind':'symlink','target':'resolv.conf'}))
        alias = self.resolv.parent/'alias'
        alias.symlink_to('resolv.conf')
        self.assertFalse(self.g['safe_snapshot']({'kind':'symlink','target':'alias'}))
        parent_alias = self.root/'etc-alias'
        parent_alias.symlink_to(self.resolv.parent)
        self.assertFalse(self.g['safe_snapshot']({'kind':'symlink','target':str(parent_alias/'resolv.conf')}))

    def test_loop_dangling_and_managed_symlink_targets_rejected(self):
        first, second = self.resolv.parent/'first', self.resolv.parent/'second'
        first.symlink_to('second'); second.symlink_to('first')
        for target in ('first','does-not-exist'):
            with self.subTest(target=target):
                self.assertFalse(self.g['safe_snapshot']({'kind':'symlink','target':target}))
        poisoned = self.resolv.parent/'poisoned'
        poisoned.write_bytes(self.managed)
        self.assertFalse(self.g['safe_snapshot']({'kind':'symlink','target':'poisoned'}))

    def test_managed_detection_is_exact_for_nameserver(self):
        self.assertTrue(self.g['managed_dns'](b'nameserver 172.30.255.2 # old TUN\n'))
        self.assertTrue(self.g['managed_dns']((self.g['DNS_HEADER']+'\nnameserver 9.9.9.9\n').encode()))
        self.assertFalse(self.g['managed_dns'](b'nameserver 172.30.255.20\n'))
        self.assertFalse(self.g['managed_dns'](b'# nameserver 172.30.255.2\nnameserver 9.9.9.9\n'))
        self.assertFalse(self.g['safe_snapshot'](self.file_snapshot(self.managed)))

    def test_absent_original_restores_absence(self):
        snapshot = {'kind':'absent'}
        self.assertTrue(self.g['safe_snapshot'](snapshot))
        self.g['restore_resolver'](snapshot)
        self.assertFalse(os.path.lexists(self.resolv))

    def test_malformed_snapshot_rejected(self):
        for value in (None,{}, {'kind':'unknown'}, {'kind':'file','data':'%%%','mode':0o644},
                      {'kind':'file','data':'','mode':-1}, {'kind':'symlink','target':''}):
            with self.subTest(value=value):
                self.assertFalse(self.g['safe_snapshot'](value))

    def test_recovery_prefers_saved_baseline(self):
        snapshot = self.file_snapshot()
        self.assertEqual(self.g['recovery_snapshot']({'resolver_before':snapshot}),snapshot)

    def test_recovery_uses_verified_wsl_fallback(self):
        result = self.g['recovery_snapshot']({'resolver_before':self.file_snapshot(self.managed)})
        self.assertEqual(result,self.good)

    def test_invalid_wsl_fallback_raises_without_guessing(self):
        for data in (self.managed,b'nameserver not-an-ip\n',b'# no DNS servers\n'):
            with self.subTest(data=data):
                self.wsl.write_bytes(data)
                with self.assertRaises(RuntimeError):
                    self.g['recovery_snapshot']({'resolver_before':self.file_snapshot(self.managed)})

    # Guard: DNS interception rules.

    def test_guard_intercepts_application_dns_before_conntrack(self):
        rules = chains(self.g['guard_text'](self.state))
        self.assertEqual(list(rules), ['dns_zone_output', 'dns_nat_output', 'output', 'forward'])
        zone = rules['dns_zone_output']
        self.assertEqual(zone[0], 'type filter hook output priority raw; policy accept;')
        # Any IPv4 DNS server except from the core, direct use of the local entry, and its replies.
        for rule in ('meta skuid != 999 meta nfproto ipv4 meta l4proto { tcp, udp } th dport 53 ct zone set 20262',
                     'meta skuid != 999 ip daddr 127.0.0.1 meta l4proto { tcp, udp } th dport 1053 ct zone set 20262',
                     'ip saddr 127.0.0.1 meta l4proto { tcp, udp } th sport 1053 ct zone set 20262',
                     'ip saddr 127.0.0.1 icmp type destination-unreachable @th,240,16 1053 ct zone set 20262'):
            self.assertIn(rule, zone)
        self.assertFalse([rule for rule in zone if 'reject' in rule])
        nat = rules['dns_nat_output']
        self.assertEqual(nat[0], 'type nat hook output priority -100; policy accept;')
        dnat = ('meta nfproto ipv4 meta l4proto { tcp, udp } th dport 53 '
                'ct mark set ct mark | 0x2000000 dnat ip to 127.0.0.1:1053')
        self.assertEqual(nat[-1], dnat)
        self.assertIn('ip daddr 127.0.0.1 meta l4proto { tcp, udp } th dport 1053 '
                      'ct mark set ct mark | 0x2000000 return', nat)
        # Replies, the core UID and flows outside the owned zone are never translated.
        for rule in ('ct direction reply return', 'meta skuid 999 return', 'ct zone != 20262 return'):
            self.assertLess(nat.index(rule), nat.index(dnat))
        output = rules['output']
        self.assertEqual(output[0], 'type filter hook output priority -10; policy drop;')
        # Translated replies pass first, even to client port 53; untranslated DNS
        # (core UID, IPv6) is still rejected before loopback is accepted.
        self.assertEqual(output[1:4], [
            'oifname "lo" ip saddr 127.0.0.1 meta l4proto { tcp, udp } th sport 1053 ct zone 20262 '
            'ct mark & 0x2000000 != 0 ct direction reply counter accept',
            'meta l4proto { tcp, udp } th dport 53 oifname != "xq-tun" counter reject with icmpx type admin-prohibited',
            'oifname "lo" counter accept'])
        self.assertIn('meta skuid 999 ip daddr 172.21.32.1 tcp dport 4066 counter accept', output)
        self.assertEqual(output[-1], 'counter reject with icmpx type admin-prohibited')

    def test_stopping_guard_rejects_new_dns_without_translation(self):
        active = chains(self.g['guard_text'](self.state))
        text = self.g['guard_text'](self.state, dns_active=False)
        stopping = chains(text)
        self.assertNotIn('dns_nat_output', stopping)
        self.assertNotIn('dnat', text)
        zone = stopping['dns_zone_output']
        # New DNS is refused before conntrack; existing mappings stay classified for removal.
        self.assertEqual(zone[1:3], [
            'meta skuid != 999 meta nfproto ipv4 meta l4proto { tcp, udp } th dport 53 '
            'counter reject with icmpx type admin-prohibited',
            'meta skuid != 999 ip daddr 127.0.0.1 meta l4proto { tcp, udp } th dport 1053 '
            'counter reject with icmpx type admin-prohibited'])
        self.assertEqual(zone[3:], active['dns_zone_output'][1:])
        self.assertEqual(stopping['output'], active['output'])
        self.assertEqual(stopping['forward'], active['forward'])

    # ON.

    def test_fresh_on_does_not_capture_own_dns(self):
        self.make_off()
        self.set_resolver(self.managed)  # stale resolver written by the earlier controller
        self.g['status'] = lambda: 0
        self.capture('on')
        saved = json.loads(self.statefile.read_text())['resolver_before']
        self.assertEqual(saved,self.good)
        # The legacy resolver is migrated back once; ON never points it at the TUN.
        self.assertEqual(os.readlink(self.resolv),str(self.wsl))

    def test_fresh_on_honors_changed_nonmanaged_dns(self):
        self.make_off()
        changed = b'# edited by user while OFF\nnameserver 9.9.9.9\n'
        self.set_resolver(changed, 0o640)
        before = self.resolver_identity()
        self.g['status'] = lambda: 0
        self.capture('on')
        saved = json.loads(self.statefile.read_text())['resolver_before']
        self.assertEqual(saved,self.file_snapshot(changed))
        # WSL and the user keep ownership: ON leaves the file itself untouched.
        self.assertEqual(self.resolver_identity(),before)

    def test_fresh_on_bad_recovery_does_not_enable_guard_or_marker(self):
        self.make_off()
        self.set_resolver(self.managed)
        self.state['resolver_before'] = self.file_snapshot(self.managed)
        self.save(self.state)
        self.wsl.write_bytes(self.managed)
        with self.assertRaisesRegex(RuntimeError, '原 DNS 备份无效'):
            self.capture('on')
        self.assertFalse(self.enabled.exists())
        self.assertFalse(self.runtime.exists())
        self.assertFalse(self.kernel.guard)
        self.assertEqual(self.kernel.loads,[])
        self.assertEqual(self.resolv.read_bytes(),self.managed)

    def test_fresh_on_intercepts_dns_without_writing_resolver(self):
        self.make_off()
        before = self.resolver_identity()
        result, output = self.capture('on')
        self.assertEqual(result, 0, output)
        self.assertEqual(self.resolver_identity(), before)
        self.assertIn('代理状态：已开启（WSL 全流量）', output)
        self.assertIn(DNS_TAKEOVER, output)
        self.assertIn(CHECK_OK, output)
        self.assertIn('默认 DNS 连通性：' + PROBE_OK[1], output)
        calls = self.kernel.calls
        # Dependency and ownership checks precede the first change.
        first_change = calls.index(('nft','-f','-'))
        for check in (('nft','-j','list','ruleset'), (str(self.conntrack),'-L','-f','ipv4','--zone','20262'),
                      ('ss','-H','-l','-n','-t','-u','-p','sport','=',':1053')):
            self.assertLess(calls.index(check), first_change)
        self.assertEqual(len(self.kernel.loads), 1)
        self.assertIn('dns_nat_output', chains(self.kernel.table))
        self.assertIn(('systemctl','restart','xq-proxy.service'), calls)
        state = self.load_state()
        self.assertEqual((state['phase'], state['dns_active'], state['dns_zone'], state['dns_mark']),
                         ('active', True, 20262, DNS_MARK))
        self.assertEqual(state['guard_digest'], sha256(self.kernel.table))
        self.assertEqual(state['running_config_digest'], sha256(self.config.read_bytes()))
        self.assertEqual(state['running_core_digest'], sha256(self.core_binary.read_bytes()))
        config = json.loads(self.config.read_text())
        self.assertIn({'type':'direct','tag':'dns-in','listen':'127.0.0.1','listen_port':1053}, config['inbounds'])
        self.assertEqual(config['route']['rules'], [{'inbound':'dns-in','action':'hijack-dns'},
                                                    {'inbound':'tun-in','port':53,'action':'hijack-dns'}])
        self.assertEqual(config['dns']['servers'][0]['detour'], 'karing')
        self.assertTrue(self.enabled.exists())
        self.assertTrue(self.runtime.exists())
        self.assertEqual(self.syslog.records, [
            (syslog.LOG_INFO, 'attach completed: TUN routes and local DNS TCP/UDP 1053 ready; resolver unchanged'),
            (syslog.LOG_INFO, 'on completed: configuration and default DNS healthy')])
        self.assertEqual(self.syslog.idents, {('xq-proxyctl', syslog.LOG_PID, syslog.LOG_DAEMON)})

    def test_repeated_healthy_on_keeps_running_core(self):
        before = self.resolver_identity()
        result, output = self.capture('on')
        self.assertEqual(result, 0, output)
        self.assertNotIn(('systemctl','restart','xq-proxy.service'), self.kernel.calls)
        self.assertEqual(self.resolver_identity(), before)
        self.assertEqual(self.load_state()['guard_digest'], sha256(self.kernel.table))
        self.assertEqual(self.syslog.records, [(syslog.LOG_INFO, 'on completed: configuration and default DNS healthy')])

    def test_on_restarts_core_unless_running_version_is_verified(self):
        cases = (('controller upgrade without running digests',
                  lambda: [self.state.pop(key) for key in ('running_config_digest', 'running_core_digest')]),
                 ('sing-box binary replaced', lambda: self.core_binary.write_bytes(b'upgraded sing-box\n')),
                 ('core started before the current config', lambda: self.state.update(running_config_digest='0'*64)))
        for label, change in cases:
            with self.subTest(label):
                self.reset()
                change()
                self.save(self.state)
                result, output = self.capture('on')
                self.assertEqual(result, 0, output)
                self.assertIn(('systemctl','restart','xq-proxy.service'), self.kernel.calls)
                state = self.load_state()
                self.assertEqual(state['running_config_digest'], sha256(self.config.read_bytes()))
                self.assertEqual(state['running_core_digest'], sha256(self.core_binary.read_bytes()))

    def test_on_migrates_legacy_tun_resolver_once(self):
        # Upgraded while ON from the controller that rewrote resolv.conf on attach.
        self.set_resolver(self.managed)
        result, output = self.capture('on')
        self.assertEqual(result, 0, output)
        self.assertEqual(os.readlink(self.resolv), str(self.wsl))
        migrated = self.resolver_identity()
        result, output = self.capture('on')
        self.assertEqual(result, 0, output)
        self.assertEqual(self.resolver_identity(), migrated)

    def test_on_refuses_foreign_conntrack_mark_or_zone_rules(self):
        self.make_off()
        foreign = {
            'ct mark match': [{'match': {'op': '==', 'left': {'ct': {'key': 'mark'}}, 'right': 1}},
                              {'accept': None}],
            'ct zone set': [{'mangle': {'key': {'ct': {'key': 'zone'}}, 'value': 7}}],
            'meta mark from ct mark': [{'mangle': {'key': {'meta': {'key': 'mark'}},
                                                   'value': {'ct': {'key': 'mark'}}}}],
        }
        tables = [('ip', 'mangle', label) for label in foreign] + [('ip', 'xq_proxy', 'ct zone set')]
        for family, table, label in tables:
            with self.subTest(family=family, table=table, rule=label):
                self.kernel.foreign_rules = [{'rule': {'family': family, 'table': table,
                                                       'chain': 'output', 'expr': foreign[label]}}]
                self.assert_on_refused('其他 nft 表使用 conntrack mark/zone，无法确认 DNS zone 20262 '
                                       '和标记 0x02000000 无冲突；拒绝覆盖')
        # Connection-state matches (Docker, ufw) neither read nor set the owned mark or zone.
        self.kernel.foreign_rules = [{'rule': {'family': 'ip', 'table': 'filter', 'chain': 'INPUT', 'expr': [
            {'match': {'op': 'in', 'left': {'ct': {'key': 'state'}}, 'right': ['established', 'related']}},
            {'accept': None}]}}]
        result, output = self.capture('on')
        self.assertEqual(result, 0, output)

    def test_on_refuses_unclear_dns_conntrack_zone(self):
        self.make_off()
        with self.subTest('zone cannot be listed'):
            self.kernel.zone_list_error = 'conntrack v1.4.8 (conntrack-tools): Operation not supported'
            self.assert_on_refused('无法检查 DNS conntrack zone：conntrack v1.4.8 (conntrack-tools): Operation not supported')
            self.kernel.zone_list_error = None
        with self.subTest('owned zone holds a flow without the owned mark'):
            self.kernel.zone_entries = [ZONE_ENTRY.format(mark=DNS_MARK), ZONE_ENTRY.format(mark=0)]
            self.assert_on_refused('DNS conntrack zone 20262 存在非本功能标记的连接，拒绝启用')
        with self.subTest('zone in use without recorded ownership'):
            for key in ('dns_zone', 'dns_mark'):
                self.state.pop(key)
            self.save(self.state)
            self.kernel.zone_entries = [ZONE_ENTRY.format(mark=DNS_MARK)]
            self.assert_on_refused('DNS conntrack zone 20262 已被占用，拒绝启用')

    def test_on_adopts_own_marked_dns_flows(self):
        # OFF keeps dns_zone/dns_mark, so flows of the previous ON still in their timeout are ours.
        self.make_off()
        self.kernel.zone_entries = [ZONE_ENTRY.format(mark=DNS_MARK | 0x1)]
        result, output = self.capture('on')
        self.assertEqual(result, 0, output)

    def test_on_refuses_foreign_dns_port_listener(self):
        with self.subTest('another process while the core holds 127.0.0.1:1053'):
            self.kernel.foreign_listeners = ['udp UNCONN 0 0 0.0.0.0:1053 0.0.0.0:* users:(("dnsmasq",pid=777,fd=4))']
            # A repeated ON refuses before re-applying the guard.
            self.assert_on_refused('DNS 端口 1053 已被其他进程占用，拒绝启用')
        with self.subTest('any listener while the service has no main process'):
            self.make_off()
            self.kernel.foreign_listeners = ['tcp LISTEN 0 4096 127.0.0.1:1053 0.0.0.0:* users:(("python3",pid=4242,fd=3))']
            self.assert_on_refused('DNS 端口 1053 已被其他进程占用，拒绝启用')

    def test_on_without_conntrack_refuses_before_any_change(self):
        for label, remove in (('missing', lambda: self.conntrack.unlink()),
                              ('not executable', lambda: self.conntrack.chmod(0o644))):
            with self.subTest(label):
                self.reset()
                self.make_off()
                remove()
                self.assert_on_refused(NEED_CONNTRACK)
                self.assertEqual(self.kernel.calls, [])

    def test_on_without_local_dns_listener_fails_closed(self):
        self.make_off()
        before = self.resolver_identity()
        self.kernel.listening['-u'] = False
        # ON only sees systemd's generic job failure; attach's 1053 message is covered by
        # test_attach_waits_briefly_for_both_local_dns_listeners.
        with self.assertRaisesRegex(RuntimeError, re.escape('systemctl restart xq-proxy.service: Job for xq-proxy.service failed')):
            self.capture('on')
        # DNS stays translated to the dead local entry: no fallback to the WSL resolver.
        self.assertIn('dns_nat_output', chains(self.kernel.table))
        self.assertTrue(self.enabled.exists())
        self.assertEqual(self.resolver_identity(), before)

    def test_on_with_failing_default_dns_keeps_guard(self):
        self.probe_result = (False, '10.255.255.254: timed out')
        result, output = self.capture('on')
        self.assertEqual(result, 1, output)
        self.assertTrue(self.kernel.guard)
        self.assertTrue(self.enabled.exists())
        self.assertEqual(self.syslog.records[-1],
                         (syslog.LOG_WARNING, 'on completed: health check failed; direct-traffic guard retained'))

    # attach (ExecStartPost of xq-proxy.service).

    def test_attach_routes_tun_without_touching_resolver(self):
        for key in ('phase', 'running_config_digest', 'running_core_digest'):
            self.state.pop(key)
        self.save(self.state)
        self.kernel.remove_routes()
        before = self.resolver_identity()
        self.original['attach']()
        self.assertEqual(self.resolver_identity(), before)
        state = self.load_state()
        self.assertEqual(self.g['route_issues'](state), [])
        self.assertEqual(state['phase'], 'active')
        self.assertEqual(state['running_config_digest'], sha256(self.config.read_bytes()))
        self.assertEqual(state['running_core_digest'], sha256(self.core_binary.read_bytes()))
        self.assertEqual(self.syslog.records, [
            (syslog.LOG_INFO, 'attach completed: TUN routes and local DNS TCP/UDP 1053 ready; resolver unchanged')])

    def test_attach_waits_briefly_for_both_local_dns_listeners(self):
        for key in ('running_config_digest', 'running_core_digest'):
            self.state.pop(key)
        self.save(self.state)
        for label, change in (('UDP missing', lambda: self.kernel.listening.update({'-u': False})),
                              ('TCP missing', lambda: self.kernel.listening.update({'-t': False})),
                              ('not loopback', lambda: setattr(self.kernel, 'dns_bind', '0.0.0.0:1053'))):
            with self.subTest(label):
                self.kernel.listening, self.kernel.dns_bind = {'-t': True, '-u': True}, '127.0.0.1:1053'
                change()
                self.sleeps.clear()
                with self.assertRaisesRegex(RuntimeError, re.escape('本地 DNS TCP/UDP 1053 未监听；guard 保留')):
                    self.original['attach']()
                self.assertEqual(self.sleeps, [0.1] * 30)
                self.assertTrue(self.kernel.guard)
                self.assertNotIn('running_config_digest', self.load_state())
        self.assertEqual(self.syslog.records, [])

    # OFF and boot-off.

    def test_off_restores_stale_managed_dns_without_marker_or_guard(self):
        self.make_off()
        self.set_resolver(self.managed)
        result, output = self.capture('off')
        self.assertEqual(result,0,output)
        self.assertTrue(self.resolv.is_symlink())
        self.assertEqual(os.readlink(self.resolv),str(self.wsl))

    def test_repeated_off_preserves_user_dns(self):
        self.make_off()
        self.set_resolver(self.managed)
        self.capture('off')
        edited = b'nameserver 9.9.9.9\nsearch my.example\n'
        self.set_resolver(edited)
        result, output = self.capture('off')
        self.assertEqual(result,0,output)
        self.assertEqual(self.resolv.read_bytes(),edited)
        self.assertFalse(self.resolv.is_symlink())

    def test_route_only_off_cleanup_preserves_nonmanaged_dns(self):
        self.make_off()
        edited = b'nameserver 9.9.9.9\nsearch changed.example\n'
        self.set_resolver(edited)
        self.kernel.rules4.append({'priority':18402,'table':20260})
        self.kernel.routes4 = [{'dst':'default','dev':'xq-tun'}]
        result, output = self.capture('off')
        self.assertEqual(result,0,output)
        self.assertEqual(self.resolv.read_bytes(),edited)
        self.assertFalse(any(r.get('priority')==18402 for r in self.kernel.rules4))
        # Nothing was translated since the last clean OFF.
        self.assertEqual(self.conntrack_calls(),[])

    def test_off_invalid_restore_retains_running_core_and_guard(self):
        self.state['resolver_before'] = self.file_snapshot(self.managed)
        self.save(self.state)
        self.wsl.write_bytes(self.managed)
        with self.assertRaisesRegex(RuntimeError, '原 DNS 备份无效'):
            self.capture('off')
        self.assertTrue(self.enabled.exists())
        self.assertTrue(self.kernel.core)
        self.assertTrue(self.kernel.guard)
        self.assertNotIn(('systemctl','stop','xq-proxy.service'),self.kernel.calls)
        self.assertNotIn(('nft','delete','table','inet','xq_proxy'),self.kernel.calls)
        # The DNS shutdown stage has not started either.
        self.assertEqual(self.kernel.loads,[])
        self.assertEqual(self.conntrack_calls(),[])
        self.assertEqual(self.load_state()['phase'],'active')

    def test_off_stops_new_dns_before_core_and_removes_owned_mappings(self):
        observed = []
        self.kernel.on_stop = lambda: observed.append(
            (self.enabled.exists(), self.load_state()['phase'], 'dns_nat_output' in chains(self.kernel.table)))
        self.kernel.zone_entries = [ZONE_ENTRY.format(mark=DNS_MARK)]
        before = self.resolver_identity()
        result, output = self.capture('off')
        self.assertEqual(result, 0, output)
        self.assertIn('代理状态：已关闭（恢复原网络）', output)
        self.assertNotIn('DNS 接管', output)
        self.assertEqual(self.probes, [])
        calls = self.kernel.calls
        delete = (str(self.conntrack), *CONNTRACK_DELETE)
        steps = [calls.index(step) for step in (('nft','-f','-'), ('systemctl','stop','xq-proxy.service'), delete,
                                                ('remove-owned-routes',), ('nft','delete','table','inet','xq_proxy'))]
        self.assertEqual(steps, sorted(steps))
        # When the core stops, systemd cannot restart it and no new DNS is translated.
        self.assertEqual(observed, [(False, 'disabling', False)])
        self.assertIn('meta skuid != 999 meta nfproto ipv4 meta l4proto { tcp, udp } th dport 53 '
                      'counter reject with icmpx type admin-prohibited', chains(self.kernel.loads[0])['dns_zone_output'])
        # Only this feature's mappings are deleted; the host conntrack table is never flushed.
        self.assertEqual(self.conntrack_calls(), [delete])
        self.assertEqual(self.kernel.zone_entries, [])
        self.assertEqual(self.resolver_identity(), before)
        state = self.load_state()
        self.assertEqual((state['phase'], state['dns_active'], state['dns_zone'], state['dns_mark']),
                         ('off', False, 20262, DNS_MARK))
        self.assertFalse(self.enabled.exists())
        self.assertFalse(self.runtime.exists())
        self.assertFalse(self.kernel.guard)
        self.assertEqual(self.syslog.records,
                         [(syslog.LOG_INFO, 'off completed: owned DNS mappings, routes and guard removed')])

    def test_off_leaves_rewritten_resolver_untouched(self):
        # WSL regenerated resolv.conf as a regular file while ON; it is not ours to restore.
        self.set_resolver(b'# generated by WSL\nnameserver 10.255.255.254\n')
        before = self.resolver_identity()
        result, output = self.capture('off')
        self.assertEqual(result, 0, output)
        self.assertEqual(self.resolver_identity(), before)

    def test_off_without_conntrack_refuses_before_any_change(self):
        before = self.world()
        self.conntrack.unlink()
        with self.assertRaisesRegex(RuntimeError, re.escape(NEED_CONNTRACK)):
            self.capture('off')
        self.assertEqual(self.kernel.calls, [('nft','list','table','inet','xq_proxy')])
        self.assertEqual(self.world(), before)

    def test_off_conntrack_failure_keeps_guard_and_resumes(self):
        for code, stderr in ((2, 'conntrack v1.4.8 (conntrack-tools): Operation failed: invalid parameters'),
                             (1, 'conntrack v1.4.8 (conntrack-tools): Operation not permitted')):
            with self.subTest(code=code, stderr=stderr):
                self.reset()
                self.kernel.delete_error = (code, stderr + '\n')
                with self.assertRaisesRegex(RuntimeError, re.escape('清理本功能 DNS conntrack 失败；guard 保留：' + stderr)):
                    self.capture('off')
                self.assertTrue(self.kernel.guard)
                self.assertNotIn('dns_nat_output', chains(self.kernel.table))
                self.assertNotIn(('remove-owned-routes',), self.kernel.calls)
                self.assertFalse(self.enabled.exists())
                self.assertEqual(self.load_state()['phase'], 'disabling')
                result, output = self.capture('status')
                self.assertEqual(result, 1)
                self.assertIn('OFF，但存在残留配置', output)
                self.assertIn('建议执行：xq_proxyoff 清理残留配置', output)
                # A rerun resumes the cleanup once conntrack works.
                self.kernel.delete_error = None
                result, output = self.capture('off')
                self.assertEqual(result, 0, output)
                self.assertFalse(self.kernel.guard)
                self.assertEqual(self.load_state()['phase'], 'off')

    def test_boot_off_does_not_stop_own_unit(self):
        result, output = self.capture('off',from_boot=True)
        self.assertEqual(result,0,output)
        self.assertNotIn(('systemctl','stop','xq-proxy-boot.service'),self.kernel.calls)
        self.assertEqual(self.syslog.records[-1],
                         (syslog.LOG_INFO, 'boot-off completed: owned DNS mappings, routes and guard removed'))

    def test_boot_off_after_terminated_on_session_needs_conntrack(self):
        # wsl --terminate while ON: flag and state persist, kernel state is gone.
        self.kernel.clear()
        self.conntrack.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, re.escape(NEED_CONNTRACK)):
            self.capture('off', from_boot=True)
        self.assertTrue(self.enabled.exists())
        self.conntrack.chmod(0o755)
        result, output = self.capture('off', from_boot=True)
        self.assertEqual(result, 0, output)
        self.assertEqual(self.conntrack_calls(), [(str(self.conntrack), *CONNTRACK_DELETE)])
        self.assertEqual(self.kernel.loads, [])
        self.assertFalse(self.enabled.exists())
        self.assertEqual(self.load_state()['phase'], 'off')

    def test_boot_off_after_clean_off_does_not_need_conntrack(self):
        self.make_off()
        self.conntrack.unlink()
        result, output = self.capture('off', from_boot=True)
        self.assertEqual(result, 0, output)
        self.assertEqual(self.conntrack_calls(), [])

    # status.

    def test_healthy_status_returns_zero_without_mutation(self):
        before = (self.resolver_identity(), self.statefile.read_bytes())
        result, output = self.capture('status')
        self.assertEqual(result,0,output)
        self.assertIn('代理状态：已开启（WSL 全流量）',output)
        self.assertIn(DNS_TAKEOVER,output)
        self.assertIn(CHECK_OK,output)
        self.assertIn('默认 DNS 连通性：'+PROBE_OK[1],output)
        self.assertNotIn('检查异常',output)
        self.assertEqual(self.probes,[4])
        self.assertFalse(any('stop' in call or 'restart' in call or 'delete' in call or '-D' in call
                             for call in self.kernel.calls))
        self.assertEqual(self.kernel.loads,[])
        self.assertEqual((self.resolver_identity(), self.statefile.read_bytes()),before)
        self.assertEqual(self.syslog.records,[])

    def test_wsl_rewritten_resolver_is_not_flagged(self):
        # WSL may regenerate or relink resolv.conf while ON (the 2026-11-14 outage).
        # Interception is in nft, so none of these is a configuration issue.
        other = self.root/'wsl'/'other.conf'
        other.write_text('nameserver 172.21.32.1\n')
        def relink():
            self.resolv.unlink()
            self.resolv.symlink_to(other)
        cases = (('formerly "wrong DNS" fixture', lambda: self.set_resolver(b'nameserver 172.30.255.20\n')),
                 ('regenerated as a regular file', lambda: self.set_resolver(self.wsl.read_bytes())),
                 ('relinked elsewhere', relink),
                 ('IPv6 entry beside IPv4', lambda: self.set_resolver(b'nameserver fd00::53\nnameserver 9.9.9.9\n')))
        for label, change in cases:
            with self.subTest(label):
                change()
                self.probes.clear()
                result, output = self.capture('status')
                self.assertEqual(result, 0, output)
                self.assertNotIn('检查异常', output)
                self.assertIn(CHECK_OK, output)
                self.assertEqual(self.probes, [4])

    def test_resolver_without_usable_ipv4_dns_returns_nonzero(self):
        cases = ((b'nameserver fd00::53\n', '默认 resolver 缺少 IPv4 DNS（IPv6 仍按策略阻断）'),
                 (b'# no DNS servers\nsearch example.test\n', '默认 resolver 缺少 IPv4 DNS（IPv6 仍按策略阻断）'),
                 (b'nameserver not-an-ip\n', 'DNS 配置不可读取'),
                 (None, 'DNS 配置不可读取'))
        for data, issue in cases:
            with self.subTest(data=data):
                if data is None:  # dangling WSL link
                    self.resolv.unlink()
                    self.resolv.symlink_to(self.root/'wsl'/'missing.conf')
                else:
                    self.set_resolver(data)
                result, output = self.capture('status')
                self.assertEqual(result,1)
                self.assertIn('ON，但配置异常',output)
                self.assertIn('检查异常：'+issue,output)
                self.assertIn(NOT_PROBED,output)
                self.assertEqual(self.probes,[])

    def test_legacy_tun_resolver_status_returns_nonzero(self):
        for data in (b'nameserver 172.30.255.2\nnameserver 9.9.9.9\n', self.managed,
                     (self.g['DNS_HEADER']+'\nnameserver 9.9.9.9\n').encode()):
            with self.subTest(data=data):
                self.set_resolver(data)
                result, output = self.capture('status')
                self.assertEqual(result,1)
                self.assertIn('检查异常：仍残留旧版 TUN resolver；需要迁移回原 DNS',output)

    def test_dns_takeover_drift_is_reported(self):
        def edit_guard():
            self.kernel.table += '# edited by hand\n'
        cases = (
            ('guard edited by hand', edit_guard, 'DNS 接管或防直连规则与已安装摘要不匹配'),
            ('guard left in OFF shutdown shape', lambda: self.patch_state(dns_active=False),
             'DNS 接管或防直连规则与已安装摘要不匹配'),
            ('UDP listener missing', lambda: self.kernel.listening.update({'-u': False}), '本地 DNS TCP/UDP 1053 监听不完整'),
            ('TCP listener missing', lambda: self.kernel.listening.update({'-t': False}), '本地 DNS TCP/UDP 1053 监听不完整'),
            ('listener not on loopback', lambda: setattr(self.kernel, 'dns_bind', '0.0.0.0:1053'),
             '本地 DNS TCP/UDP 1053 监听不完整'),
            ('conntrack removed', lambda: self.conntrack.unlink(), '缺少 conntrack，无法安全关闭 DNS 接管'),
            ('core config drifted', lambda: self.config.write_text('{}\n'), '代理核心配置偏离预期'),
            ('core not reloaded', lambda: self.patch_state(running_config_digest='0'*64), '当前核心尚未加载最新配置'),
            ('core binary replaced', lambda: self.core_binary.write_bytes(b'other\n'), '代理核心二进制已变化，需要重启加载'),
            ('core config missing', lambda: self.config.unlink(), '代理核心配置或二进制不可检查'),
            ('recovery baseline unusable', lambda: self.patch_state(resolver_before=self.file_snapshot(self.managed)),
             '原 DNS 恢复备份不可用'),
        )
        for label, change, issue in cases:
            with self.subTest(label):
                self.reset()
                change()
                result, output = self.capture('status')
                self.assertEqual(result, 1, output)
                self.assertIn('代理状态：ON，但配置异常', output)
                self.assertIn('配置检查：异常', output)
                self.assertIn('检查异常：' + issue, output)
                self.assertIn('建议执行：xq_proxyon 重新应用配置，或 xq_proxyoff 恢复普通网络', output)
                self.assertIn(NOT_PROBED, output)
                self.assertEqual(self.probes, [])

    def test_failed_default_dns_probe_returns_nonzero(self):
        def broken(timeout=4):
            raise OSError('[Errno 2] No such file or directory')
        timed_out = (False, '10.255.255.254: timed out')
        for label, setup, detail in (('probe timed out', lambda: setattr(self, 'probe_result', timed_out),
                                      '10.255.255.254: timed out'),
                                     ('resolver vanished during the probe', lambda: self.g.update(dns_probe=broken),
                                      '[Errno 2] No such file or directory')):
            with self.subTest(label):
                self.reset()
                setup()
                result, output = self.capture('status')
                self.assertEqual(result, 1)
                # The configuration itself is complete; only the default DNS path failed.
                self.assertIn('代理状态：已开启（WSL 全流量）', output)
                self.assertIn(CHECK_OK, output)
                self.assertIn('默认 DNS 连通性：' + detail, output)
                self.assertIn('配置完整，但默认 DNS 探测失败；请检查上游和服务日志。', output)
                self.assertNotIn('建议执行', output)
                self.assertEqual(self.syslog.records, [(syslog.LOG_WARNING, 'default DNS health probe failed: ' + detail)])

    def test_wrong_rule_uid_and_table_return_nonzero(self):
        cases = ((1,'iif','eth0','TUN 返回路由规则'),
                 (2,'uid_start',1000,'代理用户路由规则'),
                 (2,'uid_end',1000,'代理用户路由规则'),
                 (3,'table','main','IPv4 TUN 路由规则'))
        original = copy.deepcopy(self.kernel.rules4)
        for index,key,value,label in cases:
            with self.subTest(index=index,key=key):
                self.kernel.rules4 = copy.deepcopy(original)
                self.kernel.rules4[index][key] = value
                result, output = self.capture('status')
                self.assertEqual(result,1)
                self.assertIn(label,output)

    def test_wrong_ipv4_default_route_status_returns_nonzero(self):
        self.kernel.routes4 = [{'dst':'default','dev':'eth0'}]
        result, output = self.capture('status')
        self.assertEqual(result,1)
        self.assertIn('IPv4 默认路由',output)

    def test_extra_rule_selectors_are_not_reported_complete(self):
        cases = ({'src':'192.0.2.0/24'}, {'dst':'198.51.100.0/24'},
                 {'fwmark':'0x1'}, {'iif':'eth0'}, {'ipproto':'tcp'})
        original = copy.deepcopy(self.kernel.rules4)
        for extra in cases:
            with self.subTest(extra=extra):
                self.kernel.rules4 = copy.deepcopy(original)
                self.kernel.rules4[3].update(extra)
                result, output = self.capture('status')
                self.assertEqual(result,1)
                self.assertIn('IPv4 TUN 路由规则',output)

    def test_duplicate_policy_rule_is_not_reported_complete(self):
        self.kernel.rules4.append(copy.deepcopy(self.kernel.rules4[3]))
        result, output = self.capture('status')
        self.assertEqual(result,1)
        self.assertIn('IPv4 TUN 路由规则',output)

    def test_changed_gateway_status_returns_nonzero(self):
        self.g['gateway'] = lambda: ('172.22.32.1','eth0')
        result, output = self.capture('status')
        self.assertEqual(result,1)
        self.assertIn('代理上游与当前 Windows 网关或网卡不一致',output)

    def test_unavailable_gateway_status_returns_nonzero(self):
        def unavailable():
            raise RuntimeError('no gateway')
        self.g['gateway'] = unavailable
        result, output = self.capture('status')
        self.assertEqual(result,1)
        self.assertIn('物理默认网关不可用',output)

    def test_missing_ipv6_unreachable_status_returns_nonzero(self):
        self.kernel.routes6 = [{'dst':'default','dev':'eth0','type':'unicast'}]
        result, output = self.capture('status')
        self.assertEqual(result,1)
        self.assertIn('IPv6 不可达路由',output)

    def test_off_with_dns_residue_is_not_reported_clean(self):
        self.make_off()
        self.set_resolver(self.managed)
        result, output = self.capture('status')
        self.assertEqual(result,1)
        self.assertIn('OFF，但存在残留配置',output)
        self.assertIn('检查异常：OFF 状态仍有代理核心、防火墙或 TUN DNS 残留',output)
        self.assertNotIn('DNS 接管',output)
        self.assertEqual(self.probes,[])

    # Default DNS probe (status), against a fake resolver network.

    def test_dns_probe_accepts_matching_answer(self):
        result, network = self.real_probe(b'nameserver 10.255.255.254\n', {'10.255.255.254': dns_answer()})
        self.assertEqual(result, PROBE_OK)
        (server, query), = network.sent
        self.assertEqual(server, ('10.255.255.254', 53))
        # One recursive A query for example.com.
        self.assertEqual(query[2:], struct.pack('!HHHHH', 0x0100, 1, 0, 0, 0)
                         + b'\x07example\x03com\x00\x00\x01\x00\x01')
        self.assertTrue(0 < network.timeouts[0] <= 4)

    def test_dns_probe_rejects_unusable_answers(self):
        cases = {
            'other query ID': (dns_answer(same_id=False), 'DNS 响应 ID/长度不匹配'),
            'short header': (lambda query: query[:2] + b'\x81\x80', 'DNS 响应 ID/长度不匹配'),
            'not a response': (dns_answer(flags=0x0100), 'DNS 响应未返回成功答案'),
            'NXDOMAIN': (dns_answer(flags=0x8183), 'DNS 响应未返回成功答案'),
            'truncated': (dns_answer(flags=0x8380), 'DNS 响应未返回成功答案'),
            'no answer record': (dns_answer(answers=0), 'DNS 响应未返回成功答案'),
            'two questions': (dns_answer(questions=2), 'DNS 响应未返回成功答案'),
            'timeout': (TimeoutError('timed out'), 'timed out'),
            'refused': (ConnectionRefusedError(111, 'Connection refused'), '[Errno 111] Connection refused'),
        }
        for label, (answer, detail) in cases.items():
            with self.subTest(label):
                result, _ = self.real_probe(b'nameserver 10.255.255.254\n', {'10.255.255.254': answer})
                self.assertEqual(result, (False, '10.255.255.254: ' + detail))

    def test_dns_probe_tries_next_ipv4_server_within_budget(self):
        result, network = self.real_probe(b'nameserver fd00::53\nnameserver 10.255.255.254\nnameserver 9.9.9.9\n',
                                          {'10.255.255.254': TimeoutError('timed out'), '9.9.9.9': dns_answer()})
        self.assertEqual(result, (True, '成功（默认 DNS 9.9.9.9，example.com A）'))
        self.assertEqual([server for server, _ in network.sent], [('10.255.255.254', 53), ('9.9.9.9', 53)])
        # The first server gets its share of the 4 s budget, never all of it.
        self.assertTrue(0 < network.timeouts[0] <= 2)
        self.assertTrue(all(0 < value <= 4 for value in network.timeouts))
        result, _ = self.real_probe(b'nameserver 10.255.255.254\nnameserver 9.9.9.9\n',
                                    {'10.255.255.254': TimeoutError('timed out'), '9.9.9.9': dns_answer(flags=0x8182)})
        self.assertEqual(result, (False, '10.255.255.254: timed out; 9.9.9.9: DNS 响应未返回成功答案'))

    def test_dns_probe_sends_nothing_without_ipv4_server_or_time(self):
        result, network = self.real_probe(b'nameserver fd00::53\n', {})
        self.assertEqual(result, (False, '默认 resolver 没有 IPv4 DNS（IPv6 仍按策略阻断）'))
        self.assertEqual(network.sent, [])
        result, network = self.real_probe(b'nameserver 10.255.255.254\n', {'10.255.255.254': dns_answer()}, timeout=0)
        self.assertEqual(result, (False, '默认 DNS 探测超时'))
        self.assertEqual(network.sent, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
