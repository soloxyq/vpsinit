#!/bin/bash
# Run explicitly as root on Mico-system. Contains no credentials or sudoers changes.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

die() { printf 'xq-tun install: %s\n' "$*" >&2; exit 1; }
[[ $# == 0 ]] || die 'Usage: sudo bash /path/to/scripts/xq-tun/install.sh'
[[ $EUID == 0 ]] || die 'Run this installer with sudo in an interactive host terminal.'
[[ $(uname -m) == x86_64 ]] || die 'This reviewed installer is for the Mico-system x86_64 host.'
[[ $(cat /proc/1/comm) == systemd ]] || die 'A running host systemd is required.'
[[ -c /dev/net/tun ]] || die '/dev/net/tun is not available.'

for tool in python3 ip nft curl sha256sum tar install systemctl systemd-analyze sysctl \
            setpriv unshare mount umount flock cmp cp readlink stat mktemp; do
  command -v "$tool" >/dev/null || die "Missing prerequisite: $tool (no package changes were made)."
done

[[ ! -L /run/xq-tun-install.lock ]] || die 'Refusing a symlinked installer lock.'
exec 9>/run/xq-tun-install.lock
chmod 0600 /run/xq-tun-install.lock
flock --nonblock 9 || die 'Another xq-tun installation is running.'

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
version=1.14.4
asset="sing-box-${version}-linux-amd64.tar.gz"
asset_url="https://github.com/SagerNet/sing-box/releases/download/v${version}/${asset}"
# GitHub's immutable release asset digest, verified on 2026-11-13:
# https://github.com/SagerNet/sing-box/releases/expanded_assets/v1.14.4
# This release does not publish a separate checksums manifest.
asset_sha256=699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968
binary_dir="/usr/local/lib/xq-tun/sing-box-${version}"
binary="$binary_dir/sing-box"
marker=/etc/xq-tun/managed-by

stage=$(mktemp -d /tmp/xq-tun-install.XXXXXXXX)
cleanup() { rm -rf -- "$stage"; }
trap cleanup EXIT
trap 'printf "Installation failed. Existing namespace/guard and host network settings were not removed.\n" >&2' ERR

# Snapshot explicitly reviewed source files into a root-only staging directory.
# Never source shell settings from user-controlled files as root.
for file in xq-tunctl xq_tun xq-tun.bash shell.rc configure-shell.py verify.py sing-box.json \
            xq-tun.service xq-tun-netns.service; do
  [[ -f "$source_dir/$file" && ! -L "$source_dir/$file" ]] || die "Missing or symlinked source: $file"
  install -o root -g root -m 0600 -- "$source_dir/$file" "$stage/$file"
done

/usr/bin/python3 -I - "$stage" <<'PY'
import hashlib, json, os, pathlib, pwd, socket, stat, sys
stage = pathlib.Path(sys.argv[1])
if socket.gethostname().split('.')[0].lower() != 'mico-system':
    raise SystemExit('This installer is scoped to Mico-system; review before adapting it.')
account = pwd.getpwnam('xuqian')
if (account.pw_uid, account.pw_gid) != (1006, 1006):
    raise SystemExit('Expected xuqian UID/GID 1006; review before adapting to another host.')
marker = pathlib.Path('/etc/xq-tun/managed-by')
managed = marker.exists()
roots = ['/etc/xq-tun', '/etc/netns/xq-tun', '/usr/local/lib/xq-tun',
         '/usr/local/share/xq-tun', '/var/lib/xq-tun']
files = ['/usr/local/sbin/xq-tunctl', '/usr/local/bin/xq_tun', '/usr/local/bin/xq-tun',
         '/etc/systemd/system/xq-tun.service', '/etc/systemd/system/xq-tun-netns.service']
for name in roots + files:
    path = pathlib.Path(name)
    if not os.path.lexists(path):
        continue
    if not managed:
        raise SystemExit(f'Refusing to overwrite unmanaged path: {path}')
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise SystemExit(f'Unsafe managed path: {path}')
    if name in roots and not stat.S_ISDIR(st.st_mode):
        raise SystemExit(f'Expected a directory: {path}')
    if name in files and not stat.S_ISREG(st.st_mode):
        raise SystemExit(f'Expected a regular file: {path}')
    if name in roots:
        for child in path.rglob('*'):
            cs = child.lstat()
            if stat.S_ISLNK(cs.st_mode) or cs.st_uid != 0 or cs.st_mode & 0o022:
                raise SystemExit(f'Unsafe managed entry: {child}')
            if not (stat.S_ISREG(cs.st_mode) or stat.S_ISDIR(cs.st_mode)):
                raise SystemExit(f'Unexpected managed entry type: {child}')
parent = pathlib.Path('/etc/netns')
if os.path.lexists(parent):
    st = parent.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise SystemExit('Unsafe shared /etc/netns directory')
if managed:
    st = marker.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise SystemExit('Unsafe ownership marker')
    if marker.read_text() != 'xq-tun-installer-v1\n':
        raise SystemExit('Unknown ownership marker')
elif os.path.lexists('/run/netns/xq-tun'):
    raise SystemExit('An unmanaged xq-tun network namespace already exists.')
legacy = pathlib.Path('/usr/local/bin/xq-tun')
if legacy.exists():
    # Only the exact wrapper shipped by the previous installer is ours to remove.
    expected = 'd69f9230395aa082588ad13d4e84369b0531c16ea40978e320962e1ac496f153'
    if not managed or hashlib.sha256(legacy.read_bytes()).hexdigest() != expected:
        raise SystemExit('Unrecognized /usr/local/bin/xq-tun; refusing command migration.')
    (stage / 'remove-legacy-wrapper').write_text('yes\n')
for path in pathlib.Path('/etc/systemd/system').glob('xq-tun*.service.d'):
    if path.name in ('xq-tun.service.d', 'xq-tun-netns.service.d'):
        raise SystemExit(f'Review and remove conflicting systemd drop-ins first: {path}')
settings = dict(user='xuqian', uid=1006, gid=1006,
                upstream_host='192.168.5.34', upstream_port=4066)
(stage / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')
json.loads((stage / 'sing-box.json').read_text())
PY

install_user_shell_hook() {
  # HOME content is read and written only after dropping all root privileges.
  # This cannot write through a user-controlled path with root authority.
  /usr/bin/setpriv --reuid=1006 --regid=1006 --clear-groups \
    --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs \
    /usr/bin/python3 -I /usr/local/share/xq-tun/configure-shell.py
}

migrate_legacy_command() {
  [[ -f "$stage/remove-legacy-wrapper" ]] || return 0
  /usr/bin/python3 -I - "${backup_dir:-}" <<'PY'
import hashlib, os, pathlib, shutil, stat, sys, tempfile
legacy = pathlib.Path('/usr/local/bin/xq-tun')
if not os.path.lexists(legacy):
    raise SystemExit(0)
st = legacy.lstat()
expected = 'd69f9230395aa082588ad13d4e84369b0531c16ea40978e320962e1ac496f153'
if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022
        or hashlib.sha256(legacy.read_bytes()).hexdigest() != expected):
    raise SystemExit('Legacy wrapper changed during installation; refusing removal')
backup = pathlib.Path(sys.argv[1]) if sys.argv[1] else pathlib.Path(
    tempfile.mkdtemp(prefix='xq-tun-command-', dir='/var/backups'))
shutil.copy2(legacy, backup / 'xq-tun.legacy-command')
legacy.unlink()
print('Legacy command backed up to ' + str(backup / 'xq-tun.legacy-command'))
PY
}

for unit in xq-tun.service xq-tun-netns.service; do
  fragment=$(systemctl show --property=FragmentPath --value "$unit")
  if [[ -n $fragment && ! -f $marker ]]; then
    die "An unmanaged systemd unit already exists: $fragment"
  fi
  dropins=$(systemctl show --property=DropInPaths --value "$unit")
  [[ -z $dropins ]] || die "Review conflicting drop-ins before installation: $dropins"
  active_state=$(systemctl show --property=ActiveState --value "$unit")
  case $active_state in
    active|inactive|failed) ;;
    *) die "Unit is busy ($active_state): $unit" ;;
  esac
