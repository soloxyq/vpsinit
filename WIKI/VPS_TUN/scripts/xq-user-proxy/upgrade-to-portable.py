#!/usr/bin/python3 -I
"""Replace an installation of this frozen package, in place, by the maintained
package in ../xq-user-tun. It works while the user proxy is ON or OFF.

    sudo python3 -I upgrade-to-portable.py --user NAME            # examine only: changes nothing
    sudo python3 -I upgrade-to-portable.py --user NAME --apply

What it does, in this order:

1. Examines the host without changing it and refuses unless every managed file
   is exactly this frozen package's file or already the new one, the new rules
   and core configuration are valid, the new private DNS port is free, and an
   installation that is ON passes its own check.
2. Copies every file it will replace to a new directory below /var/backups.
3. Installs the new core binary copy, settings.json, core configuration,
   controller and unit, each by an atomic rename, and reloads systemd.
4. If the proxy is ON, runs the new controller's `on` once. It takes over the
   running state: the rule table is replaced in one nft transaction, the core
   is stopped and started again with the new unit. The guard table, the policy
   rule and the blackhole route exist the whole time, so the owner is blocked
   for those seconds, never direct. The only conntrack entries deleted are this
   feature's own DNS translations, which led to the old entry; nothing else is
   flushed. Connections of the owner that ran through the old core have to be
   opened again.
5. Verifies the result as the owner: check, listeners, default DNS, DNS to a
   public resolver, HTTPS egress.

If step 3, 4 or 5 fails on an installation that was entirely the frozen one,
the previous files are put back and, when it was ON, the frozen controller
brings its rules and core back. That is a return to the previous proxied state,
not to direct traffic, and nothing is ever undone on a timer.

The independent `xq_tun run` namespace (xq-tun.service) is not touched; its
shell helper keeps providing xq_proxyon, xq_proxyoff and xq_proxystatus, which
call the controller at its unchanged path.

upgrade-rehearsal.py runs this very script against a copy of the frozen
installation inside throwaway namespaces.
"""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
OLD = Path(__file__).resolve().parent
NEW = OLD.parent / 'xq-user-tun'
SERVICE = 'xq-user-proxy.service'
CONTROLLER = Path('/usr/local/sbin/xq-user-proxyctl')
CONFIG_DIR = Path('/etc/xq-user-proxy')
CONFIG = CONFIG_DIR / 'sing-box.json'
SETTINGS = CONFIG_DIR / 'settings.json'
MARKER = CONFIG_DIR / 'managed-by'
UNIT = Path('/etc/systemd/system') / SERVICE
LIB_DIR = Path('/usr/local/lib/xq-user-proxy')
BINARY = LIB_DIR / 'bin/sing-box'
VERIFIER = LIB_DIR / 'verify.py'             # the frozen package's checker; the new package has none
VAR_DIR = Path('/var/lib/xq-user-proxy')
STATE = Path('/run/xq-user-proxy')
ENABLED = STATE / 'enabled'
OLD_MARKER, NEW_MARKER = b'xq-user-proxy-v1\n', b'xq-user-tun-portable-v1\n'
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
IP, NFT, SS = '/usr/sbin/ip', '/usr/sbin/nft', '/usr/bin/ss'
SYSTEMCTL, SETPRIV = '/usr/bin/systemctl', '/usr/bin/setpriv'
LOG = []

# One DNS question for an A record, sent as the calling user; prints the first address.
ASK = r'''
import socket,struct,sys
server,name=sys.argv[1],sys.argv[2]
query=(struct.pack('>HHHHHH',0x5151,0x0100,1,0,0,0)
       +b''.join(bytes([len(label)])+label.encode() for label in name.rstrip('.').split('.'))+b'\0'+struct.pack('>HH',1,1))
with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
    s.settimeout(8);s.connect((server,53));port=s.getsockname()[1];s.send(query);data=s.recv(1500)
if data[3]&15 or not data[7]: raise SystemExit('no answer record (rcode %d)'%(data[3]&15))
print(socket.inet_ntoa(data[-4:]),port)
'''
RESOLVE = 'import socket,sys;print(socket.getaddrinfo(sys.argv[1],443,socket.AF_INET,socket.SOCK_STREAM)[0][4][0])'


def say(text=''):
    LOG.append(text)
    print(text, flush=True)


