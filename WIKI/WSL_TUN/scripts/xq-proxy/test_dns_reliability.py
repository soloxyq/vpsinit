#!/usr/bin/env python3
"""Offline controller regressions: temporary files, fake kernel, no network/root."""
import base64
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import runpy
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest

CONTROLLER = Path(__file__).with_name('xq-proxyctl')
if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
    CONTROLLER = Path(sys.argv.pop(1))


class FakeKernel:
    def __init__(self):
        self.calls = []
        self.core = True
        self.guard = True
        self.link_up = True
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
        self.remove_routes()
        self.calls.clear()

    def run(self, args, *, check=True, data=None):
        a = tuple(args)
        self.calls.append(a)
        code, stdout = 0, ''
        if a == ('systemctl','is-active','--quiet','xq-proxy.service'):
            code = 0 if self.core else 3
        elif a == ('systemctl','stop','xq-proxy.service'):
            self.core = self.link_up = False
        elif a == ('systemctl','stop','xq-proxy-boot.service'):
            pass
        elif a == ('systemctl','restart','xq-proxy.service'):
            self.core = self.link_up = True
        elif a == ('nft','list','table','inet','xq_proxy'):
            code = 0 if self.guard else 1
        elif a == ('nft','delete','table','inet','xq_proxy'):
            self.guard = False
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
        elif a == ('ip','-j','-4','addr','show','dev','eth0'):
            stdout = json.dumps([{'addr_info':[{'family':'inet','local':'172.21.38.15'}]}])
        elif a[:3] == ('/usr/bin/sing-box','check','-c'):
            pass
        else:
            raise AssertionError('Unexpected simulated command; no process was run: '+repr(a))
        if check and code:
            raise RuntimeError('simulated command failure: '+repr(a))
        return SimpleNamespace(returncode=code, stdout=stdout, stderr='')


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xq-dns-offline-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mod = runpy.run_path(str(CONTROLLER), run_name='offline_controller_test')
        self.g = mod['on'].__globals__
        self.state_dir = self.root/'state'
        self.state_dir.mkdir()
        self.resolv = self.root/'etc'/'resolv.conf'
        self.resolv.parent.mkdir()
        self.wsl = self.root/'wsl'/'resolv.conf'
        self.wsl.parent.mkdir()
        self.wsl.write_text('nameserver 10.255.255.254\n')
        self.runtime = self.root/'runtime-enabled'
        self.enabled = self.state_dir/'enabled'
        self.statefile = self.state_dir/'state.json'
        self.config = self.root/'config'/'sing-box.json'
        self.kernel = FakeKernel()
        # Only the hardcoded runtime marker is remapped; all other filesystem work
        # already uses the temporary paths injected below.
        def mapped_path(value):
            p = Path(value)
            return self.runtime if str(p) == '/run/xq-proxy-enabled' else p
        self.g.update(STATE=self.state_dir, ENABLED=self.enabled, STATEFILE=self.statefile,
                      RESOLV=self.resolv, WSL_RESOLV=self.wsl, CONF=self.config,
                      Path=mapped_path, run=self.kernel.run,
                      gateway=lambda: ('172.21.32.1','eth0'),
                      pwd=SimpleNamespace(getpwnam=lambda _:SimpleNamespace(pw_uid=999)),
                      preflight=lambda _:None, remove_routes=self.kernel.remove_routes)
        def install_guard(_):
            self.kernel.calls.append(('install-guard',))
            self.kernel.guard = True
        self.g['install_guard'] = install_guard
        self.good = {'kind':'symlink','target':str(self.wsl)}
        self.state = {'phase':'active','host':'172.21.32.1','interface':'eth0',
                      'uid':999,'port':4066,'resolver_before':self.good}
        self.managed = (self.g['DNS_HEADER']+'\nnameserver 172.30.255.2\noptions timeout:2 attempts:2\n').encode()
        self.resolv.write_bytes(self.managed)
        self.enabled.write_text('on\n')
        self.runtime.write_text('on\n')
        self.save(self.state)

    def save(self, value):
        self.statefile.write_text(json.dumps(value))

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
        self.state['phase'] = 'off'
        self.save(self.state)

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

    def test_fresh_on_does_not_capture_own_dns(self):
        self.make_off()
        self.g['status'] = lambda: 0
        self.capture('on')
        saved = json.loads(self.statefile.read_text())['resolver_before']
        self.assertEqual(saved,self.good)
        self.assertFalse(self.g['managed_dns'](base64.b64decode(saved['data'])) if saved['kind']=='file' else False)

    def test_fresh_on_honors_changed_nonmanaged_dns(self):
        self.make_off()
        changed = b'# edited by user while OFF\nnameserver 9.9.9.9\n'
        self.resolv.write_bytes(changed)
        self.resolv.chmod(0o640)
        self.g['status'] = lambda: 0
        self.capture('on')
        saved = json.loads(self.statefile.read_text())['resolver_before']
        self.assertEqual(saved,self.file_snapshot(changed))

    def test_fresh_on_bad_recovery_does_not_enable_guard_or_marker(self):
        self.make_off()
        self.state['resolver_before'] = self.file_snapshot(self.managed)
        self.save(self.state)
        self.wsl.write_bytes(self.managed)
        with self.assertRaises(RuntimeError):
            self.capture('on')
        self.assertFalse(self.enabled.exists())
        self.assertFalse(self.kernel.guard)
        self.assertNotIn(('install-guard',),self.kernel.calls)

    def test_off_restores_stale_managed_dns_without_marker_or_guard(self):
        self.make_off()
        result, output = self.capture('off')
        self.assertEqual(result,0,output)
        self.assertTrue(self.resolv.is_symlink())
        self.assertEqual(os.readlink(self.resolv),str(self.wsl))

    def test_repeated_off_preserves_user_dns(self):
        self.make_off()
        self.capture('off')
        self.resolv.unlink()
        edited = b'nameserver 9.9.9.9\nsearch my.example\n'
        self.resolv.write_bytes(edited)
        result, output = self.capture('off')
        self.assertEqual(result,0,output)
        self.assertEqual(self.resolv.read_bytes(),edited)
        self.assertFalse(self.resolv.is_symlink())

    def test_route_only_off_cleanup_preserves_nonmanaged_dns(self):
        self.make_off()
        edited = b'nameserver 9.9.9.9\nsearch changed.example\n'
        self.resolv.write_bytes(edited)
        self.kernel.rules4.append({'priority':18402,'table':20260})
        self.kernel.routes4 = [{'dst':'default','dev':'xq-tun'}]
        result, output = self.capture('off')
        self.assertEqual(result,0,output)
        self.assertEqual(self.resolv.read_bytes(),edited)
        self.assertFalse(any(r.get('priority')==18402 for r in self.kernel.rules4))

    def test_off_invalid_restore_retains_running_core_and_guard(self):
        self.state['resolver_before'] = self.file_snapshot(self.managed)
        self.save(self.state)
        self.wsl.write_bytes(self.managed)
        with self.assertRaises(RuntimeError):
            self.capture('off')
        self.assertTrue(self.enabled.exists())
        self.assertTrue(self.kernel.core)
        self.assertTrue(self.kernel.guard)
        self.assertNotIn(('systemctl','stop','xq-proxy.service'),self.kernel.calls)
        self.assertNotIn(('nft','delete','table','inet','xq_proxy'),self.kernel.calls)

    def test_boot_off_does_not_stop_own_unit(self):
        result, output = self.capture('off',from_boot=True)
        self.assertEqual(result,0,output)
        self.assertNotIn(('systemctl','stop','xq-proxy-boot.service'),self.kernel.calls)

    def test_healthy_status_returns_zero_without_mutation(self):
        result, output = self.capture('status')
        self.assertEqual(result,0,output)
        self.assertIn('DNS、路由和恢复备份正常',output)
        self.assertFalse(any('stop' in call or 'delete' in call or call==('install-guard',)
                             for call in self.kernel.calls))

    def test_wrong_dns_status_returns_nonzero(self):
        self.resolv.write_text('nameserver 172.30.255.20\n')
        result, output = self.capture('status')
        self.assertEqual(result,1)
        self.assertIn('DNS 配置',output)
        self.assertIn('ON，但配置异常',output)

    def test_extra_dns_server_status_returns_nonzero(self):
        self.resolv.write_text('nameserver 172.30.255.2\nnameserver 9.9.9.9\n')
        result, output = self.capture('status')
        self.assertEqual(result,1)
        self.assertIn('DNS 配置',output)

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
        result, output = self.capture('status')
        self.assertEqual(result,1)
        self.assertIn('OFF，但存在残留配置',output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
