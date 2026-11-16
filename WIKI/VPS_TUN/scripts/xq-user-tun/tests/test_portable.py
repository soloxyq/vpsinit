#!/usr/bin/python3 -I
"""Offline regression checks for identity selection and configuration scope."""
import ast
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
BUILD = BASE.parent / 'build-xq-user-tun.py'       # in the WIKI checkout, not in the bundle
GUIDE = BASE.parent.parent / 'VPS-用户级TUN一键部署.md'  # shipped as DEPLOYMENT.md
LEGACY_PORT = str(1000 + 53)                       # the unprivileged entry used until 2026-11-15


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
                         ('127.0.0.1', str(controller.DNS_PORT)), ('203.0.113.25', '0'),
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
            self.assertIn(f'meta skuid {uid} ip daddr != @lan_v4 fib daddr type local', rules)
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

    def test_core_unit_may_bind_the_privileged_dns_port(self):
        unit = (BASE / 'xq-user-proxy.service').read_text()
        options = dict(line.split('=', 1) for line in unit.splitlines()
                       if '=' in line and not line.startswith('#'))
        self.assertEqual(options['CapabilityBoundingSet'].split(),
                         ['CAP_NET_ADMIN', 'CAP_NET_RAW', 'CAP_NET_BIND_SERVICE'])
        self.assertLess(controller.DNS_PORT, 1024)
        # The rules let exactly the unit's user answer from that port.
        self.assertEqual((options['User'], controller.CORE_UID), ('root', 0))

    def test_installer_and_controller_agree_on_dns_port_and_classifier(self):
        shipped = installer.package_controller()
        self.assertEqual(shipped.__spec__.origin, str(BASE / 'xq-user-proxyctl'))
        self.assertEqual(shipped.DNS_PORT, controller.DNS_PORT)
        template = json.loads((BASE / 'sing-box.template.json').read_text())
        self.assertEqual([item['listen_port'] for item in template['inbounds'] if item['tag'] == 'uid-dns'],
                         [controller.DNS_PORT])
        installer.render(self.directory, self.settings)
        rendered = json.loads((self.directory / 'sing-box.json').read_text())
        self.assertIn({'type': 'direct', 'tag': 'uid-dns', 'listen': '127.0.0.1',
                       'listen_port': controller.DNS_PORT}, rendered['inbounds'])
        # The installer keeps no port or classification of its own.
        source = (BASE / 'install.py').read_text()
        for name in ('DNS_PORT =', 'def nameserver_path', 'def resolver_report', 'def endpoint_fault', 'LAN_V4'):
            self.assertNotIn(name, source)
        resolver = self.directory / 'resolv.conf'
        resolver.write_text('nameserver 127.0.0.53\nnameserver 192.168.1.1\nnameserver ::1\nnameserver 9.9.9.9\n')
        with patch.object(shipped, 'RESOLV', resolver), patch.object(controller, 'RESOLV', resolver):
            self.assertEqual(shipped.resolver_paths(), controller.resolver_paths())
            self.assertEqual([kind for _, kind, _ in shipped.resolver_paths()],
                             ['proxied', 'lan', 'blocked', 'unused'])

    def test_render_rejects_a_template_whose_dns_port_differs_from_the_controller(self):
        package = self.directory / 'package'
        package.mkdir()
        for name in ('xq-user-proxyctl', 'xq-user-proxy.bash', 'xq-user-proxy.service', 'sing-box.template.json'):
            shutil.copyfile(BASE / name, package / name)
        template = package / 'sing-box.template.json'
        template.write_text(template.read_text().replace(f'"listen_port": {controller.DNS_PORT}',
                                                         f'"listen_port": {controller.DNS_PORT + 1}'))
        target = self.directory / 'rendered'
        target.mkdir()
        with patch.object(installer, 'SOURCE', package), self.assertRaisesRegex(RuntimeError, '专用 DNS 入口'):
            installer.render(target, self.settings)

    def test_installer_refuses_unusable_dns_host_before_touching_the_system(self):
        shipped = installer.package_controller()
        resolver, sysctl = self.directory / 'resolv.conf', self.directory / 'sysctl'
        (sysctl / 'ipv4').mkdir(parents=True)
        threshold = sysctl / 'ipv4/ip_unprivileged_port_start'
        arguments = SimpleNamespace(no_start=True, archive=None)
        cases = [('nameserver ::1\nnameserver 2001:4860:4860::8888\n', 1024, ('::1', '2001:4860:4860::8888', '阻断')),
                 ('nameserver 9.9.9.9\n', controller.DNS_PORT, ('ip_unprivileged_port_start', '普通用户')),
                 ('nameserver 9.9.9.9\n', 0, ('ip_unprivileged_port_start', '普通用户'))]
        for text, start, words in cases:
            resolver.write_text(text)
            threshold.write_text(f'{start}\n')
            with self.subTest(resolver=text, start=start), \
                    patch.object(shipped, 'RESOLV', resolver), patch.object(shipped, 'SYSCTL', sysctl), \
                    patch.object(installer, 'host_preflight'), \
                    patch.object(installer, 'destinations_clear', side_effect=AssertionError('Reached the system')), \
                    patch.object(installer, 'run', side_effect=AssertionError('Must not spawn a command')):
                with self.assertRaises(RuntimeError) as caught:
                    installer.install(arguments, self.settings)
                for word in (*words, '尚未写入'):
                    self.assertIn(word, str(caught.exception))
        # A LAN resolver stays allowed: direct by policy, announced as not proxied.
        resolver.write_text('nameserver 192.168.1.1\n')
        threshold.write_text('1024\n')
        output = io.StringIO()
        with patch.object(shipped, 'RESOLV', resolver), patch.object(shipped, 'SYSCTL', sysctl), \
                contextlib.redirect_stdout(output):
            installer.dns_preflight()
        self.assertIn('警告', output.getvalue())
        self.assertIn('192.168.1.1', output.getvalue())
        self.assertIn('不经代理', output.getvalue())

    def test_no_file_of_the_package_mentions_the_old_unprivileged_dns_port(self):
        files = [path for path in BASE.rglob('*') if path.is_file() and '__pycache__' not in path.parts]
        if GUIDE.is_file():
            files.append(GUIDE)
        self.assertGreater(len(files), 8)
        for path in files:
            with self.subTest(file=path.name):
                self.assertEqual([line.strip() for line in path.read_text(errors='replace').splitlines()
                                  if LEGACY_PORT in line], [])

    def test_documented_rootless_command_names_the_callers_network_namespace(self):
        # A shell expands "$HOSTNS" before an assignment written on the same command takes effect.
        stub = self.directory / 'unshare'
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        stub.chmod(0o755)
        documents = {'README.md': (BASE / 'README.md').read_text(),
                     'tests/netns-check.py': ast.get_docstring(ast.parse((BASE / 'tests/netns-check.py').read_text()))}
        for name, text in documents.items():
            with self.subTest(document=name):
                blocks = [block for block in text.split('\n\n') if 'XQ_HOST_NETNS=' in block]
                self.assertEqual(len(blocks), 1)
                script = '\n'.join(line for line in blocks[0].splitlines() if not line.startswith('```'))
                shown = subprocess.run(['/bin/sh', '-c', script], cwd=self.directory, check=True, text=True,
                                       capture_output=True, env={'PATH': f'{self.directory}:/usr/bin:/bin'}).stdout
                self.assertIn('XQ_HOST_NETNS=' + os.readlink('/proc/self/ns/net'), shown.splitlines())

    @unittest.skipUnless(BUILD.is_file(), 'the build script exists only in the WIKI checkout')
    def test_bundle_list_names_every_file_of_the_package(self):
        build = module('portable_build', BUILD)
        present = {str(path.relative_to(BASE)) for path in BASE.rglob('*')
                   if path.is_file() and '__pycache__' not in path.parts}
        self.assertEqual(set(build.FILES), present)
        self.assertIn('tests/test_lifecycle.py', build.FILES)


if __name__ == '__main__':
    unittest.main(verbosity=2)