def run(args, *, check=True, data=None, timeout=60):
    result = subprocess.run([str(item) for item in args], env=ENV, input=data, text=True,
                            capture_output=True, timeout=timeout, close_fds=True)
    if check and result.returncode:
        raise RuntimeError(' '.join(map(str, args)) + f'：退出码 {result.returncode}\n'
                           + (result.stdout + result.stderr).strip())
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def trusted(path):
    """Refuse a path that someone other than root could have redirected or rewritten."""
    for item in (path, *path.parents):
        if not os.path.lexists(item):
            continue
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError(f'不可信的已安装路径：{item}')


def content(path):
    """The bytes of a root-owned regular file reached through root-owned directories, or None when absent."""
    path = Path(path)
    trusted(path)
    if not os.path.lexists(path):
        return None
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RuntimeError(f'已安装路径不是普通文件：{path}')
    return path.read_bytes()


def source(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f'缺少源文件或源文件是符号链接：{path}')
    return path.read_bytes()


def module(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


def replace(path, data, mode):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(name, 0, 0)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def as_owner(plan, command, **kwargs):
    return run([SETPRIV, f'--reuid={plan["settings"]["uid"]}', f'--regid={plan["settings"]["gid"]}',
                '--clear-groups', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all',
                '--no-new-privs', '--', *command], **kwargs)


def listeners(port):
    """Which of (tcp, udp) has a socket bound to 127.0.0.1:port."""
    return tuple(bool(run([SS, '-Hln', kind, 'src', '127.0.0.1', 'sport', '=', f':{port}']).stdout.strip())
                 for kind in ('-t', '-u'))


def core_pid():
    shown = run([SYSTEMCTL, 'show', SERVICE, '--property=MainPID,ActiveState'], check=False).stdout
    values = dict(line.split('=', 1) for line in shown.splitlines() if '=' in line)
    return int(values.get('MainPID', '0') or 0) if values.get('ActiveState') == 'active' else 0


def other_service():
    """The independent xq_tun service, which this upgrade must leave exactly as it is."""
    return run([SYSTEMCTL, 'show', 'xq-tun.service', '--property=MainPID,ActiveState'], check=False).stdout.strip()


def foreign(ctl):
    """The host's rules and routes that are not this feature's: they must come out unchanged."""
    snapshot = ctl.snapshot()
    table, tun, pref, rtable = ctl.TABLE, ctl.TUN, int(ctl.PRIORITY), ctl.RTABLE

    def owned(entry):
        item = next(iter(entry.values())) if isinstance(entry, dict) and entry else {}
        return isinstance(item, dict) and (item.get('table') == table or (item.get('name') == table and 'handle' in item
                                                                           and 'family' in item and len(item) <= 3))
    def steady(value):
        """Without the counts that every passing packet changes."""
        if isinstance(value, dict):
            return {key: steady(item) for key, item in value.items() if key not in ('packets', 'bytes')}
        return [steady(item) for item in value] if isinstance(value, list) else value
    return {
        'nftables': [steady(entry) for entry in snapshot['nftables'].get('nftables', []) if not owned(entry)],
        'rules': {family: [rule for rule in rules if rule.get('priority') != pref]
                  for family, rules in snapshot['rules'].items()},
        'routes': {family: [route for route in routes
                            if str(route.get('table')) != rtable and route.get('dev') != tun
                            and not str(route.get('dst', '')).startswith('172.30.254.1')]
                   for family, routes in snapshot['routes'].items()},
        'resolver': (snapshot['resolver_link'], snapshot['resolver_sha256']),
    }


def examine(args):
    """Read-only. Returns the plan, or raises with the reason this host cannot be upgraded by this script."""
    if os.geteuid() != 0:
        raise RuntimeError('需要 root：sudo python3 -I upgrade-to-portable.py --user 用户名 [--apply]')
    here, host = os.stat('/proc/self/ns/net'), os.stat('/proc/1/ns/net')
    if (here.st_dev, here.st_ino) != (host.st_dev, host.st_ino):
        raise RuntimeError('请在宿主网络命名空间中执行')
    account = pwd.getpwnam(args.user)
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise RuntimeError('目标必须是普通用户')
    frozen_controller = source(OLD / 'xq-user-proxyctl')
    fixed = re.search(rb'^UID = (\d+)$', frozen_controller, re.M)
    named = re.search(rb"^USER = '([^']+)'$", frozen_controller, re.M)
    if not fixed or not named or (int(fixed.group(1)), named.group(1).decode()) != (account.pw_uid, account.pw_name):
        raise RuntimeError(f'冻结版控制器固定的用户与 --user {args.user}（UID {account.pw_uid}）不一致')

    installed_config = content(CONFIG)
    if installed_config is None:
        raise RuntimeError(f'没有找到已安装的 {CONFIG}；本脚本只升级冻结版的现有安装')
    upstream = [item for item in json.loads(installed_config).get('outbounds', []) if item.get('tag') == 'upstream']
    if len(upstream) != 1 or upstream[0].get('type') != 'socks':
        raise RuntimeError('已安装的 sing-box.json 没有唯一的 SOCKS 上游')
    settings = dict(schema=1, user=account.pw_name, uid=account.pw_uid, gid=account.pw_gid,
                    proxy_ip=upstream[0]['server'], proxy_port=upstream[0]['server_port'])

    # The new files, rendered exactly as the package's installer renders them.
    installer = module(NEW / 'install.py', 'xq_upgrade_installer')
    stage = Path(tempfile.mkdtemp(prefix='xq-user-proxy-upgrade-', dir='/run'))
    try:
        rendered = {name: text.encode() for name, text in installer.render(stage, settings).items()}
        ctl = module(stage / 'xq-user-proxyctl', 'xq_upgrade_controller')
        ctl.CONFIG, ctl.SETTINGS = stage / 'sing-box.json', stage / 'settings.json'
        ctl.load_settings()
        ctl.check_config()
        for fault in (ctl.endpoint_fault(), ctl.resolver_fault()):
            if fault:
                raise RuntimeError(fault)
        ctl.check_nss()
        for active in (True, False):
            run(['/usr/bin/unshare', '--net', NFT, '--check', '-f', '-'], data=ctl.firewall(active))
        new_port = ctl.DNS_PORT
        frozen_config = json.loads(rendered['sing-box.json'])
        entry = [item for item in frozen_config['inbounds'] if item.get('tag') == 'uid-dns']
        old_port = [item for item in json.loads(source(OLD / 'sing-box.json'))['inbounds']
                    if item.get('tag') == 'uid-dns'][0]['listen_port']
        entry[0]['listen_port'] = old_port
        if json.loads(installed_config) not in (frozen_config, json.loads(rendered['sing-box.json'])):
            raise RuntimeError('已安装的 sing-box.json 既不是冻结版的配置，也不是新版配置；请人工核对后再升级')

        # Every managed file: (path, mode, new content, the contents it may have now).
        managed = [
            (SETTINGS, 0o600, rendered['settings.json'], (None,)),
            (CONFIG, 0o600, rendered['sing-box.json'], (installed_config,)),
            (CONTROLLER, 0o755, rendered['xq-user-proxyctl'], (frozen_controller,)),
            (UNIT, 0o644, rendered['xq-user-proxy.service'], (source(OLD / 'xq-user-proxy.service'),)),
            (MARKER, 0o600, NEW_MARKER, (OLD_MARKER,)),
        ]
        current = {path: content(path) for path, _, _, _ in managed}
        for path, _, new, accepted in managed:
            if current[path] != new and current[path] not in accepted:
                raise RuntimeError(f'{path} 不是冻结版安装的文件，也不是新版文件；拒绝覆盖，请人工核对')
        frozen = all(current[path] in accepted and current[path] != new for path, _, new, accepted in managed)
        done = all(current[path] == new for path, _, new, _ in managed)
        verifier = content(VERIFIER)
        if verifier is not None and verifier != source(OLD / 'verify.py'):
            raise RuntimeError(f'{VERIFIER} 不是冻结版安装的文件；拒绝删除，请人工核对')
        if os.path.lexists(str(UNIT) + '.d'):
            raise RuntimeError(f'{UNIT}.d 存在 drop-in；拒绝在未知的单元覆盖之上升级')

        # The core binary the installed unit runs is the one the new unit will run a copy of.
        started = re.search(r'^ExecStart=(\S+) run ', (current[UNIT] or b'').decode(), re.M)
        if not started:
            raise RuntimeError('无法从已安装的服务单元确定核心程序')
        binary = Path(started.group(1))
        binary_digest = digest(content(binary) or b'')
        version = run([binary, 'version']).stdout.split('\n')[0]
        if installer.VERSION not in version:
            raise RuntimeError(f'核心版本与新版安装包要求的 {installer.VERSION} 不一致：{version}')
        copied = content(BINARY)
        if copied is not None and digest(copied) != binary_digest:
            raise RuntimeError(f'{BINARY} 已存在且与正在使用的核心不同；请人工核对')
        run([binary, 'check', '-c', stage / 'sing-box.json'])
        if not os.access(ctl.CONNTRACK, os.X_OK):
            raise RuntimeError('缺少 /usr/sbin/conntrack')

        enabled = ENABLED.exists()
        if frozen:
            if enabled:
                run([CONTROLLER, 'check'])            # a restore must have a working state to return to
            else:
                found, unchecked = ctl.kernel_leftovers()
                if found or unchecked:
                    raise RuntimeError('开关为 OFF，但本功能有残留：' + '；'.join(found + unchecked)
                                       + '。请先用已安装的控制器清理')
            if any(listeners(new_port)):
                raise RuntimeError(f'127.0.0.1:{new_port} 已被占用；新版专用 DNS 入口需要它')
            for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                with socket.socket(socket.AF_INET, kind) as sock:
                    sock.bind(('127.0.0.1', new_port))
        return dict(settings=settings, managed=managed, current=current, frozen=frozen, done=done, enabled=enabled,
                    verifier=verifier, binary=binary, binary_digest=binary_digest, version=version, ctl=ctl,
                    old_port=old_port, new_port=new_port, args=args)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def describe(plan):
    settings = plan['settings']
    say(f'用户：{settings["user"]}（UID {settings["uid"]}），上游 SOCKS5 {settings["proxy_ip"]}:{settings["proxy_port"]}')
    say(f'核心：{plan["version"]}（{plan["binary"]}）')
    say('当前安装：' + ('全部是冻结版文件' if plan['frozen'] else '全部已是新版文件' if plan['done']
                     else '部分文件已是新版（上次升级没有完成），本次继续完成'))
    say('用户代理开关：' + ('ON' if plan['enabled'] else 'OFF'))
    for path, mode, new, _ in plan['managed']:
        state = '已是新版' if plan['current'][path] == new else '新增' if plan['current'][path] is None else '替换'
        say(f'  {state:<4} {path}（{mode:04o}）')
    say(f'  {"已存在" if content(BINARY) is not None else "新增":<4} {BINARY}（现用核心的副本）')
    if plan['verifier'] is not None:
        say(f'  删除 {VERIFIER}（冻结版的检查脚本，保留在备份中）')
    say(f'专用 DNS 入口：127.0.0.1:{plan["old_port"]} → 127.0.0.1:{plan["new_port"]}（特权端口，仅核心可绑定）')


def back_up(plan):
    backup = Path(tempfile.mkdtemp(prefix='xq-user-proxy-upgrade-' + time.strftime('%Y%m%d-%H%M%S-'), dir='/var/backups'))
    for path in [item[0] for item in plan['managed']] + [VERIFIER, STATE / 'state.json']:
        data = content(path) if path.parent != STATE else (path.read_bytes() if path.exists() else None)
        if data is not None:
            target = backup / path.relative_to('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(stat.S_IMODE(path.stat().st_mode))
    ctl = plan['ctl']
    (backup / 'nft-table.txt').write_text(run([NFT, '--stateless', 'list', 'table', 'inet', ctl.TABLE], check=False).stdout)
    (backup / 'ip-rule.txt').write_text(''.join(run([IP, family, 'rule', 'show']).stdout for family in ('-4', '-6')))
    (backup / 'ip-route-own-table.txt').write_text(
        ''.join(run([IP, family, 'route', 'show', 'table', ctl.RTABLE], check=False).stdout for family in ('-4', '-6')))
    return backup


def install(plan):
    for directory in (LIB_DIR, BINARY.parent):
        directory.mkdir(mode=0o755, exist_ok=True)
        directory.chmod(0o755)
        trusted(directory)
    if content(BINARY) is None:
        with plan['binary'].open('rb') as origin, tempfile.NamedTemporaryFile(
                prefix='.sing-box-', dir=BINARY.parent, delete=False) as copy:
            try:
                shutil.copyfileobj(origin, copy, 1 << 20)
                copy.flush()
                os.fsync(copy.fileno())
                os.chmod(copy.name, 0o755)
                os.replace(copy.name, BINARY)
            finally:
                if os.path.lexists(copy.name):
                    os.unlink(copy.name)
    if digest(BINARY.read_bytes()) != plan['binary_digest']:
        raise RuntimeError('核心副本与原文件不一致')
    for path, mode, new, _ in plan['managed']:
        if plan['current'][path] != new:
            replace(path, new, mode)
    run(['/usr/bin/systemd-analyze', 'verify', UNIT])
    run([SYSTEMCTL, 'daemon-reload'])
    if plan['verifier'] is not None:
        VERIFIER.unlink()


def switch(plan):
    if plan['enabled']:
        say('开关为 ON：由新版控制器接管正在运行的状态（替换规则表、重启核心；防直连规则全程保留）……')
        result = run([CONTROLLER, 'on'], check=False, timeout=180)
        if result.returncode:
            raise RuntimeError('新版控制器的 on 失败：\n' + (result.stdout + result.stderr).strip())
    else:
        say('开关为 OFF：只替换文件，不改动网络。')


def verify(plan):
    args, ctl = plan['args'], plan['ctl']
    status = run([CONTROLLER, 'status'], check=False)
    say('\n'.join('  | ' + line for line in status.stdout.strip().splitlines()))
    if status.returncode:
        raise RuntimeError('新版控制器的 status 报告异常')
    if not plan['enabled']:
        say('PASS：开关保持 OFF，status 正常；下次 xq_proxyon 即使用新版。')
        return
    run([CONTROLLER, 'check'])
    for _ in range(50):                               # systemd does not wait for the core's listeners
        if listeners(plan['new_port']) == (True, True):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError(f'核心没有同时监听 127.0.0.1:{plan["new_port"]} 的 TCP 和 UDP')
    if any(listeners(plan['old_port'])):
        raise RuntimeError(f'旧入口 127.0.0.1:{plan["old_port"]} 仍有监听')
    record = json.loads((STATE / 'core.json').read_text())
    settings = plan['settings']
    if not record.get('loaded') or record.get('upstream') != f'{settings["proxy_ip"]}:{settings["proxy_port"]}':
        raise RuntimeError(f'核心启动记录异常：{record}')
    say(f'PASS：check 通过；核心 PID {core_pid()} 监听 127.0.0.1:{plan["new_port"]}（TCP+UDP），'
        f'旧入口 {plan["old_port"]} 已无监听；启动记录与磁盘配置一致。')
    python = ['/usr/bin/python3', '-I', '-c']
    answer = as_owner(plan, [*python, RESOLVE, args.probe_name]).stdout.strip()
    say(f'PASS：{settings["user"]} 的默认 DNS（glibc → /etc/resolv.conf）解析 {args.probe_name} → {answer}')
    answer, port = as_owner(plan, [*python, ASK, args.probe_resolver, args.probe_name]).stdout.split()
    flows = run([ctl.CONNTRACK, '-L', '-p', 'udp', '--dport', '53', '--dst', args.probe_resolver], check=False).stdout
    mine = [line for line in flows.splitlines() if f'dst={args.probe_resolver} sport={port} ' in line]
    if (len(mine) != 1 or 'zone=' in mine[0] or f'sport={plan["new_port"]} ' in mine[0]
            or f'mark={ctl.OWNER_BIT} ' not in mine[0]):
        raise RuntimeError('发往公网 DNS 的查询没有按预期（不改写、默认 zone、带 owner 标记）进入 TUN：\n' + '\n'.join(mine))
    say(f'PASS：直接查询公网 DNS {args.probe_resolver} 得到 {answer}；该连接未被改写、带 owner 标记（进入 TUN 由核心应答）。')
    if args.egress_url:
        shown = as_owner(plan, ['/usr/bin/curl', '--disable', '--fail', '--silent', '--show-error', '-4', '--proxy', '',
                                '--noproxy', '*', '--connect-timeout', '10', '--max-time', '30', args.egress_url],
                         timeout=45).stdout.strip()
        say(f'PASS：经 TUN 实测公网出口：{shown}')


def restore(plan, backup):
    """Back to the frozen files and, when it was ON, to the frozen controller's rules and core."""
    say('升级失败，恢复升级前的版本（防直连规则保持，不改为直连）……')
    for path, mode, _, _ in plan['managed']:
        saved = backup / path.relative_to('/')
        if saved.exists():
            replace(path, saved.read_bytes(), mode)
        elif os.path.lexists(path):
            path.unlink()
    if plan['verifier'] is not None:
        replace(VERIFIER, plan['verifier'], 0o755)
    shutil.rmtree(BINARY.parent, ignore_errors=True)
    (STATE / 'core.json').unlink(missing_ok=True)         # the new controller's note; the frozen one has none
    run([SYSTEMCTL, 'daemon-reload'], check=False)
    if not plan['enabled']:
        say('已恢复冻结版文件；开关原本为 OFF，网络没有改动。')
        return
    # A core started from the new files must not stay behind the frozen rules, nor a DNS
    # translation to the new entry: a program that keeps one socket would stay tied to it.
    run([SYSTEMCTL, 'stop', SERVICE], check=False, timeout=60)
    ctl = plan['ctl']
    run([ctl.CONNTRACK, '-D', '-f', 'ipv4', '--mark', f'{ctl.DNS_BIT:#x}/{ctl.DNS_BIT:#x}'], check=False)
    result = run([CONTROLLER, 'on'], check=False, timeout=180)
    checked = run([CONTROLLER, 'check'], check=False)
    if result.returncode or checked.returncode:
        say('冻结版控制器没有恢复成功；防直连规则仍在，该用户的公网访问保持阻断：\n'
            + (result.stdout + result.stderr + checked.stderr).strip())
        say(f'人工处理：sudo {CONTROLLER} status 查看原因，修复后 sudo {CONTROLLER} on。')
    else:
        say('已恢复：冻结版控制器、规则和核心重新工作（开关 ON）。')


def main(argv):
    parser = argparse.ArgumentParser(description='把冻结版用户级 TUN 的现有安装原地升级为 xq-user-tun 便携包的版本。')
    parser.add_argument('--user', required=True, help='该安装所属的用户名（必须与冻结版控制器中固定的用户一致）')
    parser.add_argument('--apply', action='store_true', help='执行升级；不加此项只做检查，不改动任何东西')
    parser.add_argument('--probe-name', default='example.com', help='升级后用于验证 DNS 的域名')
    parser.add_argument('--probe-resolver', default='1.1.1.1', help='升级后用于验证“公网 DNS 进入 TUN”的解析器地址')
    parser.add_argument('--egress-url', default='https://api.ipify.org', help='升级后用于验证 HTTPS 出口的地址；留空则跳过')
    args = parser.parse_args(argv)
    os.umask(0o077)
    plan = examine(args)
    describe(plan)
    if not args.apply:
        say('检查通过；未改动任何东西。加 --apply 执行升级。')
        return 0
    before, other = foreign(plan['ctl']), other_service()
    backup = back_up(plan)
    if VAR_DIR.is_dir():
        (VAR_DIR / 'upgrade-backup').write_text(str(backup) + '\n')
    say(f'备份：{backup}')
    try:
        try:
            install(plan)
            switch(plan)
            verify(plan)
        except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            say(f'失败：{error}')
            if plan['frozen']:
                restore(plan, backup)
            else:
                say('这次是继续一次未完成的升级，没有可自动恢复的完整旧版；防直连规则保持。'
                    f'请查看 sudo {CONTROLLER} status。')
            return 1
        after = foreign(plan['ctl'])
        changed = [key for key in before if before[key] != after[key]]
        if changed or other != other_service():
            say('注意：升级期间本功能之外的宿主网络对象有变化（可能来自其他服务的正常活动），请核对：'
                + '、'.join(changed + (['xq-tun.service'] if other != other_service() else [])))
            (backup / 'foreign-before.json').write_text(json.dumps(before, indent=2, default=str))
            (backup / 'foreign-after.json').write_text(json.dumps(after, indent=2, default=str))
        else:
            say('PASS：本功能之外的 nft 表、策略规则、路由和 /etc/resolv.conf 前后一致；xq-tun.service 的 PID 和状态未变。')
        say('升级完成。')
        return 0
    finally:
        (backup / 'upgrade.log').write_text('\n'.join(LOG) + '\n')


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('upgrade: ' + str(error), file=sys.stderr)
        sys.exit(1)
