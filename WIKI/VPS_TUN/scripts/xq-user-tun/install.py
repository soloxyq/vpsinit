#!/usr/bin/python3 -I
"""Fresh, single-owner installation. Never update a live or previous installation."""
import argparse
import ast
import fcntl
import hashlib
import importlib.machinery
import importlib.util
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
import sys
import tarfile
import tempfile
import time

VERSION = '1.14.4'
# Official immutable asset digests, checked 2026-11-14:
# https://github.com/SagerNet/sing-box/releases/expanded_assets/v1.14.4
ARCHIVES = {
    'x86_64': ('amd64', '699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968'),
    'aarch64': ('arm64', '436441f76ee2f7fe21b5b2d426d3cb261a480455a704865789ad533e4273ec26'),
}
SOURCE = Path(__file__).resolve().parent
SERVICE = 'xq-user-proxy.service'
CONTROLLER = Path('/usr/local/sbin/xq-user-proxyctl')
CONFIG_DIR = Path('/etc/xq-user-proxy')
LIB_DIR = Path('/usr/local/lib/xq-user-proxy')
SHARE_DIR = Path('/usr/local/share/xq-user-proxy')
VAR_DIR = Path('/var/lib/xq-user-proxy')
UNIT = Path('/etc/systemd/system') / SERVICE
BINARY = LIB_DIR / 'bin/sing-box'
HELPER = SHARE_DIR / 'xq-user-proxy.bash'
DESTINATIONS = (CONFIG_DIR, LIB_DIR, SHARE_DIR, VAR_DIR, CONTROLLER, UNIT,
                Path(str(UNIT) + '.d'), Path('/run/xq-user-proxy'))
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
       'HOME': '/root', 'NEEDRESTART_MODE': 'l', 'DEBIAN_FRONTEND': 'noninteractive'}


def run(args, *, capture=False, check=True, timeout=60, data=None):
    result = subprocess.run([str(a) for a in args], env=ENV, check=False,
                            text=True, input=data, capture_output=capture,
                            timeout=timeout, close_fds=True)
    if check and result.returncode:
        detail = (result.stderr or '').strip() if capture else ''
        raise RuntimeError('命令失败：' + ' '.join(map(str, args)) + ('\n' + detail if detail else ''))
    return result


def parse_args(argv):
    parser = argparse.ArgumentParser(description='为当前非 root 用户安装用户级 TUN；只支持首次安装。')
    parser.add_argument('--proxy-ip', help='可达的 SOCKS5 IPv4 地址（无认证）')
    parser.add_argument('--proxy-port', type=int, help='SOCKS5 端口，1–65535')
    parser.add_argument('--user', help='目标用户；通常自动识别当前用户，纯 root 登录必须指定')
    parser.add_argument('--no-start', action='store_true', help='安装后保持 OFF，不改变当前网络')
    parser.add_argument('--archive', type=Path, help='已下载的官方 sing-box 1.14.4 Linux tar.gz；仍校验 SHA256')
    parser.add_argument('--render-dir', type=Path, help='只在一个新目录渲染文件，不提权、不联网、不安装')
    args = parser.parse_args(argv)
    if args.proxy_ip is None:
        if not sys.stdin.isatty(): parser.error('非交互运行必须提供 --proxy-ip')
        args.proxy_ip = input('代理 IPv4 地址：').strip()
    if args.proxy_port is None:
        if not sys.stdin.isatty(): parser.error('非交互运行必须提供 --proxy-port')
        try: args.proxy_port = int(input('代理端口：').strip())
        except ValueError: parser.error('端口必须是整数')
    try:
        host = ipaddress.IPv4Address(args.proxy_ip)
        if host.is_unspecified or host.is_multicast or str(host) == '255.255.255.255':
            raise ValueError('不是单播目标')
        args.proxy_ip = str(host)
    except ValueError:
        parser.error('--proxy-ip 必须是可用的 IPv4 单播地址，不接受域名、IPv6 或 URL')
    if not 1 <= args.proxy_port <= 65535: parser.error('--proxy-port 必须在 1–65535 之间')
    if args.proxy_ip == '127.0.0.1' and args.proxy_port == 1053:
        parser.error('代理不能占用专用 DNS 入口 127.0.0.1:1053')
    if args.proxy_ip == '172.30.254.1':
        parser.error('代理 IP 与本方案专用 TUN 地址 172.30.254.1 冲突')
    return args


