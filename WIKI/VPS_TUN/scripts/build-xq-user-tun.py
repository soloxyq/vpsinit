#!/usr/bin/python3
"""Build a reproducible portable installer bundle from this WIKI checkout."""
import gzip
import hashlib
import io
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/xq-user-tun'
DIST = ROOT / 'dist'
FILES = ('install.sh', 'install.py', 'xq-user-proxyctl', 'xq-user-proxy.bash',
         'xq-user-proxy.service', 'sing-box.template.json', 'README.md',
         'tests/test_portable.py', 'tests/netns-check.py')


def main():
    payloads = {name: (SOURCE / name).read_bytes() for name in FILES}
    # WIKI links outside the portable directory have no destination on the
    # new VPS. Bundle the complete guide and keep historical references plain.
    readme = payloads['README.md'].decode().replace('../../VPS-用户级TUN一键部署.md', 'DEPLOYMENT.md')
    readme = re.sub(r'\[([^]]+)\]\((\.\./[^)]+)\)', r'\1（见原 WIKI）', readme)
    payloads['README.md'] = readme.encode()
    guide = (ROOT / 'VPS-用户级TUN一键部署.md').read_text()
    guide = guide.replace('(scripts/xq-user-tun/README.md)', '(README.md)')
    def local_reference(match):
        label, target = match.groups()
        if target == 'README.md' or target.startswith(('https://', 'http://', '#')):
            return match.group(0)
        return label + '（见原 WIKI）'
    guide = re.sub(r'\[([^]]+)\]\(([^)]+)\)', local_reference, guide)
    payloads['DEPLOYMENT.md'] = guide.encode()
    checksums = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                        for name, data in sorted(payloads.items()))
    payloads['CONTENTS.sha256'] = checksums.encode()
    DIST.mkdir(exist_ok=True)
    target = DIST / 'xq-user-tun.tar.gz'
    with target.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name, data in sorted(payloads.items()):
                info = tarfile.TarInfo('xq-user-tun/' + name)
                info.size = len(data)
                info.mode = 0o755 if name in ('install.sh', 'xq-user-proxyctl') else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + '.sha256').write_text(digest + '  ' + target.name + '\n')
    print(f'{target}: {target.stat().st_size} bytes, SHA256 {digest}')


if __name__ == '__main__':
    main()
