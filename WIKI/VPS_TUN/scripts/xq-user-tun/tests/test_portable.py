#!/usr/bin/python3 -I
"""Offline regression checks for identity selection and configuration scope."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]


def module(name, filename):
    loader = importlib.machinery.SourceFileLoader(name, str(BASE / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


installer = module('portable_installer', 'install.py')
controller = module('portable_controller', 'xq-user-proxyctl')


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xq-portable-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.account = SimpleNamespace(pw_name='alice', pw_uid=23456,
                                       pw_gid=23457, pw_dir=str(self.directory))
        self.settings = dict(schema=1, user='alice', uid=23456, gid=23457,
                             proxy_ip='203.0.113.25', proxy_port=1080)

    def test_identity_from_sudo_not_root_or_environment_username(self):
        with patch.object(installer.os, 'getuid', return_value=0), \
                patch.object(installer.os, 'geteuid', return_value=0), \
                patch.dict(installer.os.environ, {'SUDO_UID': '23456', 'USER': 'root'}, clear=True), \
                patch.object(installer.pwd, 'getpwuid', return_value=self.account) as lookup:
            self.assertEqual(installer.account_for(SimpleNamespace(user=None)), self.account)
            lookup.assert_called_once_with(23456)

    def test_plain_root_needs_explicit_nonroot_user(self):
        with patch.object(installer.os, 'getuid', return_value=0), \
                patch.object(installer.os, 'geteuid', return_value=0), \
                patch.dict(installer.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, '纯 root'):
                installer.account_for(SimpleNamespace(user=None))
            with patch.object(installer.pwd, 'getpwnam', return_value=self.account):
                self.assertEqual(installer.account_for(SimpleNamespace(user='alice')), self.account)
            with patch.object(installer.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=0, pw_gid=0)):
                with self.assertRaisesRegex(RuntimeError, '非 root'):
                    installer.account_for(SimpleNamespace(user='root'))

    def test_normal_caller_cannot_select_another_uid(self):
        with patch.object(installer.os, 'getuid', return_value=2000), \
                patch.object(installer.os, 'geteuid', return_value=2000), \
                patch.dict(installer.os.environ, {'SUDO_UID': '0'}, clear=True), \
                patch.object(installer.pwd, 'getpwnam', return_value=self.account):
            with self.assertRaisesRegex(RuntimeError, '调用者自身'):
                installer.account_for(SimpleNamespace(user='alice'))

    def test_bad_proxy_rejected_before_sudo_or_network(self):
        for ip, port in [('host.example', '1080'), ('::1', '1080'),
                         ('0.0.0.0', '1080'), ('224.0.0.1', '1080'),
                         ('127.0.0.1', '1053'), ('203.0.113.25', '0'),
                         ('203.0.113.25', '65536'), ('172.30.254.1', '1080')]:
            with self.subTest(ip=ip, port=port), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    installer.parse_args(['--proxy-ip', ip, '--proxy-port', port])

    def test_rendered_config_and_runtime_agree_for_different_users(self):
        for uid, username, ip in [(23456, 'alice', '203.0.113.25'),
                                  (34567, 'bob', '198.51.100.10')]:
            settings = dict(self.settings, uid=uid, user=username, proxy_ip=ip)
            folder = self.directory / username
            folder.mkdir()
            installer.render(folder, settings)
            account = SimpleNamespace(pw_uid=uid, pw_gid=settings['gid'])
            with patch.object(controller, 'SETTINGS', folder / 'settings.json'), \
                    patch.object(controller, 'CONFIG', folder / 'sing-box.json'), \
                    patch.object(controller, 'trusted'), \
                    patch.object(controller.pwd, 'getpwnam', return_value=account):
                controller.load_settings()
                controller.check_config()
                rules = controller.firewall()
            self.assertIn(f'meta skuid {uid} ', rules)
            self.assertIn(f'meta skuid {uid} meta nfproto ipv4 ip daddr != @lan_v4', rules)
            self.assertEqual(rules.count(f'ct zone set {controller.DNS_ZONE}'), 4)
            self.assertNotIn('1006', rules)
            self.assertNotIn('16791', rules)
            text = (folder / 'xq-user-proxy.bash').read_text()
            self.assertNotIn('@UID@', text)
            self.assertNotIn('@USER@', text)
            # The real invoking user is neither synthetic owner: helper must
            # refuse before invoking sudo, even if loaded into another shell.
            result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                                     'source "$1"; xq_proxyon', '_', str(folder / 'xq-user-proxy.bash')],
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertIn('仅允许', result.stderr)

    def test_runtime_rejects_identity_or_scope_drift(self):
        installer.render(self.directory, self.settings)
        with patch.object(controller, 'SETTINGS', self.directory / 'settings.json'), \
                patch.object(controller, 'CONFIG', self.directory / 'sing-box.json'), \
                patch.object(controller, 'trusted'), \
                patch.object(controller.pwd, 'getpwnam', return_value=self.account):
            controller.load_settings()
            original = json.loads((self.directory / 'sing-box.json').read_text())
            for mutation in ('global-route', 'extra-listener', 'direct-outbound', 'wrong-proxy'):
                config = json.loads(json.dumps(original))
                if mutation == 'global-route': config['inbounds'][0]['auto_route'] = True
                elif mutation == 'extra-listener': config['inbounds'].append({'type': 'mixed'})
                elif mutation == 'direct-outbound': config['outbounds'].append({'type': 'direct'})
                else: config['outbounds'][0]['server_port'] = 1081
                (self.directory / 'sing-box.json').write_text(json.dumps(config))
                with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                    controller.check_config()
            wrong_uid = dict(self.settings, uid=22222)
            (self.directory / 'settings.json').write_text(json.dumps(wrong_uid))
            with self.assertRaisesRegex(RuntimeError, 'UID/GID'):
                controller.load_settings()

    def test_existing_destination_rejected_before_any_subprocess(self):
        existing = self.directory / 'existing-installation'
        existing.mkdir()
        with patch.object(installer, 'DESTINATIONS', (existing,)), \
                patch.object(installer, 'run', side_effect=AssertionError('Must not spawn a command')):
            with self.assertRaisesRegex(RuntimeError, '拒绝覆盖'):
                installer.destinations_clear()

    def test_missing_unit_is_distinct_from_systemd_failure(self):
        absent = 'LoadState=not-found\nFragmentPath=\nDropInPaths=\n'
        cases = [(absent, '', code, True) for code in (0, 1, 4)] + [
            ('', 'Failed to connect to bus', 1, False),
            ('FragmentPath=\nDropInPaths=\n', '', 0, False),
            ('LoadState=loaded\nFragmentPath=/etc/unit\nDropInPaths=\n', '', 0, False),
            (absent.replace('DropInPaths=', 'DropInPaths=/etc/override.conf'), '', 0, False),
        ]
        with patch.object(installer, 'DESTINATIONS', ()), patch.object(installer, 'trusted_parents'):
            for output, error, code, accepted in cases:
                result = SimpleNamespace(stdout=output, stderr=error, returncode=code)
                with self.subTest(output=output, code=code), patch.object(installer, 'run', return_value=result):
                    if accepted:
                        installer.destinations_clear()
                    else:
                        with self.assertRaises(RuntimeError): installer.destinations_clear()


if __name__ == '__main__':
    unittest.main(verbosity=2)