def account_for(args):
    caller = os.getuid()
    if os.geteuid() == 0 and 'SUDO_UID' in os.environ:
        caller = int(os.environ['SUDO_UID'])
    if not args.user and caller == 0:
        raise RuntimeError('纯 root 登录不能自动选择用户；请加 --user 已存在的普通用户名')
    account = pwd.getpwnam(args.user) if args.user else pwd.getpwuid(caller)
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise RuntimeError('目标必须是非 root UID 且非 root 主组的普通用户')
    if caller != 0 and caller != account.pw_uid:
        raise RuntimeError('sudo/普通用户运行时只能为调用者自身安装；请从目标用户会话执行')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*\$?', account.pw_name):
        raise RuntimeError('用户名包含此安装器不支持的字符')
    if not Path(account.pw_dir).is_absolute() or not Path(account.pw_dir).is_dir():
        raise RuntimeError('目标用户必须有现存的绝对路径 home 目录')
    return account


def settings_for(args, account):
    return dict(schema=1, user=account.pw_name, uid=account.pw_uid, gid=account.pw_gid,
                proxy_ip=args.proxy_ip, proxy_port=args.proxy_port)


def render(directory, settings):
    """Render data using JSON, not shell interpolation or sourced settings."""
    files = {}
    for name in ('xq-user-proxyctl', 'xq-user-proxy.bash', 'xq-user-proxy.service', 'sing-box.template.json'):
        source = SOURCE / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError('缺少完整安装目录或源文件是符号链接：' + str(source))
        files[name] = source.read_text()
    ast.parse(files['xq-user-proxyctl'])
    config = json.loads(files.pop('sing-box.template.json'))
    upstream = [x for x in config['outbounds'] if x.get('tag') == 'upstream']
    if len(upstream) != 1 or upstream[0].get('type') != 'socks':
        raise RuntimeError('模板上游异常')
    upstream[0]['server'], upstream[0]['server_port'] = settings['proxy_ip'], settings['proxy_port']
    files['sing-box.json'] = json.dumps(config, indent=2) + '\n'
    files['settings.json'] = json.dumps(settings, indent=2) + '\n'
    for name in ('xq-user-proxy.bash', 'xq-user-proxy.service'):
        files[name] = files[name].replace('@USER@', settings['user']).replace('@UID@', str(settings['uid']))
    for name, content in files.items():
        with (directory / name).open('x') as stream: stream.write(content)
        (directory / name).chmod(0o600)
    run(['/bin/bash', '-n', directory / 'xq-user-proxy.bash'], capture=True)
    return files


def trusted_parents(path):
    """Never install through a symlink or a non-root-writable ancestor."""
    for parent in (path, *path.parents):
        if not os.path.lexists(parent): continue
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_mode & 0o022:
            raise RuntimeError('不安全的安装路径：' + str(parent))


def destinations_clear():
    # Check before apt, downloads, locking, or writing any installation object.
    for target in DESTINATIONS:
        if os.path.lexists(target):
            raise RuntimeError('检测到已有安装或冲突，拒绝覆盖：' + str(target)
                               + '；此脚本只用于新 VPS 的首次安装')
        trusted_parents(target.parent)
    for directory in (Path('/run'), Path('/var/backups')):
        trusted_parents(directory)
    result = run(['/usr/bin/systemctl', 'show', SERVICE,
                  '--property=LoadState,FragmentPath,DropInPaths'], capture=True, check=False)
    properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    # Some systemd versions use a nonzero status for not-found. Accept only
    # complete, explicit not-found metadata; never equate a bus error with an
    # absent unit. Empty/missing output or stderr remains a hard failure.
    if (properties != {'LoadState': 'not-found', 'FragmentPath': '', 'DropInPaths': ''}
            or result.stderr.strip()):
        raise RuntimeError('同名 systemd unit/drop-in 已存在，或无法确认 unit 不存在；拒绝覆盖：'
                           + (result.stderr.strip() or str(properties)))


