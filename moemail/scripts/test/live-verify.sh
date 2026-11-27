#!/usr/bin/env bash
# 部署后的匿名验证：只发匿名请求，不带任何凭据，不改任何数据。
#   live-verify.sh <BASE_URL>      例：live-verify.sh https://mail.example.com
# 检查的都是“没登录的人能看到什么”：受保护接口一律拒绝、两类会绕过中间件的路径写法返回 404、
# 页面不接受写请求、响应带防嵌套头、注册关闭、登录页正常。
set -uo pipefail
B="${1:?base url}"; B="${B%/}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0; CODE=""
req() { # req <METHOD> <path> [curl 参数...]
  local method="$1" path="$2"; shift 2
  local try
  for try in 1 2 3 4; do
    CODE=$(curl -s -m 30 --path-as-is -o "$T/body" -D "$T/hdr" -w '%{http_code}' -X "$method" "$@" "$B$path" 2>/dev/null) || CODE="000"
    # 连接失败，或本机模拟器的偶发 503（线上不会出现）：重试
    if [ "$CODE" = "000" ] || { [ "$CODE" = "503" ] && grep -q "restarted mid-request" "$T/body" 2>/dev/null; }; then sleep 0.5; continue; fi
    break
  done
}
body() { head -c 160 "$T/body" 2>/dev/null | tr -d '\000' | tr '\n' ' '; }
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1"; }
expect()  { if [[ "$CODE" =~ ^($2)$ ]]; then ok "$1 -> $CODE"; else bad "$1 -> $CODE（期望 $2）| $(body)"; fi; }
present() { if grep -qF -- "$2" "$T/body" 2>/dev/null; then ok "$1"; else bad "$1 -> 响应里没有 \"$2\"（HTTP $CODE）| $(body)"; fi; }
absent()  { if grep -qF -- "$2" "$T/body" 2>/dev/null; then bad "$1 -> 响应里出现了 \"$2\"（HTTP $CODE）| $(body)"; else ok "$1（HTTP $CODE）"; fi; }
header()  { if tr -d '\r' < "$T/hdr" | grep -qi -- "^$2"; then ok "$1"; else bad "$1 -> 响应头里没有 \"$2\""; fi; }
J='Content-Type: application/json'

echo "== 1. 页面与静态文件 =="
req GET /zh-CN/login; expect "登录页" "200"
header "登录页带 X-Frame-Options: DENY" "x-frame-options: deny"
header "登录页带 CSP frame-ancestors 'none'" "content-security-policy: frame-ancestors 'none'"
present "登录页声明不让搜索引擎收录" "noindex"
BUILD_ID=$(grep -oE '\\"b\\":\\"[A-Za-z0-9_-]+\\"' "$T/body" | head -1 | tr -d '\\"' | cut -d: -f2)
[ -n "$BUILD_ID" ] && ok "取到 buildId" || { bad "取不到 buildId，/_next/data 的用例测不到真实写法"; BUILD_ID=x; }
req GET /; expect "GET / 跳到语言前缀" "307"
req GET /zh-CN/this-page-does-not-exist; expect "不存在的页面返回 404" "404"; present "404 页面含完整 html 根元素" "<html"; present "404 页面含 404 文案" "404"; present "404 页面不让搜索引擎收录" "noindex"
for p in /manifest.json /sw.js /favicon.ico /icons/icon-192x192.png; do req GET "$p"; expect "GET $p" "200"; done
req GET "/zh-CN/login?_rsc=abc12" -H 'RSC: 1'; expect "客户端导航用的 RSC 请求" "200"

echo "== 2. 登录与注册 =="
req GET /api/auth/providers; expect "GET /api/auth/providers" "200"; present "登录方式有账号密码" '"credentials"'; absent "没有 GitHub 登录" '"github"'; absent "没有 Google 登录" '"google"'
req GET /api/auth/session; expect "匿名 GET /api/auth/session" "200"; absent "匿名会话为空" '"user"'
# 空请求体：注册关闭时返回 403；即使开着也只会因参数不合法返回 400，不会创建账号。本机测试实例注册是开着的，用 REGISTER_EXPECT=400 运行
req POST /api/auth/register -H "$J" -d '{}'; expect "注册已关闭（空请求体，不会创建账号）" "${REGISTER_EXPECT:-403}"

echo "== 3. 受保护的接口：匿名一律 401，写法变体也一样 =="
for p in /api/emails /api/config /api/config/email-service /api/api-keys /api/webhook /api/roles/users /api/emails/send-permission \
         /api/emails.rsc /api/config.rsc /API/EMAILS /Api/Config "/_next/data/$BUILD_ID/api/emails.json"; do
  req GET "$p" -H 'X-User-Id: 00000000-0000-4000-8000-000000000000'; expect "匿名 GET $p（带伪造的 X-User-Id）" "401"; absent "匿名 GET $p 不返回站点配置" "emailDomains"
