#!/usr/bin/env bash
# 在本机回环地址起一个独立的 wrangler pages dev 实例（本地模拟 D1/KV，不连 Cloudflare），
# 运行安全/功能回归套件（sec-suite.sh）与匿名部署前检查（live-verify.sh），跑完自动停止并清理临时状态。
#
# 前置：先执行 pnpm run build:pages 生成 .vercel/output。
# 用法：
#   scripts/test/run-local.sh            # 默认端口 8792
#   PORT=8795 scripts/test/run-local.sh  # 指定端口
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATIC="$ROOT/.vercel/output/static"
CONFIG_JSON="$ROOT/.vercel/output/config.json"
WRANGLER="$ROOT/node_modules/.bin/wrangler"
PORT="${PORT:-8792}"
BASE="http://localhost:$PORT"

[ -d "$STATIC" ] || { echo "找不到构建产物 $STATIC，请先运行 pnpm run build:pages" >&2; exit 2; }
[ -x "$WRANGLER" ] || { echo "找不到 $WRANGLER，请先运行 pnpm install" >&2; exit 2; }

# 优先读取 wrangler.json 里的绑定 ID（让本地 D1 迁移与 pages dev 指向同一个库），没有则用占位 ID
D1_NAME="moemail-db"
D1_ID="00000000-0000-4000-8000-000000000001"
KV_ID="00000000000000000000000000000001"
if [ -f "$ROOT/wrangler.json" ] && command -v jq >/dev/null 2>&1; then
  D1_NAME="$(jq -r '.d1_databases[0].database_name // "moemail-db"' "$ROOT/wrangler.json")"
  D1_ID="$(jq -r '.d1_databases[0].database_id // "00000000-0000-4000-8000-000000000001"' "$ROOT/wrangler.json")"
  KV_ID="$(jq -r '.kv_namespaces[0].id // "00000000000000000000000000000001"' "$ROOT/wrangler.json")"
fi

TMP="$(mktemp -d)"
STATE="$TMP/state"
LOG="$TMP/pages-dev.log"
PID=""

cleanup() {
  if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
    # wrangler 会拉起 workerd 子进程，一起结束
    pkill -P "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

export WRANGLER_SEND_METRICS=false
unset CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID || true

mkdir -p "$STATE"
echo "== 应用本地 D1 迁移 =="
(cd "$ROOT" && CI=1 "$WRANGLER" d1 migrations apply "$D1_NAME" --local --persist-to "$STATE" 2>&1 \
  | grep -c "✅" | sed 's/^/已应用迁移数: /')

echo "== 启动本地测试实例 ($BASE) =="
# 在临时目录起 pages dev，避免被根目录 wrangler.json 干扰绑定参数
(cd "$TMP" && exec "$WRANGLER" pages dev "$STATIC" \
  --ip 127.0.0.1 --port "$PORT" \
  --compatibility-date 2024-03-20 --compatibility-flags nodejs_compat \
  --d1 "DB=$D1_ID" \
  --kv "SITE_CONFIG=$KV_ID" \
  --binding AUTH_SECRET=local-test-secret-not-the-real-one-0123456789abcdef \
  --binding AUTH_TRUST_HOST=true \
  --persist-to "$STATE" \
  --show-interactive-dev-session=false) >"$LOG" 2>&1 &
PID=$!

READY=""
for _ in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 -H 'X-Forwarded-Proto: http' "$BASE/zh-CN/login" 2>/dev/null || echo 000)
  if [ "$code" = "200" ]; then READY=1; break; fi
  kill -0 "$PID" 2>/dev/null || { echo "本地实例提前退出，日志如下：" >&2; tail -40 "$LOG" >&2; exit 1; }
  sleep 2
done
[ -n "$READY" ] || { echo "等待本地实例就绪超时，日志如下：" >&2; tail -40 "$LOG" >&2; exit 1; }

echo "== 运行安全与功能回归套件 =="
CONFIG_JSON="$CONFIG_JSON" "$ROOT/scripts/test/sec-suite.sh" "$BASE" local

echo
echo "== 运行部署前匿名验证（本机注册默认开启，REGISTER_EXPECT=400） =="
REGISTER_EXPECT=400 "$ROOT/scripts/test/live-verify.sh" "$BASE"
