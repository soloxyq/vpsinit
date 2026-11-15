#!/bin/bash
# Keep the complete xq-user-tun directory together when copying this installer.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if ! command -v python3 >/dev/null; then
  printf '需要 Python 3.9+；请先安装 python3，再运行本脚本。\n' >&2
  exit 1
fi
exec python3 -I "$source_dir/install.py" "$@"
