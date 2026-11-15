#!/bin/bash
# Upgrade only the user entry points of an existing Mico-system installation.
# The core, namespace, routes, DNS and firewall remain running throughout.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
[[ $EUID == 0 && $# == 0 ]] || { printf 'Usage: sudo bash update-shell-entry.sh\n' >&2; exit 2; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ ! -L /run/xq-tun-install.lock ]] || { printf 'Unsafe install lock\n' >&2; exit 1; }
exec 9>/run/xq-tun-install.lock
flock --nonblock 9
[[ $(cat /etc/xq-tun/managed-by) == xq-tun-installer-v1 ]] || exit 1
systemctl is-active --quiet xq-tun.service
before_pid=$(systemctl show xq-tun.service --property=MainPID --value)
backup_dir=$(mktemp -d /var/backups/xq-tun-shell-$(date +%Y%m%d-%H%M%S)-XXXXXXXX)
/usr/bin/python3 -I /usr/local/lib/xq-tun/verify.py --snapshot "$backup_dir/host-before.json"

/usr/bin/python3 -I - "$source_dir" "$backup_dir" <<'PY'
import ast, hashlib, os, pathlib, pwd, shutil, socket, stat, subprocess, sys, tempfile
source, backup = map(pathlib.Path, sys.argv[1:])
account = pwd.getpwnam('xuqian')
if socket.gethostname().split('.')[0].lower() != 'mico-system' or (account.pw_uid, account.pw_gid) != (1006,1006):
    raise SystemExit('Unexpected target host or application user')
mapping = [
    ('shell.rc', '/usr/local/share/xq-tun/shell.rc', 0o644),
    ('xq-tun.bash', '/usr/local/share/xq-tun/xq-tun.bash', 0o644),
    ('configure-shell.py', '/usr/local/share/xq-tun/configure-shell.py', 0o644),
    ('xq_tun', '/usr/local/bin/xq_tun', 0o755),
    ('xq-tunctl', '/usr/local/sbin/xq-tunctl', 0o755),
]

def trusted(path):
    for p in (path, *path.parents):
        info = p.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit(f'Unsafe installed path: {p}')

old = pathlib.Path('/usr/local/bin/xq-tun')
if os.path.lexists(old):
    trusted(old)
    if hashlib.sha256(old.read_bytes()).hexdigest() != 'd69f9230395aa082588ad13d4e84369b0531c16ea40978e320962e1ac496f153':
        raise SystemExit('Legacy entry has changed; refusing to remove it')
staged = []
for name, target_name, mode in mapping:
    src, target = source / name, pathlib.Path(target_name)
    if src.is_symlink() or not src.is_file():
        raise SystemExit(f'Missing or symlinked source: {src}')
    trusted(target if os.path.lexists(target) else target.parent)
    if os.path.lexists(target) and not target.is_file():
        raise SystemExit(f'Unexpected target type: {target}')
    content = src.read_bytes()
    if name.endswith('.py') or name == 'xq-tunctl':
        ast.parse(content, filename=name)
    else:
        subprocess.run(['/bin/bash', '-n'], input=content, check=True)
    staged.append((target, mode, content))
for target, _, _ in staged:
    if target.exists():
        dest = backup / target.relative_to('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
if old.exists():
    dest = backup / 'usr/local/bin/xq-tun'
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(old, dest)
for target, mode, content in staged:
    fd, temporary = tempfile.mkstemp(prefix='.' + target.name + '-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.chown(temporary, 0, 0)
        os.replace(temporary, target)
    finally:
        if os.path.lexists(temporary): os.unlink(temporary)
PY

# Only the ordinary user edits their own shell configuration.
/usr/bin/setpriv --reuid=1006 --regid=1006 --clear-groups --inh-caps=-all \
  --ambient-caps=-all --bounding-set=-all --no-new-privs -- \
  /usr/bin/python3 -I /usr/local/share/xq-tun/configure-shell.py

# Migration deletes only the previously verified, backed-up legacy entry.
/usr/bin/python3 -I - <<'PY'
from pathlib import Path
import hashlib
old = Path('/usr/local/bin/xq-tun')
if old.exists():
    if hashlib.sha256(old.read_bytes()).hexdigest() != 'd69f9230395aa082588ad13d4e84369b0531c16ea40978e320962e1ac496f153':
        raise SystemExit('Legacy entry changed during migration')
    old.unlink()
PY
/usr/local/sbin/xq-tunctl check
/usr/bin/python3 -I /usr/local/lib/xq-tun/verify.py --snapshot "$backup_dir/host-after.json"
cmp "$backup_dir/host-before.json" "$backup_dir/host-after.json"
[[ $(systemctl show xq-tun.service --property=MainPID --value) == "$before_pid" ]]
printf 'Shell entry upgrade complete; core PID and host network unchanged.\nBackup: %s\n' "$backup_dir"