def host_preflight():
    if sys.version_info < (3, 9): raise RuntimeError('需要 Python 3.9 或以上版本')
    if platform.system() != 'Linux' or platform.machine() not in ARCHIVES:
        raise RuntimeError('仅支持 Linux x86_64/aarch64')
    release = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            release[key] = value.strip('"')
    distro, version = release.get('ID'), release.get('VERSION_ID', '0')
    if not ((distro == 'debian' and int(version.split('.')[0]) >= 12)
            or (distro == 'ubuntu' and tuple(map(int, version.split('.')[:2])) >= (22, 4))):
        raise RuntimeError('自动安装仅支持 Debian 12+ / Ubuntu 22.04+')
    if Path('/proc/1/comm').read_text().strip() != 'systemd':
        raise RuntimeError('需要运行中的宿主 systemd')
    here, host = os.stat('/proc/self/ns/net'), os.stat('/proc/1/ns/net')
    if (here.st_dev, here.st_ino) != (host.st_dev, host.st_ino):
        raise RuntimeError('请从宿主网络命名空间执行安装')
    tun = Path('/dev/net/tun')
    if not tun.exists() or not stat.S_ISCHR(tun.stat().st_mode):
        raise RuntimeError('/dev/net/tun 不可用；请先在 VPS 管理平台开启 TUN')


def ensure_dependencies():
    commands = {'/usr/sbin/ip': 'iproute2', '/usr/sbin/nft': 'nftables',
                '/usr/sbin/conntrack': 'conntrack', '/usr/bin/curl': 'curl',
                '/usr/bin/setpriv': 'util-linux', '/usr/bin/unshare': 'util-linux',
                '/usr/bin/sudo': 'sudo', '/usr/sbin/iptables-legacy-save': 'iptables',
                '/usr/sbin/ip6tables-legacy-save': 'iptables'}
    packages = {pkg for cmd, pkg in commands.items() if not os.access(cmd, os.X_OK)}
    if not Path('/etc/ssl/certs/ca-certificates.crt').is_file(): packages.add('ca-certificates')
    if packages:
        print('安装缺少的系统依赖：' + ' '.join(sorted(packages)), flush=True)
        run(['/usr/bin/apt-get', 'update'], timeout=600)
        run(['/usr/bin/apt-get', 'install', '-y', '--no-upgrade', '--no-install-recommends', *sorted(packages)], timeout=600)
    for command in (*commands, '/usr/bin/systemd-analyze'):
        if not os.access(command, os.X_OK): raise RuntimeError('依赖不可用：' + command)


def check_legacy_firewall(*, require_all=True):
    # nft cannot see legacy xtables rules. Conservatively refuse any custom
    # rules or non-ACCEPT policies, including MARK/CONNMARK in either family.
    for tool in ('/usr/sbin/iptables-legacy-save', '/usr/sbin/ip6tables-legacy-save'):
        if not os.access(tool, os.X_OK):
            if require_all:
                raise RuntimeError('缺少 legacy 防火墙核验工具：' + tool)
            continue
        saved = run([tool], capture=True).stdout
        for line in saved.splitlines():
            line = line.strip()
            if (line.startswith('-') or
                    (line.startswith(':') and line.split()[1] != 'ACCEPT')):
                raise RuntimeError('检测到 iptables-legacy 自定义规则/策略；请先人工核对，不自动改动：' + tool)


def curl_options(settings):
    return ['/usr/bin/curl', '--disable', '--fail', '--show-error', '--silent',
            '--proto', '=https', '--proto-redir', '=https',
            '--connect-timeout', '10', '--max-time', '45',
            '--proxy', f'socks5h://{settings["proxy_ip"]}:{settings["proxy_port"]}', '--noproxy', '']


def proxy_probe(settings):
    print('检查 SOCKS5 上游和经代理的 HTTPS...', flush=True)
    run([*curl_options(settings), '--output', '/dev/null', 'https://example.com/'], timeout=60)