done

if [[ -e /run/netns/xq-tun ]]; then
  namespace_pids=$(ip netns pids xq-tun)
  [[ -z $namespace_pids ]] || die "Exit applications in xq-tun before installing; PIDs: $namespace_pids"
fi

# A repeated installation of identical files reuses the installed files. Full
# verification deliberately stops/restarts this core with no applications present.
# Changed installations require the operator to stop this core before upgrading.
if systemctl is-active --quiet xq-tun.service; then
  for mapping in \
    'xq-tunctl:/usr/local/sbin/xq-tunctl' \
    'xq_tun:/usr/local/bin/xq_tun' \
    'xq-tun.bash:/usr/local/share/xq-tun/xq-tun.bash' \
    'shell.rc:/usr/local/share/xq-tun/shell.rc' \
    'configure-shell.py:/usr/local/share/xq-tun/configure-shell.py' \
    'verify.py:/usr/local/lib/xq-tun/verify.py' \
    'sing-box.json:/etc/xq-tun/sing-box.json' \
    'settings.json:/etc/xq-tun/settings.json' \
    'xq-tun.service:/etc/systemd/system/xq-tun.service' \
    'xq-tun-netns.service:/etc/systemd/system/xq-tun-netns.service'; do
    cmp -s "$stage/${mapping%%:*}" "${mapping#*:}" || \
      die 'Installed files differ. Run sudo /usr/local/sbin/xq-tunctl stop, then rerun this installer.'
  done
  /usr/bin/python3 -I /usr/local/lib/xq-tun/verify.py
  install_user_shell_hook
  migrate_legacy_command
  printf 'Existing files verified; outage test stopped/restarted this core. Boot enablement was unchanged.\n'
  exit 0
