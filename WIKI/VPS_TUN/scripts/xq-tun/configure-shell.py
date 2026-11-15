#!/usr/bin/python3 -I
"""Load the installed XQ shell helper for xuqian; must run as that user."""
import os
import pathlib
import pwd
import re
import stat
import subprocess
import sys
import tempfile
import time


def main():
    if len(sys.argv) != 1:
        raise SystemExit('This helper takes no arguments.')
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (1006, 1006, 1006, 1006):
        raise SystemExit('Run as xuqian (1006:1006), never as root.')
    account = pwd.getpwuid(os.getuid())
    if account.pw_name != 'xuqian':
        raise SystemExit('Expected the xuqian account.')
    home = pathlib.Path(account.pw_dir)
    target = home / '.bashrc'
    mode = 0o644
    old = b''
    if os.path.lexists(target):
        st = target.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid():
            raise SystemExit('Review ~/.bashrc first: expected a regular file owned by xuqian')
        mode = stat.S_IMODE(st.st_mode) & 0o777
        old = target.read_bytes()
    begin = b'# >>> xq-tun shell helper >>>'
    end = b'# <<< xq-tun shell helper <<<'
    pattern = re.compile(rb'(?ms)^' + re.escape(begin) + rb'\n.*?^' + re.escape(end) + rb'(?:\n|$)')
    blocks = pattern.findall(old)
    if old.splitlines().count(begin) != len(blocks) or old.splitlines().count(end) != len(blocks):
        raise SystemExit('Malformed xq-tun helper block in ~/.bashrc; no change made')
    base = pattern.sub(b'', old).rstrip(b'\n')
    block = (begin + b'\n'
             b'if [ -r /usr/local/share/xq-tun/xq-tun.bash ]; then\n'
             b'  . /usr/local/share/xq-tun/xq-tun.bash\n'
             b'fi\n' + end + b'\n')
    new = (base + b'\n\n' if base else b'') + block
    if new == old:
        print('Bash helper already loaded at the end of ~/.bashrc; unchanged.')
        return
    fd, temporary = tempfile.mkstemp(prefix='.bashrc.xq-tun-', dir=home)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(new)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        subprocess.run(['/bin/bash', '--noprofile', '--norc', '-n', temporary], check=True)
        if target.exists():
            backup_fd, backup = tempfile.mkstemp(
                prefix='.bashrc.before-xq-tun-' + time.strftime('%Y%m%d-%H%M%S') + '-', dir=home)
            with os.fdopen(backup_fd, 'wb') as handle:
                handle.write(old)
                handle.flush()
                os.fsync(handle.fileno())
            print('Bashrc backup: ' + backup)
        os.replace(temporary, target)
        print('Installed managed Bash helper block for xuqian.')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == '__main__':
    main()