def obtain_binary(args, settings, stage):
    arch, digest = ARCHIVES[platform.machine()]
    asset = f'sing-box-{VERSION}-linux-{arch}.tar.gz'
    archive = stage / asset
    if args.archive:
        # Snapshot before verifying. Do not trust a mutable archive after hashing.
        with args.archive.open('rb') as src, archive.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    else:
        print('下载并校验官方 ' + asset + '...', flush=True)
        run([*curl_options(settings), '--max-time', '300', '--retry', '2', '--location',
             '--output', archive, f'https://github.com/SagerNet/sing-box/releases/download/v{VERSION}/{asset}'],
            timeout=660)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise RuntimeError('sing-box 安装包 SHA256 不匹配；拒绝执行')
    member_name = f'sing-box-{VERSION}-linux-{arch}/sing-box'
    target = stage / 'sing-box'
    with tarfile.open(archive, 'r:gz') as package:
        member = package.getmember(member_name)
        if not member.isfile() or member.size > 250_000_000:
            raise RuntimeError('安装包中的 sing-box 不是预期普通文件')
        with package.extractfile(member) as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    target.chmod(0o700)
    run([target, 'check', '-c', stage / 'sing-box.json'])
    return target


def load_controller(path):
    loader = importlib.machinery.SourceFileLoader('xq_user_tun_installer_controller', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_new(path, content, mode):
    with path.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(mode)


# Executed only after dropping UID, GID, groups and capabilities. No privileged
# process follows user-controlled ~/.bashrc or home symlinks to write files.
SHELL_SETUP = r'''
import os, pathlib, pwd, shutil, stat, tempfile, time
home = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
path = home / '.bashrc'
begin, end = '# >>> xq-user-tun >>>', '# <<< xq-user-tun <<<'
block = begin + '\nsource /usr/local/share/xq-user-proxy/xq-user-proxy.bash\n' + end + '\n'
if path.is_symlink(): raise SystemExit('拒绝修改符号链接 ~/.bashrc；请手动 source helper')
old = path.read_text() if path.exists() else ''
if begin in old or end in old: raise SystemExit('~/.bashrc 已存在 xq-user-tun 标记；请人工核对')
if path.exists():
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise SystemExit('~/.bashrc 不是当前用户拥有的普通文件')
    backup = home / ('.bashrc.before-xq-user-tun-' + str(time.time_ns()))
    with backup.open('x') as stream: stream.write(old)
    backup.chmod(stat.S_IMODE(info.st_mode))
    print('Bash 备份：' + str(backup))
fd, temp = tempfile.mkstemp(prefix='.bashrc.xq-', dir=home)
try:
    with os.fdopen(fd, 'w') as stream: stream.write(old.rstrip('\n') + '\n\n' + block)
    os.chmod(temp, stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644)
    os.replace(temp, path)
finally:
    if os.path.exists(temp): os.unlink(temp)
'''


def as_owner(settings, command, **kwargs):
    return run(['/usr/bin/setpriv', f'--reuid={settings["uid"]}', f'--regid={settings["gid"]}',
                '--clear-groups', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all',
                '--no-new-privs', '--', *command], **kwargs)


def install(args, settings):
    host_preflight()
    destinations_clear()
    # A shared installer lock is itself checked before opening it as root.
    lockpath = Path('/run/xq-user-proxy-install.lock')
    lock = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    info = os.fstat(lock)
    if not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_mode & 0o022:
        os.close(lock)
        raise RuntimeError('不安全的安装锁')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        destinations_clear()
        check_legacy_firewall(require_all=False)
        ensure_dependencies()
        check_legacy_firewall()
        proxy_probe(settings)
        with tempfile.TemporaryDirectory(prefix='xq-user-tun-', dir='/var/tmp') as temp:
            stage = Path(temp)
            render(stage, settings)
            binary = obtain_binary(args, settings, stage)
            # Run controller preflight against staged config before installing.
            ctl = load_controller(stage / 'xq-user-proxyctl')
            # Trusted-path checks reject /var/tmp by design. A root-only stage
            # below /run lets the exact runtime validator inspect the config.
            with tempfile.TemporaryDirectory(prefix='xq-user-tun-check-', dir='/run') as checkdir:
                checkdir = Path(checkdir)
                shutil.copyfile(stage / 'sing-box.json', checkdir / 'sing-box.json')
                shutil.copyfile(stage / 'settings.json', checkdir / 'settings.json')
                (checkdir / 'sing-box.json').chmod(0o600)
                (checkdir / 'settings.json').chmod(0o600)
                ctl.CONFIG = checkdir / 'sing-box.json'
                ctl.SETTINGS = checkdir / 'settings.json'
                ctl.load_settings()
                ctl.preflight()
                run(['/usr/bin/unshare', '--net', '/usr/sbin/nft', '--check', '-f', '-'], data=ctl.firewall())
                baseline = ctl.snapshot()
            backup = Path(tempfile.mkdtemp(prefix='xq-user-tun-' + time.strftime('%Y%m%d-%H%M%S-'), dir='/var/backups'))
            write_new(backup / 'host-before.json', (json.dumps(baseline, indent=2) + '\n').encode(), 0o600)
            for directory, mode in ((CONFIG_DIR, 0o755), (LIB_DIR, 0o755), (LIB_DIR / 'bin', 0o755),
                                    (SHARE_DIR, 0o755), (VAR_DIR, 0o700)):
                directory.mkdir(mode=mode)
                directory.chmod(mode)
            mappings = {'xq-user-proxyctl': (CONTROLLER, 0o755),
                        'xq-user-proxy.bash': (HELPER, 0o644),
                        'xq-user-proxy.service': (UNIT, 0o644),
                        'settings.json': (CONFIG_DIR / 'settings.json', 0o600),
                        'sing-box.json': (CONFIG_DIR / 'sing-box.json', 0o600)}
            for name, (destination, mode) in mappings.items():
                write_new(destination, (stage / name).read_bytes(), mode)
            write_new(BINARY, binary.read_bytes(), 0o755)
            write_new(CONFIG_DIR / 'managed-by', b'xq-user-tun-portable-v1\n', 0o600)
            write_new(VAR_DIR / 'latest-backup', (str(backup) + '\n').encode(), 0o600)
            run(['/usr/bin/systemd-analyze', 'verify', UNIT])
            run(['/usr/bin/systemctl', 'daemon-reload'])
            # Make recovery commands available before enabling any guard.
            as_owner(settings, ['/usr/bin/python3', '-I', '-c', SHELL_SETUP])
            if not args.no_start:
                print('启用目标用户 TUN；失败时保留防直连规则，不自动 OFF。', flush=True)
                run([CONTROLLER, 'on'], timeout=90)
                run([CONTROLLER, 'check'])
                result = as_owner(settings, ['/usr/bin/curl', '--disable', '--fail', '--silent', '--show-error',
                                            '-4', '--proxy', '', '--noproxy', '*', '--connect-timeout', '10',
                                            '--max-time', '30', 'https://api.ipify.org'], capture=True, timeout=45)
                print('经 TUN 实测公网出口：' + result.stdout.strip())
            print(f'安装完成：{settings["user"]}（UID {settings["uid"]}），状态：' + ('OFF' if args.no_start else 'ON'))
            print('新 shell 自动加载；当前 shell 执行：source ~/.bashrc')
            print('命令：xq_proxyon / xq_proxyoff / xq_proxystatus；重启默认 OFF。')
            print('日常开关和状态查询需要目标用户已有 sudo 管理权限；本安装器不修改 sudoers。')
            print('网络基线：' + str(backup))
    finally:
        os.close(lock)


def main(argv):
    args = parse_args(argv)
    account = account_for(args)
    settings = settings_for(args, account)
    if args.render_dir:
        if os.geteuid() == 0:
            raise RuntimeError('--render-dir 请由普通用户执行，不要使用 sudo')
        destination = args.render_dir.absolute()
        destination.mkdir(mode=0o700)
        render(destination, settings)
        print('仅渲染配置，没有联网、安装或修改网络：' + str(destination))
        return 0
    if os.geteuid() != 0:
        command = ['/usr/bin/sudo', '--', '/usr/bin/python3', '-I', str(SOURCE / 'install.py'),
                   '--proxy-ip', args.proxy_ip, '--proxy-port', str(args.proxy_port), '--user', account.pw_name]
        if args.no_start: command.append('--no-start')
        if args.archive: command.extend(['--archive', str(args.archive.absolute())])
        os.execv(command[0], command)
    os.umask(0o077)
    install(args, settings)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError) as error:
        print('安装未完成：' + str(error), file=sys.stderr)
        print('没有执行自动 OFF 或网络回滚。若已启用，请检查 sudo /usr/local/sbin/xq-user-proxyctl status；'
              '恢复核心用 on，只有明确恢复直连时才使用 off。', file=sys.stderr)
        sys.exit(1)