fi

printf 'Downloading pinned sing-box %s through 192.168.5.34:4066...\n' "$version"
curl --disable --fail --show-error --silent --location --proto '=https' \
  --proto-redir '=https' --proxy socks5h://192.168.5.34:4066 --noproxy '' \
  --connect-timeout 10 --max-time 300 --retry 2 \
  --output "$stage/$asset" "$asset_url"
printf '%s  %s\n' "$asset_sha256" "$stage/$asset" | sha256sum --check --status
tar --extract --gzip --file "$stage/$asset" --directory "$stage" \
  --no-same-owner --no-same-permissions "sing-box-${version}-linux-amd64/sing-box"
downloaded_binary="$stage/sing-box-${version}-linux-amd64/sing-box"
[[ -f $downloaded_binary && ! -L $downloaded_binary ]] || die 'Archive did not contain a regular executable.'
chmod 0700 "$downloaded_binary"
"$downloaded_binary" version
"$downloaded_binary" check -c "$stage/sing-box.json"

backup_dir=$(mktemp -d /var/backups/xq-tun-$(date +%Y%m%d-%H%M%S)-XXXXXXXX)
chmod 0700 "$backup_dir"
/usr/bin/python3 -I "$stage/verify.py" --snapshot "$backup_dir/host-before.json"
ip -4 route show table all > "$backup_dir/route4.txt"
ip -6 route show table all > "$backup_dir/route6.txt"
ip -4 rule show > "$backup_dir/rule4.txt"
ip -6 rule show > "$backup_dir/rule6.txt"
nft --stateless list ruleset > "$backup_dir/nft.ruleset"
sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding > "$backup_dir/forwarding.txt"
readlink /etc/resolv.conf > "$backup_dir/resolv-link.txt" || true
cp -a /etc/resolv.conf "$backup_dir/resolv.conf.entry"
cp -L /etc/resolv.conf "$backup_dir/resolv.conf.content"
cp -a /etc/nsswitch.conf "$backup_dir/nsswitch.conf"
if [[ -f $marker ]]; then
  mkdir "$backup_dir/previous"
  for item in /etc/xq-tun /etc/netns/xq-tun \
              /usr/local/sbin/xq-tunctl /usr/local/bin/xq_tun /usr/local/bin/xq-tun \
              /usr/local/share/xq-tun /usr/local/lib/xq-tun \
              /etc/systemd/system/xq-tun.service /etc/systemd/system/xq-tun-netns.service; do
    if [[ -e $item ]]; then cp -a --parents -- "$item" "$backup_dir/previous/"; fi
  done
