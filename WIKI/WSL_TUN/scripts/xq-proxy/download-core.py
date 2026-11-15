#!/usr/bin/env python3
"""Download the pinned, tested sing-box amd64 package via an explicit Karing proxy.

Downloads and verifies only; it does not install packages or change networking.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

VERSION = '1.14.4'
ASSET = f'sing-box_{VERSION}_linux_amd64.deb'
SHA256 = '4e9b8809aed0e3ac78ad14fa3a0af533402425d736f0cc9dc75b1c03d381b614'
URL = f'https://github.com/SagerNet/sing-box/releases/download/v{VERSION}/{ASSET}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', required=True, help='Explicit Karing HTTP or socks5h URL, without credentials')
    parser.add_argument('--output-dir', type=Path, default=Path.home() / '.cache/xq-proxy-deploy')
    args = parser.parse_args()
    if not shutil.which('curl'):
        parser.error('Install curl and ca-certificates first; see the WSL guide.')
    u = urlsplit(args.proxy)
    if u.scheme not in ('http', 'https', 'socks5h') or not u.hostname or not u.port:
        parser.error('Use http://HOST:4066 or socks5h://HOST:4066 for the local Karing proxy.')
    if u.username or u.password:
        parser.error('This helper expects the local Karing endpoint without URL credentials.')
    architecture = subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()
    if architecture != 'amd64':
        parser.error('This replay bundle was tested on amd64 only; choose and verify the appropriate official package separately.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / ASSET
    if target.exists():
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != SHA256:
            parser.error(f'Existing file is unexpected: {target}; inspect it before retrying.')
        print(f'Already verified: {target}')
        return
    fd, temp = tempfile.mkstemp(prefix='sing-box-download-', dir=args.output_dir)
    os.close(fd)
    try:
        subprocess.run(['curl', '--disable', '--fail', '--location', '--show-error', '--silent',
                        '--proto', '=https', '--proto-redir', '=https',
                        '--connect-timeout', '10', '--max-time', '300',
                        '--proxy', args.proxy, '--noproxy', '', '--output', temp, URL], check=True)
        actual = hashlib.sha256(Path(temp).read_bytes()).hexdigest()
        if actual != SHA256:
            raise RuntimeError('SHA256 mismatch; package was not accepted.')
        package = subprocess.check_output(['dpkg-deb', '-f', temp, 'Package'], text=True).strip()
        version = subprocess.check_output(['dpkg-deb', '-f', temp, 'Version'], text=True).strip()
        arch = subprocess.check_output(['dpkg-deb', '-f', temp, 'Architecture'], text=True).strip()
        if (package, version, arch) != ('sing-box', VERSION, 'amd64'):
            raise RuntimeError('Unexpected package metadata.')
        os.chmod(temp, 0o644)
        os.replace(temp, target)
        print(f'Verified package: {target}')
        print('SHA256: ' + actual)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
