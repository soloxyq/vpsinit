#!/usr/bin/python3 -I
"""Atomically upgrade owned entry points/guards, without stopping either core."""
import ast
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import subprocess
import tempfile

ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}
ROOT = Path(__file__).resolve().parent.parent
MAPPING = (
    ('xq-user-proxy/xq-user-proxyctl', '/usr/local/sbin/xq-user-proxyctl'),
    ('xq-user-proxy/verify.py', '/usr/local/lib/xq-user-proxy/verify.py'),
    ('xq-tun/xq-tunctl', '/usr/local/sbin/xq-tunctl'),
    ('xq-tun/xq_tun', '/usr/local/bin/xq_tun'),
    ('xq-tun/verify.py', '/usr/local/lib/xq-tun/verify.py'),
    ('xq-tun/xq-tun.bash', '/usr/local/share/xq-tun/xq-tun.bash'),
)


def run(args, **kwargs):
    return subprocess.run(args, env=ENV, text=True, capture_output=True, check=True, timeout=40, **kwargs).stdout


def pids():
    return run(['/usr/bin/systemctl', 'show', 'xq-user-proxy.service', 'xq-tun.service',
                '-p', 'MainPID', '-p', 'ActiveState'])


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run through sudo on the installed host')
    run(['/usr/local/sbin/xq-user-proxyctl', 'check'])
    run(['/usr/local/sbin/xq-tunctl', 'check'])
    before_pids = pids()
    backup = Path(tempfile.mkdtemp(prefix='xq-tun-access-', dir='/var/backups'))
    print('Backup: ' + str(backup), flush=True)
    before = runpy.run_path('/usr/local/lib/xq-user-proxy/verify.py')['snapshot']()
    (backup/'host-before.json').write_text(json.dumps(before, indent=2)+'\n')
    (backup/'namespace-before.nft').write_text(run(['/usr/sbin/ip', 'netns', 'exec', 'xq-tun',
                                                  '/usr/sbin/nft', '--stateless', 'list', 'ruleset']))
    updates = []
    for relative, installed in MAPPING:
        src, target = ROOT/relative, Path(installed)
        for p in (target, *target.parents):
            st = p.lstat()
            if stat.S_ISLNK(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
                raise RuntimeError('Untrusted installed path: '+str(p))
        if not src.is_file() or src.is_symlink():
            raise RuntimeError('Invalid source: '+str(src))
        data = src.read_bytes()
        if relative.endswith(('xq_tun','.bash')):
            run(['/bin/bash', '-n'], input=data.decode())
        else:
            ast.parse(data, filename=relative)
        dest = backup/target.relative_to('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        updates.append((target,data))
    # Parsing occurs in a temporary network namespace, never in the live host.
    host = runpy.run_path(str(ROOT/'xq-user-proxy/xq-user-proxyctl'))
    ns = runpy.run_path(str(ROOT/'xq-tun/xq-tunctl'))
    for source in (host['firewall'](), host['firewall'](False), ns['guard_source']()):
        run(['/usr/bin/unshare', '--net', '/usr/sbin/nft', '--check', '-f', '-'], input=source)
    for target,data in updates:
        fd,name=tempfile.mkstemp(prefix='.'+target.name+'-',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.chmod(name,0o644 if target.name.endswith('.bash') else 0o755); os.chown(name,0,0)
            os.replace(name,target)
        finally:
            if os.path.lexists(name): os.unlink(name)
    host=runpy.run_path('/usr/local/sbin/xq-user-proxyctl')
    with host['locked']():
        state=host['load']()
        if not host['ENABLED'].exists() or not state.get('guard_active'):
            raise RuntimeError('State changed during upgrade; no implicit ON or OFF is allowed')
        host['install_firewall'](state)
        host['check']()
    # setup only atomically replaces its own namespace guard and ownership hash.
    run(['/usr/local/sbin/xq-tunctl','setup'])
    run(['/usr/local/sbin/xq-tunctl','check'])
    verifier=runpy.run_path('/usr/local/lib/xq-user-proxy/verify.py')
    after=verifier['snapshot']()
    (backup/'host-after.json').write_text(json.dumps(after,indent=2)+'\n')
    clean=verifier['without_counters']
    strip=verifier['strip_owned']
    if clean(strip(before)) != clean(strip(after)):
        raise RuntimeError('Unexpected changes outside owned host resources; inspect backup')
    if before_pids != pids():
        raise RuntimeError('Core PID/state changed during upgrade')
    print('PASS: only owned guards/entries updated; other host network resources and both core PIDs unchanged.',flush=True)


if __name__=='__main__':
    os.umask(0o077)
    main()