fi
printf 'Host baseline: %s\n' "$backup_dir"

if [[ ! -d /etc/netns ]]; then install -d -o root -g root -m 0755 /etc/netns; fi
install -d -o root -g root -m 0755 /etc/xq-tun /etc/netns/xq-tun \
  /usr/local/lib/xq-tun "$binary_dir" /usr/local/share/xq-tun
install -d -o root -g root -m 0700 /var/lib/xq-tun
printf 'xq-tun-installer-v1\n' > "$marker"
chmod 0600 "$marker"
printf '%s\n' "$backup_dir" > /var/lib/xq-tun/latest-backup
chmod 0600 /var/lib/xq-tun/latest-backup
install -o root -g root -m 0755 "$downloaded_binary" "$binary"
install -o root -g root -m 0755 "$stage/xq-tunctl" /usr/local/sbin/xq-tunctl
install -o root -g root -m 0755 "$stage/xq_tun" /usr/local/bin/xq_tun
install -o root -g root -m 0644 "$stage/xq-tun.bash" /usr/local/share/xq-tun/xq-tun.bash
install -o root -g root -m 0644 "$stage/shell.rc" /usr/local/share/xq-tun/shell.rc
install -o root -g root -m 0644 "$stage/configure-shell.py" /usr/local/share/xq-tun/configure-shell.py
install -o root -g root -m 0755 "$stage/verify.py" /usr/local/lib/xq-tun/verify.py
install -o root -g root -m 0600 "$stage/settings.json" /etc/xq-tun/settings.json
install -o root -g root -m 0600 "$stage/sing-box.json" /etc/xq-tun/sing-box.json
install -o root -g root -m 0644 "$stage/xq-tun.service" /etc/systemd/system/xq-tun.service
install -o root -g root -m 0644 "$stage/xq-tun-netns.service" /etc/systemd/system/xq-tun-netns.service

/usr/bin/python3 -I - <<'PY'
from pathlib import Path
import re
resolver = Path('/etc/netns/xq-tun/resolv.conf')
resolver.write_text('nameserver 172.30.255.2\noptions timeout:2 attempts:2\n')
resolver.chmod(0o644)
nss = Path('/etc/nsswitch.conf').read_text()
nss, count = re.subn(r'^hosts:.*$', 'hosts:          files dns', nss, flags=re.M)
if not count:
    nss += '\nhosts:          files dns\n'
target = Path('/etc/netns/xq-tun/nsswitch.conf')
target.write_text(nss)
target.chmod(0o644)
PY

systemd-analyze verify /etc/systemd/system/xq-tun-netns.service /etc/systemd/system/xq-tun.service
systemctl daemon-reload
"$binary" check -c /etc/xq-tun/sing-box.json
systemctl start xq-tun-netns.service
# Also recheck a namespace whose oneshot unit was already active from a prior run.
/usr/local/sbin/xq-tunctl setup
systemctl reset-failed xq-tun.service
systemctl start xq-tun.service
/usr/bin/python3 -I /usr/local/lib/xq-tun/verify.py
install_user_shell_hook
migrate_legacy_command

printf '\nInstallation and verification completed. Boot activation was not changed.\n'
printf 'Reload your shell with: source ~/.bashrc\n'
printf 'Enter an isolated shell with: xq_tun shell; leave with: exit\n'
printf 'Management command: xq_tun status\n'
printf 'Host baseline and previous files: %s\n' "$backup_dir"