done
req GET /api/emails -H 'X-API-Key: mk_invalid'; expect "无效 API Key" "401"
req GET /api/api-keys -H 'X-API-Key: mk_invalid'; expect "API Key 不能用于只认登录会话的接口" "403"
req POST /api/config -H 'X-API-Key: mk_invalid' -H "$J" -d '{}'; expect "API Key 不能改站点配置" "403"
req GET /api/config/email-service -H 'X-API-Key: mk_invalid'; expect "API Key 不能读发件服务配置" "403"

echo "== 4. 会被路由器改写到 /api 的两类路径写法：中间件直接 404 =="
mw404() { expect "$1" "404"; present "$1 是中间件的 404" '"error":"Not Found"'; absent "$1 不返回站点配置" "emailDomains"; }
for hv in "RSC: 1" "x-nextjs-data: 1"; do
  for p in //x.y/api/config //x.y/api/emails //x.y/api/roles/users; do req GET "$p" -H "$hv"; mw404 "匿名 GET $p [$hv]"; done
done
for p in //x.y/api/config/.rsc //x.y/api/emails/.rsc //x/api/api-keys/abc/.prefetch.rsc; do req GET "$p"; mw404 "匿名 GET $p"; done
for p in "/_next/data/$BUILD_ID/api/configXjson" "/_NEXT/DATA/$BUILD_ID/api/config.json" "/_next/data/$BUILD_ID/api/config.JSON" "/_next/data/$BUILD_ID/api/api-keysXjson"; do
  req GET "$p" -H 'x-nextjs-data: 1' -H 'X-API-Key: mk_invalid'; mw404 "匿名 GET $p [x-nextjs-data]"; absent "匿名 GET $p 没有到达 handler" "此接口不支持 API Key"
done
req GET "/_next/data/$BUILD_ID/api/api-keys/abcXjson" -H 'X-API-Key: mk_invalid'; mw404 "匿名 GET /_next/data/<id>/api/api-keys/abcXjson（不带特殊请求头）"

echo "== 5. 页面不接受写请求；跨站写请求被拒绝 =="
req POST /en -H 'Next-Action: x' -H 'Content-Type: text/plain;charset=UTF-8' -d '[]'; expect "POST /en [Next-Action]" "405"
req POST /zh-CN/login -F a=b; expect "POST /zh-CN/login（表单）" "405"
req POST /en.rsc -H 'Next-Action: x' -F a=b; expect "POST /en.rsc [Next-Action]" "405"
req POST /api/webhook -H "$J" -H 'Origin: https://evil.example' -d '{}'; expect "跨站 POST /api/webhook（Origin 不是本站）" "403"; present "被跨站检查拒绝" "跨站请求被拒绝"
req POST /api/webhook -H "$J" -H 'Sec-Fetch-Site: same-site' -d '{}'; expect "同站不同源 POST /api/webhook" "403"
req POST /api/webhook -H "$J" -H "Origin: $B" -d '{}'; expect "本站来源但没登录 POST /api/webhook" "401"
req DELETE /api/emails/00000000-0000-4000-8000-000000000000; expect "匿名 DELETE 邮箱" "401"

echo "== 6. 构建文件不对外提供 =="
for p in /_worker.js/index.js /_worker.js/nop-build-log.json /_routes.json; do req GET "$p"; expect "GET $p" "404|307"; absent "GET $p 不含构建内部内容" "x-prerender-revalidate"; done

echo "== 7. 图片代理接口 /_next/image 已关闭 =="
HP="${B#*://}"   # 反斜杠写法的抓取目标只用本站自己，不涉及任何第三方主机
img_closed() {
  expect "$1" "404|405|307|308"; absent "$1 没有返回抓取到的内容" "start_url"; absent "$1 没有返回抓取到的内容" "csrfToken"
  if tr -d '\r' < "$T/hdr" | grep -qi '^set-cookie:'; then bad "$1 -> 响应带了 Set-Cookie"; else ok "$1 没有 Set-Cookie"; fi
  if tr -d '\r' < "$T/hdr" | grep -qi '^content-disposition: attachment'; then bad "$1 -> 是图片代理的响应"; else ok "$1 不是图片代理的响应"; fi
}
for q in "url=%2Ficons%2Ficon-192x192.png&w=64&q=75" "url=%2Fmanifest.json&w=64&q=75" "url=%2F%5C${HP}%2Fmanifest.json&w=64&q=75" "url=%2F%5C${HP}%2Fapi%2Fauth%2Fcsrf&w=64&q=75" "url=%2F%09%2F${HP}%2Fmanifest.json&w=64&q=75"; do
  for base in /_next/image /_next/image/ /_next/imageX /_NEXT/IMAGE /_next/%69mage; do req GET "$base?$q"; img_closed "匿名 GET $base?${q%%&*}"; done
done

echo
echo "== 结果 [$B]: 通过 $PASS, 失败 $FAIL =="
[ "$FAIL" -eq 0 ]
