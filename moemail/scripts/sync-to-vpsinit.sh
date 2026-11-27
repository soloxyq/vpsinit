#!/usr/bin/env bash
# 把这份工作目录同步到个人仓库里的入库副本（默认 ~/WIKI/vpsinit/moemail）。
#
#   scripts/sync-to-vpsinit.sh            # 同步
#   DRY_RUN=1 scripts/sync-to-vpsinit.sh  # 只列出会改动什么，不写任何文件
#
# 做三件事：
#   1. 代码按 .gitignore 过滤后镜像过去（不含 .git、node_modules、构建产物）；
#      部署脚本生成的 wrangler*.json 也复制，它们在那边同样被 .gitignore 忽略。
#   2. .env 不照搬：写一份把密钥换成 "xxxxxx" 的脱敏副本，那边入库的是这一份。
#   3. 检查目标目录里没有任何文件含有 .env 中的真实密钥，发现就报错退出。
#
# 只同步文件，不做 git 提交。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DST="${1:-$HOME/WIKI/vpsinit/moemail}"
# 名字以这些词结尾的配置项视为脱敏项（密钥或账号标识）
SECRET_KEYS='(TOKEN|SECRET|PASSWORD|API_KEY|ACCOUNT_ID)$'

[ -f "$SRC/.env" ] || { echo "找不到 $SRC/.env" >&2; exit 1; }
[ -d "$DST" ] || { echo "目标目录不存在: $DST" >&2; exit 1; }

rsync_opts=(-a --delete)
if [ -n "${DRY_RUN:-}" ]; then
  rsync_opts+=(-n --itemize-changes)
fi

# 1. 镜像代码。/.env 被排除：既不复制过去，也不会被 --delete 删掉。
rsync "${rsync_opts[@]}" \
  --exclude='/.git/' \
  --exclude='/.env' \
  --include='/.env.example' \
  --include='/wrangler.json' --include='/wrangler.email.json' --include='/wrangler.cleanup.json' \
  --filter=':- .gitignore' \
  "$SRC/" "$DST/"

if [ -n "${DRY_RUN:-}" ]; then
  echo "(DRY_RUN：未写入脱敏 .env，未做密钥检查)"
  exit 0
fi

# 2. 写脱敏后的 .env
{
  echo '# 【已脱敏的入库副本】名字以 TOKEN / SECRET / PASSWORD / API_KEY / ACCOUNT_ID 结尾的项，值已替换为 "xxxxxx"。'
  echo '# 真实值只在部署机工作目录的 .env 里；用本文件部署前必须先填回真实值，'
  echo '# 尤其是 AUTH_SECRET：填错会让已有账号的密码全部失效。'
  echo
  awk -v pat="$SECRET_KEYS" '
    /^[A-Za-z0-9_]+[[:space:]]*=/ {
      key = $0; sub(/[[:space:]]*=.*/, "", key)
      val = $0; sub(/^[^=]*=[[:space:]]*/, "", val)
      if (key ~ pat && val != "" && val != "\"\"" && val != "\x27\x27") {
        print key " = \"xxxxxx\""
        next
      }
    }
    { sub(/（本文件已被 \.gitignore 忽略，不会进入 git）/, ""); print }
  ' "$SRC/.env"
} > "$DST/.env.tmp"
chmod 644 "$DST/.env.tmp"
mv "$DST/.env.tmp" "$DST/.env"

# 3. 目标目录里不能出现真实密钥。
#    密钥经进程替换交给 grep -f，不放在命令行参数里（多用户机器上参数对他人可见）。
leaked="$(
  grep -rlF -f <(
    awk -v pat="$SECRET_KEYS" '
      /^[A-Za-z0-9_]+[[:space:]]*=/ {
        key = $0; sub(/[[:space:]]*=.*/, "", key)
        val = $0; sub(/^[^=]*=[[:space:]]*/, "", val)
        gsub(/^["\x27]|["\x27]$/, "", val)
        if (key ~ pat && length(val) >= 12) print val
      }
    ' "$SRC/.env"
  ) "$DST" 2>/dev/null || true
)"
if [ -n "$leaked" ]; then
  echo "!! 以下文件含有 .env 中的真实密钥，不要提交：" >&2
  echo "$leaked" >&2
  exit 1
fi

echo "已同步到 $DST（.env 已脱敏，未发现真实密钥）"
