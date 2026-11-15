#!/bin/bash
# Add the UID-wide switch without changing the existing xq_tun run namespace.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
[[ $EUID == 0 && $# == 0 ]] || { printf 'Usage: sudo bash install.sh\n' >&2; exit 2; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
binary=/usr/local/lib/xq-tun/sing-box-1.14.4/sing-box
[[ -x $binary && -x /usr/local/bin/xq_tun && -x /usr/sbin/conntrack ]]
[[ ! -L /run/xq-user-proxy-install.lock ]]
exec 9>/run/xq-user-proxy-install.lock
flock --nonblock 9
if [[ -e /run/xq-user-proxy/enabled ]]; then
  printf 'User-wide proxy is active; turn it OFF before changing its installed files.\n' >&2
  exit 1
fi
stage=$(mktemp -d /tmp/xq-user-proxy-install.XXXXXXXX)
trap 'rm -rf -- "$stage"' EXIT
for name in xq-user-proxyctl sing-box.json xq-user-proxy.service verify.py; do
  [[ -f "$source_dir/$name" && ! -L "$source_dir/$name" ]]
  install -o root -g root -m 0600 "$source_dir/$name" "$stage/$name"
done
install -o root -g root -m 0600 "$source_dir/../xq-tun/xq-tun.bash" "$stage/xq-tun.bash"
"$binary" check -c "$stage/sing-box.json"
bash -n "$stage/xq-tun.bash"
/usr/bin/python3 -I - "$stage" <<'PY'
import ast, os, pathlib, pwd, socket, stat, sys
stage = pathlib.Path(sys.argv[1])
if socket.gethostname().split('.')[0].lower() != 'mico-system' or pwd.getpwnam('xuqian').pw_uid != 1006:
    raise SystemExit('Unexpected host/user')
for name in ('xq-user-proxyctl','verify.py'): ast.parse((stage/name).read_bytes())
marker = pathlib.Path('/etc/xq-user-proxy/managed-by')
managed = marker.exists()
for name in ('/etc/xq-user-proxy','/usr/local/lib/xq-user-proxy','/var/lib/xq-user-proxy',
             '/usr/local/sbin/xq-user-proxyctl','/etc/systemd/system/xq-user-proxy.service'):
    p=pathlib.Path(name)
    if not os.path.lexists(p): continue
    if not managed: raise SystemExit('Unmanaged destination: '+name)
    for q in (p,*p.parents):
        st=q.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid or st.st_mode&0o022:
            raise SystemExit('Unsafe destination: '+str(q))
if managed and marker.read_text() != 'xq-user-proxy-v1\n': raise SystemExit('Unknown ownership marker')
if pathlib.Path('/etc/systemd/system/xq-user-proxy.service.d').exists():
    raise SystemExit('Review existing service drop-ins first')
PY
backup_dir=$(mktemp -d /var/backups/xq-user-proxy-$(date +%Y%m%d-%H%M%S)-XXXXXXXX)
/usr/bin/python3 -I /usr/local/lib/xq-tun/verify.py --snapshot "$backup_dir/host-before.json"
cp -a /usr/local/share/xq-tun/xq-tun.bash "$backup_dir/previous-shell-helper.bash"
for name in /etc/xq-user-proxy /usr/local/sbin/xq-user-proxyctl /etc/systemd/system/xq-user-proxy.service; do
  if [[ -e $name ]]; then cp -a --parents "$name" "$backup_dir/"; fi
done
install -d -o root -g root -m 0755 /etc/xq-user-proxy /usr/local/lib/xq-user-proxy
install -d -o root -g root -m 0700 /var/lib/xq-user-proxy
printf 'xq-user-proxy-v1\n' > /etc/xq-user-proxy/managed-by
printf '%s\n' "$backup_dir" > /var/lib/xq-user-proxy/latest-backup
install -o root -g root -m 0755 "$stage/xq-user-proxyctl" /usr/local/sbin/xq-user-proxyctl
install -o root -g root -m 0755 "$stage/verify.py" /usr/local/lib/xq-user-proxy/verify.py
install -o root -g root -m 0600 "$stage/sing-box.json" /etc/xq-user-proxy/sing-box.json
install -o root -g root -m 0644 "$stage/xq-user-proxy.service" /etc/systemd/system/xq-user-proxy.service
systemd-analyze verify /etc/systemd/system/xq-user-proxy.service
systemctl daemon-reload

# An error must not silently restore direct networking. Retain the current
# guard/state; only an explicit user OFF operation may release protection.
cleanup_failure() {
  printf 'Verification failed; current guard/state retained, no automatic OFF. Inspect logs and %s\n' "$backup_dir" >&2
}
trap cleanup_failure ERR
# Remove any legacy rollback job; never create a new timer.
systemctl stop xq-user-proxy-rollback.timer xq-user-proxy-rollback.service 2>/dev/null || true
# Installation explicitly enables the feature; verification itself stays live
# and does not toggle it or interrupt an already running core.
/usr/local/sbin/xq-user-proxyctl on
/usr/bin/python3 -I /usr/local/lib/xq-user-proxy/verify.py --baseline "$backup_dir/host-before.json"
install -o root -g root -m 0644 "$stage/xq-tun.bash" /usr/local/share/xq-tun/xq-tun.bash
/usr/bin/setpriv --reuid=1006 --regid=1006 --clear-groups --bounding-set=-all \
  --inh-caps=-all --ambient-caps=-all --no-new-privs -- \
  /usr/bin/python3 -I /usr/local/share/xq-tun/configure-shell.py
trap - ERR
printf 'User-wide proxy installed and verified, ON. Reboot defaults OFF.\nBackup: %s\nReload: source ~/.bashrc\n' "$backup_dir"
