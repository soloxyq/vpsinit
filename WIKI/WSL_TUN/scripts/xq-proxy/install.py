#!/usr/bin/env python3
"""Install the archived XQ proxy on a fresh WSL2 NAT distribution; starts OFF.

No downloads, proxy traffic, network configuration, or credentials are performed here.
Run with sudo after installing dependencies. --check is read-only.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import grp
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import stat
import subprocess
import tempfile

VERSION = '1.14.4'
SERVICE_USER = 'xq-proxy'
UNITS = ('xq-proxy.service', 'xq-proxy-boot.service')
STATE = Path('/var/lib/xq-proxy')
CONFIG = Path('/etc/xq-proxy')
SOURCE = Path(__file__).resolve().parent
SAFE_PATH = '/usr/sbin:/usr/bin:/sbin:/bin'
PRIORITIES = {18400, 18401, 18402}
SUBNET = ipaddress.ip_network('172.30.255.0/30')
SOURCE_BLOCK = '''\n# XQ WSL TUN controls: loading functions does not enable the proxy.
if [ -r "$HOME/.config/xq/proxy.bash" ]; then
  . "$HOME/.config/xq/proxy.bash"
fi
'''


def command(name, *args, check=True, data=None):
    executable = shutil.which(name, path=SAFE_PATH)
    if not executable:
        raise RuntimeError(f'Missing command: {name}')
    env = os.environ.copy()
    env.update(PATH=SAFE_PATH, LANG='C.UTF-8', LC_ALL='C.UTF-8')
    result = subprocess.run([executable, *args], input=data, text=True,
                            capture_output=True, timeout=30, env=env)
    if check and result.returncode:
        raise RuntimeError(f'{name} {" ".join(args)} failed: {result.stderr.strip()}')
    return result


def lexists(path):
    return os.path.lexists(path)


def target_account():
    username = os.environ.get('SUDO_USER')
    if not username or username == 'root':
        if os.geteuid() != 0:
            username = pwd.getpwuid(os.getuid()).pw_name
        else:
            raise RuntimeError('Run from the intended non-root account with sudo; SUDO_USER is required.')
    account = pwd.getpwnam(username)
    if account.pw_uid == 0 or not account.pw_dir.startswith('/'):
        raise RuntimeError('Target must be a non-root Linux account with an absolute home directory.')
    target_home = Path(account.pw_dir)
    if target_home.is_symlink() or not target_home.is_dir() or target_home.stat().st_uid != account.pw_uid:
        raise RuntimeError('Target home must be a normal directory owned by the target account.')
    return account, target_home


def read_sources():
    result = {}
    for name in ('xq-proxyctl', *UNITS, 'proxy.bash'):
        path = SOURCE / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f'Missing or symlinked companion file: {path}')
        result[name] = path.read_bytes()
    ast.parse(result['xq-proxyctl'].decode(), filename='xq-proxyctl')
    command('bash', '-n', data=result['proxy.bash'].decode())
    boot = result['xq-proxy-boot.service'].decode()
    if ('ExecStart=/usr/local/sbin/xq-proxyctl boot-off' not in boot
            or 'ConditionPathExists=' in boot or '\nRestart=' in boot):
        raise RuntimeError('The archived boot unit is not the expected unconditional startup-OFF version.')
    return result


def preflight():
    if os.geteuid() != 0:
        raise RuntimeError('Use sudo for --check as well, so firewall and routing checks are reliable.')
    account, target_home = target_account()
    release = platform.release().lower()
    if 'microsoft' not in release or 'wsl2' not in release:
        raise RuntimeError('This installer requires standard WSL2; it is not a general VPS installer.')
    if Path('/proc/1/comm').read_text().strip() != 'systemd':
        raise RuntimeError('PID 1 must be systemd. Configure WSL systemd and fully restart the distribution first.')
    required = ('bash', 'python3', 'curl', 'ip', 'nft', 'runuser', 'useradd',
                'systemctl', 'systemd-analyze', 'wslinfo', 'sing-box')
    missing = [name for name in required if not shutil.which(name, path=SAFE_PATH)]
    if missing:
        raise RuntimeError('Install prerequisites first; missing: ' + ', '.join(missing))
    if command('wslinfo', '--networking-mode').stdout.strip().lower() != 'nat':
        raise RuntimeError('This archived controller expects WSL NAT networking, not mirrored networking.')
    tun = Path('/dev/net/tun')
    if not tun.exists() or not stat.S_ISCHR(tun.stat().st_mode):
        raise RuntimeError('/dev/net/tun must be an available character device.')
    if not Path('/usr/bin/sing-box').is_file():
        raise RuntimeError('Install the official package with its binary at /usr/bin/sing-box.')
    version = command('/usr/bin/sing-box', 'version').stdout
    if version.splitlines()[0].strip() != f'sing-box version {VERSION}' or 'with_gvisor' not in version:
        raise RuntimeError(f'This bundle was validated with official sing-box {VERSION} including with_gvisor.')
    sources = read_sources()

    resolver = Path('/etc/resolv.conf')
    resolved_resolver = resolver.resolve(strict=True)
    if not resolved_resolver.is_file():
        raise RuntimeError('The current resolver must resolve to a readable regular file.')
    resolver_data = resolver.read_text()
    servers = []
    for line in resolver_data.splitlines():
        fields = line.split('#', 1)[0].split(';', 1)[0].split()
        if fields and fields[0] == 'nameserver':
            if len(fields) < 2:
                raise RuntimeError('Malformed nameserver entry in the current resolver.')
            address = ipaddress.ip_address(fields[1].split('%', 1)[0])
            if address.is_unspecified or address.is_multicast:
                raise RuntimeError('The current resolver contains an unusable nameserver address.')
            servers.append(address)
    own_dns = ipaddress.ip_address('172.30.255.2')
    if ('# Managed by xq-proxy' in resolver_data
            or any(server == own_dns or getattr(server, 'ipv4_mapped', None) == own_dns for server in servers)):
        raise RuntimeError('Stale XQ TUN DNS found. Restore the original resolver with the previous setup before installing.')
    if not servers:
        raise RuntimeError('The current resolver has no usable nameserver; establish normal OFF DNS first.')

    targets = [Path('/usr/local/sbin/xq-proxyctl'), target_home / '.config/xq/proxy.bash',
               Path('/run/xq-proxy-enabled')]
    for name in (*UNITS, 'xq-proxy-health.service', 'xq-proxy-health.timer'):
        targets.extend((Path('/etc/systemd/system') / name,
                        Path('/etc/systemd/system') / (name + '.d'),
                        Path('/etc/systemd/system/multi-user.target.wants') / name,
                        Path('/etc/systemd/system/timers.target.wants') / name))
    conflicts = [str(p) for p in targets if lexists(p)]
    if conflicts:
        raise RuntimeError('Fresh installation only; existing files must be reviewed manually: ' + ', '.join(conflicts))
    for directory in (CONFIG, STATE):
        if lexists(directory):
            if directory.is_symlink() or not directory.is_dir() or any(directory.iterdir()):
                raise RuntimeError(f'Existing nonempty or unsafe directory: {directory}')
            if directory.stat().st_uid != 0:
                raise RuntimeError(f'System directory must be owned by root: {directory}')
    for directory in (target_home / '.config', target_home / '.config/xq'):
        if lexists(directory) and (directory.is_symlink() or not directory.is_dir()
                                  or directory.stat().st_uid != account.pw_uid):
            raise RuntimeError(f'User configuration directory is not an owned normal directory: {directory}')
    for name, lookup in ((SERVICE_USER, pwd.getpwnam), (SERVICE_USER, grp.getgrnam)):
        try:
            lookup(name)
        except KeyError:
            continue
        raise RuntimeError('An xq-proxy account or group already exists; inspect previous installation before proceeding.')
    for unit in UNITS:
        result = command('systemctl', 'show', unit, '-p', 'LoadState', '--value', check=False)
        if result.stdout.strip() not in ('', 'not-found'):
            raise RuntimeError(f'Existing systemd unit: {unit}')
    if (command('systemctl', 'is-active', '--quiet', 'sing-box.service', check=False).returncode == 0
            or command('systemctl', 'is-enabled', 'sing-box.service', check=False).stdout.strip()
            in ('enabled', 'enabled-runtime', 'linked', 'linked-runtime')):
        raise RuntimeError('The stock sing-box.service is active/enabled. Resolve that separate setup first.')

    nft = json.loads(command('nft', '-j', 'list', 'ruleset').stdout)
    for item in nft.get('nftables', []):
        name = item.get('table', {}).get('name', '')
        if name in ('xq_proxy', 'xq_proxy_validation'):
            raise RuntimeError('Existing XQ firewall state; use its original OFF/recovery procedure first.')
    links = json.loads(command('ip', '-j', 'link', 'show').stdout)
    if any(link.get('ifname') == 'xq-tun' for link in links):
        raise RuntimeError('Existing xq-tun interface; no network changes were made.')
    for family in ('-4', '-6'):
        rules = json.loads(command('ip', '-j', family, 'rule', 'show').stdout)
        if any(rule.get('priority') in PRIORITIES for rule in rules):
            raise RuntimeError('Routing priorities 18400–18402 are already in use.')
        routes = command('ip', family, 'route', 'show', 'table', '20260', check=False)
        if routes.stdout.strip():
            raise RuntimeError('Routing table 20260 is already in use.')
    routes = json.loads(command('ip', '-j', '-4', 'route', 'show', 'table', 'main').stdout)
    defaults = [r for r in routes if r.get('dst') == 'default' and r.get('gateway') and r.get('dev')]
    if not defaults:
        raise RuntimeError('No physical IPv4 default gateway was found.')
    selected = min(defaults, key=lambda route: route.get('metric', 0))
    gateway = str(ipaddress.IPv4Address(selected['gateway']))
    interface = selected['dev']
    info = json.loads(command('ip', '-j', 'link', 'show', 'dev', interface).stdout)
    if not info or 'UP' not in info[0].get('flags', []) or info[0].get('mtu', 0) < 1280:
        raise RuntimeError('The physical default-route interface must be UP with MTU at least 1280.')
    for route in routes:
        destination = route.get('dst', 'default')
        if destination != 'default' and ipaddress.ip_network(destination, strict=False).overlaps(SUBNET):
            raise RuntimeError('The reserved TUN subnet 172.30.255.0/30 overlaps an existing route.')

    # Kernel validation only: --check never installs this deliberately separate table.
    probe_table = f'xq_install_probe_{os.getpid()}'
    guard_probe = f'''table inet {probe_table} {{
      chain output {{
        type filter hook output priority -10; policy drop;
        meta l4proto {{ tcp, udp }} th dport 53 oifname != "xq-tun" counter reject with icmpx type admin-prohibited
        oifname "lo" counter accept
        meta nfproto ipv4 oifname "xq-tun" counter accept
        meta skuid 0 ip daddr {gateway} tcp dport 4066 counter accept
        meta skuid 0 ip daddr {gateway} meta l4proto udp counter accept
        counter reject with icmpx type admin-prohibited
      }}
      chain forward {{
        type filter hook forward priority -10; policy drop;
        meta nfproto ipv4 oifname "xq-tun" counter accept
        meta nfproto ipv4 iifname "xq-tun" ct state established,related counter accept
        counter reject with icmpx type admin-prohibited
      }}
    }}\n'''
    command('nft', '--check', '-f', '-', data=guard_probe)

    bashrc = target_home / '.bashrc'
    if lexists(bashrc) and (bashrc.is_symlink() or not bashrc.is_file()
                           or bashrc.stat().st_uid != account.pw_uid):
        raise RuntimeError('Existing .bashrc must be a normal file owned by the target account; merge symlinked dotfiles manually.')
    original = bashrc.read_bytes() if bashrc.exists() else b''
    if re.search(rb'xq_proxy(?:on|off|status)|_xq_proxy|xq-proxyctl|\.config/xq/proxy\.bash', original):
        raise RuntimeError('Existing XQ function or loader found in .bashrc; do not append a second implementation.')
    updated = original + SOURCE_BLOCK.encode()
    command('bash', '-n', data=updated.decode())
    return account, target_home, sources, original, updated


def atomic_write(path, data, mode, uid=0, gid=0):
    descriptor, temp = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp, mode)
        os.chown(temp, uid, gid)
        os.replace(temp, path)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def install(account, target_home, sources, original, updated):
    backup = Path(tempfile.mkdtemp(prefix='xq-proxy-before-install-', dir='/var/backups'))
    backup.chmod(0o700)
    bashrc = target_home / '.bashrc'
    bash_mode = stat.S_IMODE(bashrc.stat().st_mode) if bashrc.exists() else 0o644
    record = {'user': account.pw_name, 'home': str(target_home),
              'bashrc_existed': bashrc.exists(), 'bashrc_mode': bash_mode,
              'created_files': [], 'created_directories': [], 'created_user': False,
              'boot_unit_enabled': False, 'bashrc_updated': False,
              'source_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}}
    atomic_write(backup / 'bashrc', original, 0o600)

    def save_record():
        atomic_write(backup / 'installation.json', (json.dumps(record, indent=2) + '\n').encode(), 0o600)

    def directory(path, mode, uid=0, gid=0):
        if not path.exists():
            path.mkdir(mode=mode)
            os.chown(path, uid, gid)
            record['created_directories'].append(str(path))
            save_record()

    try:
        save_record()
        command('useradd', '--system', '--user-group', '--no-create-home', '--home-dir',
                '/nonexistent', '--shell', '/usr/sbin/nologin', SERVICE_USER)
        record['created_user'] = True
        save_record()
        directory(CONFIG, 0o755)
        directory(STATE, 0o700)
        CONFIG.chmod(0o755)
        STATE.chmod(0o700)
        for name, destination, mode in (
                ('xq-proxyctl', Path('/usr/local/sbin/xq-proxyctl'), 0o755),
                *((name, Path('/etc/systemd/system') / name, 0o644) for name in UNITS)):
            atomic_write(destination, sources[name], mode)
            record['created_files'].append(str(destination))
            save_record()
        command('systemd-analyze', 'verify', *(str(Path('/etc/systemd/system') / name) for name in UNITS))
        directory(target_home / '.config', 0o755, account.pw_uid, account.pw_gid)
        directory(target_home / '.config/xq', 0o755, account.pw_uid, account.pw_gid)
        library = target_home / '.config/xq/proxy.bash'
        atomic_write(library, sources['proxy.bash'], 0o644, account.pw_uid, account.pw_gid)
        record['created_files'].append(str(library))
        save_record()
        # Refuse to replace a concurrently changed user file.
        if (bashrc.read_bytes() if bashrc.exists() else b'') != original or bashrc.is_symlink():
            raise RuntimeError('.bashrc changed during installation; no replacement performed.')
        atomic_write(bashrc, updated, bash_mode, account.pw_uid, account.pw_gid)
        record['bashrc_updated'] = True
        save_record()
        command('bash', '-n', str(bashrc))
        command('systemctl', 'daemon-reload')
        # Enable only the one-time OFF reset. No --now: installation never changes networking.
        command('systemctl', 'enable', 'xq-proxy-boot.service')
        record['boot_unit_enabled'] = True
        save_record()
        if command('systemctl', 'is-enabled', 'xq-proxy.service', check=False).stdout.strip() != 'disabled':
            raise RuntimeError('Unexpected core autostart state; inspect systemd before using the switch.')
        print(f'Installed for {account.pw_name}. Backup and manifest: {backup}')
        print('Current mode: OFF. No TUN was started; DNS, routes and firewall were not changed.')
        print('Open a new Bash terminal, or run: source ~/.bashrc')
        print('Then use xq_proxystatus; run xq_proxyon only when ready to enable all-WSL routing.')
        print('Recovery entry: sudo /usr/local/sbin/xq-proxyctl off')
    except Exception:
        save_record()
        print(f'Installation stopped. No ON command was run. Inspect partial-file manifest: {backup}/installation.json', file=sys.stderr)
        print('The original .bashrc is backed up there. Review partial files before retrying; this is a fresh-install-only helper.', file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='read-only prerequisite and conflict checks; no installation')
    args = parser.parse_args()
    account, target_home, sources, original, updated = preflight()
    print(f'Preflight PASS: WSL2 NAT, systemd, TUN, sing-box {VERSION}, no XQ conflicts.')
    print(f'Machine architecture: {platform.machine()}')
    print(f'Target account: {account.pw_name}; home: {target_home}')
    if args.check:
        print('Read-only check complete. Karing reachability is checked separately in the guide.')
        return
    install(account, target_home, sources, original, updated)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
