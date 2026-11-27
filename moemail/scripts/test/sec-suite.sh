#!/usr/bin/env bash
# 本地安全/功能回归测试。只对本机实例使用（会注册测试账号、建邮箱）。
#   scripts/test/sec-suite.sh <BASE_URL> [label]
# 或直接用 scripts/test/run-local.sh 一键起本机实例并运行。
# 标签含义：
#   [SEC]  安全断言：修复前的版本应当在这里失败，修复后必须通过
#   [FUNC] 正常功能：修复前后都必须通过
#   [NEW]  新增功能（注册开关等）：只有修复后的版本才会通过
set -uo pipefail
B="${1:?base url}"; LABEL="${2:-run}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_JSON="${CONFIG_JSON:-$ROOT/.vercel/output/config.json}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
case "$B" in http://127.0.0.1:*|http://localhost:*) ;; *) echo "只允许对本机实例运行" >&2; exit 2;; esac

PASS=0; FAIL=0; CODE=""; RETRIES=0; XFP="X-Forwarded-Proto: http"
req() { # req <jar|-> <METHOD> <path> [curl 参数...]
  local jar="$1" method="$2" path="$3"; shift 3
  # 本机是 http：告诉服务端协议，否则 next-auth 在中间件里按 https 找 __Secure- 前缀的 Cookie
  local args=(-s -m 30 -o "$T/body" -D "$T/hdr" -w '%{http_code}' -X "$method" -H "$XFP")
  [ "$jar" != "-" ] && args+=(-b "$T/$jar.jar")
  local try
  for try in 1 2 3 4; do
    CODE=$(curl "${args[@]}" "$@" "$B$path" 2>/dev/null) || CODE="000"
    # 本地模拟器的偶发故障（上一个请求体未被读取时，下一个请求会 503；或连接被重置）：重试
    if [ "$CODE" = "000" ] || { [ "$CODE" = "503" ] && grep -q "restarted mid-request" "$T/body" 2>/dev/null; }; then RETRIES=$((RETRIES+1)); sleep 0.3; continue; fi
    break
  done
}
body() { head -c 200 "$T/body" 2>/dev/null | tr '\n' ' '; }
ok()   { PASS=$((PASS+1)); [ -n "${VERBOSE:-}" ] && echo "  ok   $1"; return 0; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL $1"; }
expect() { # expect <tag> <name> <status-regex>
  if [[ "$CODE" =~ ^($3)$ ]]; then ok "[$1] $2 -> $CODE"; else bad "[$1] $2 -> $CODE (期望 $3) | $(body)"; fi
}
absent() { # absent <tag> <name> <string>  响应体里不能出现该字符串
  if grep -qF -- "$3" "$T/body" 2>/dev/null; then bad "[$1] $2 -> 响应里出现了 \"$3\" (HTTP $CODE) | $(body)"; else ok "[$1] $2 (无泄露, HTTP $CODE)"; fi
}
present() { if grep -qF -- "$3" "$T/body" 2>/dev/null; then ok "[$1] $2"; else bad "[$1] $2 -> 响应里没有 \"$3\" (HTTP $CODE) | $(body)"; fi; }
J='Content-Type: application/json'

register() { req - POST /api/auth/register -H "$J" -d "{\"username\":\"$1\",\"password\":\"$2\"}"; }
login() { # login <jar> <user> <pass>
  local jar="$T/$1.jar" csrf; rm -f "$jar"
  csrf=$(curl -s -m 30 -H "$XFP" -c "$jar" -b "$jar" "$B/api/auth/csrf" | jq -r '.csrfToken // empty')
  curl -s -m 30 -o "$T/login.out" -c "$jar" -b "$jar" -X POST "$B/api/auth/callback/credentials" \
    -H 'X-Auth-Return-Redirect: 1' -H "$XFP" \
    --data-urlencode "csrfToken=$csrf" --data-urlencode "username=$2" --data-urlencode "password=$3" \
    --data-urlencode "callbackUrl=$B/" >/dev/null
  req "$1" GET /api/auth/session
  jq -r '.user.id // empty' "$T/body" 2>/dev/null
}
role_of() { req "$1" GET /api/auth/session; jq -r '[.user.roles[]?.name] | join(",")' "$T/body" 2>/dev/null; }

echo "== 准备测试数据 ($B) =="
PW='Passw0rd-local-test'
for u in owner1 civ1 kn1 dk1 victim1; do register "$u" "$PW"; [ "$CODE" = 200 ] || echo "  注册 $u -> $CODE $(body)"; done
OWNER=$(login owner owner1 "$PW"); CIV=$(login civ civ1 "$PW"); KN=$(login kn kn1 "$PW"); DK=$(login dk dk1 "$PW"); VICTIM=$(login victim victim1 "$PW")
echo "  owner=$OWNER civ=$CIV kn=$KN dk=$DK victim=$VICTIM"
[ -n "$OWNER" ] && [ -n "$CIV" ] && [ -n "$KN" ] && [ -n "$DK" ] && [ -n "$VICTIM" ] || { echo "登录失败，无法继续"; cat "$T/login.out" 2>/dev/null | head -c 300; exit 3; }
req owner GET /api/roles/init-emperor; echo "  init-emperor -> $CODE $(body)"
req owner POST /api/roles/promote -H "$J" -H "Origin: $B" -d "{\"userId\":\"$KN\",\"roleName\":\"knight\"}"; echo "  promote kn -> $CODE"
req owner POST /api/roles/promote -H "$J" -H "Origin: $B" -d "{\"userId\":\"$DK\",\"roleName\":\"duke\"}"; echo "  promote dk -> $CODE"
echo "  角色: owner=$(role_of owner) civ=$(role_of civ) kn=$(role_of kn) dk=$(role_of dk)"
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"ownerbox","expiryTime":0,"domain":"moemail.app"}'
BOX=$(jq -r '.id // empty' "$T/body"); echo "  owner 邮箱 -> $CODE id=$BOX"
req kn POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"knbox","expiryTime":0,"domain":"moemail.app"}'; echo "  kn 邮箱 -> $CODE"
req owner POST /api/api-keys -H "$J" -H "Origin: $B" -d '{"name":"owner-key"}'; OKEY=$(jq -r '.key // empty' "$T/body"); echo "  owner key -> $CODE ${OKEY:0:6}…"
req dk POST /api/api-keys -H "$J" -H "Origin: $B" -d '{"name":"dk-key"}'; DKEY=$(jq -r '.key // empty' "$T/body"); echo "  dk key -> $CODE ${DKEY:0:6}…"
# App Router 的页面里 buildId 在内联数据里，形如 \"b\":\"<id>\"（没有 Pages Router 的 "buildId":"…"）
BUILD_ID=$(curl -s -m 30 -H "$XFP" "$B/zh-CN/login" | grep -oE '\\"b\\":\\"[A-Za-z0-9_-]+\\"' | head -1 | tr -d '\\"' | cut -d: -f2); BUILD_ID=${BUILD_ID:-x}
echo "  buildId=$BUILD_ID"
FAKE=00000000-0000-4000-8000-000000000000
DENY='401|403|404|405|307|308|400'

echo "== 1. 匿名访问：所有受保护接口及其变体都必须被拒绝，且不泄露数据 =="
GETS=(/api/emails "/api/emails/$BOX" "/api/emails/$BOX/$FAKE" "/api/emails/$BOX/share" /api/emails/send-permission
      /api/config /api/config/email-service /api/api-keys /api/webhook /api/roles/users /api/roles/init-emperor)
variants() { # 输出一个路径的各种写法
  local p="$1"
  echo "$p"; echo "$p.rsc"; echo "$p/.rsc"; echo "$p.prefetch.rsc"; echo "$p.json"; echo "$p.action"; echo "$p.html"; echo "$p.txt"
  echo "${p/\/api\//\/API\/}"; echo "${p/\/api\//\/API\/}.rsc"
  echo "$(echo "$p" | sed -E 's|^/api/([a-z-]+)|/api/\U\1|')"; echo "$(echo "$p" | sed -E 's|^/api/([a-z-]+)|/api/\U\1|').rsc"
  echo "${p/\/api\//\/api\/\/}"; echo "${p/\/api\//\/api\/.\/}"; echo "${p/\/api\//\/%61pi\/}"; echo "${p/\/api\//\/%61pi\/}.rsc"
  echo "/api/%65mails${p#/api/emails}" | grep -F '/api/%65mails' | grep -vF "/api/%65mails$p" || true
  echo "/_next/data/$BUILD_ID$p.json"; echo "/_next/data/x$p.json"
}
for p in "${GETS[@]}"; do
  while IFS= read -r v; do
    [ -n "$v" ] || continue
    for hdr in "" "X-User-Id: $OWNER"; do
      for extra in "" "RSC: 1" "x-nextjs-data: 1" "x-middleware-subrequest: middleware:middleware:middleware:middleware:middleware"; do
        a=(); [ -n "$hdr" ] && a+=(-H "$hdr"); [ -n "$extra" ] && a+=(-H "$extra")
        req - GET "$v" --path-as-is "${a[@]}"
        n="匿名 GET $v ${hdr:+[伪造 X-User-Id]} ${extra:+[$extra]}"
        expect SEC "$n" "$DENY"
        absent SEC "$n" "ownerbox"
        absent SEC "$n" "secretKey"
      done
    done
  done < <(variants "$p")
done
WRITES=("POST /api/emails/generate {\"name\":\"anonbox\",\"expiryTime\":0,\"domain\":\"moemail.app\"}"
        "POST /api/roles/promote {\"userId\":\"$CIV\",\"roleName\":\"duke\"}"
        "POST /api/webhook {\"url\":\"https://attacker.invalid/hook\",\"enabled\":true}"
        "POST /api/webhook/test {\"url\":\"http://127.0.0.1:9/\"}"
        "POST /api/config {\"defaultRole\":\"duke\",\"emailDomains\":\"evil.invalid\",\"adminContact\":\"x\",\"maxEmails\":\"99\"}"
        "POST /api/api-keys {\"name\":\"anon\"}"
        "DELETE /api/users/$VICTIM {}"
        "DELETE /api/emails/$BOX {}")
for w in "${WRITES[@]}"; do
  m=${w%% *}; rest=${w#* }; p=${rest%% *}; d=${rest#* }
  for v in "$p" "$p.rsc" "$p/.rsc" "${p/\/api\//\/API\/}.rsc"; do
    for hdr in "" "X-User-Id: $OWNER"; do
      a=(-H "$J" -d "$d"); [ -n "$hdr" ] && a+=(-H "$hdr")
      req - "$m" "$v" --path-as-is "${a[@]}"
      expect SEC "匿名 $m $v ${hdr:+[伪造 X-User-Id]}" "$DENY"
    done
  done
done
# 写请求之后，状态必须没被改动
req owner GET /api/emails; present SEC "匿名删除之后 owner 的邮箱仍在" "ownerbox"; absent SEC "匿名没能建出邮箱" "anonbox"
req owner GET /api/config; absent SEC "匿名没能改站点配置" "evil.invalid"
req owner GET /api/webhook; absent SEC "匿名没能改 webhook" "attacker.invalid"
[ "$(role_of civ)" = "civilian" ] && ok "[SEC] 匿名没能提升 civ 的角色" || bad "[SEC] civ 的角色被改成了 $(role_of civ)"
req owner POST /api/roles/users -H "$J" -H "Origin: $B" -d '{"searchText":"victim1"}'; present SEC "匿名没能删除用户 victim1" "victim1"

echo "== 2. 平民账号（任何人都能注册得到）不能越权 =="
for v in /api/emails /api/emails.rsc /api/EMAILS /api/EMAILS.rsc /API/emails.rsc /api/emails/.rsc "/api/emails/$BOX" "/api/emails/$BOX.rsc" "/api/EMAILS/$BOX" /api/emails/send-permission.rsc; do
  for hdr in "" "X-User-Id: $OWNER"; do
    a=(); [ -n "$hdr" ] && a+=(-H "$hdr")
    req civ GET "$v" --path-as-is "${a[@]}"
    n="平民 GET $v ${hdr:+[伪造 X-User-Id]}"
    expect SEC "$n" "$DENY"; absent SEC "$n" "ownerbox"
  done
done
for v in /api/config /api/config.rsc; do
  req civ GET "$v" -H "X-User-Id: $OWNER"; absent SEC "平民 GET $v [伪造 X-User-Id] 读不到 Turnstile 密钥块" "secretKey"
done
for v in /api/api-keys /api/api-keys.rsc /api/webhook /api/webhook.rsc /api/roles/users /api/roles/users.rsc /api/config/email-service /api/config/email-service.rsc; do
  for hdr in "" "X-User-Id: $OWNER"; do
    a=(); [ -n "$hdr" ] && a+=(-H "$hdr")
    req civ GET "$v" "${a[@]}"; expect SEC "平民 GET $v ${hdr:+[伪造 X-User-Id]}" "$DENY"
  done
done
for w in "${WRITES[@]}"; do
  m=${w%% *}; rest=${w#* }; p=${rest%% *}; d=${rest#* }; d=${d/anonbox/civbox}
  for v in "$p" "$p.rsc" "$(echo "$p" | sed -E 's|^/api/([a-z-]+)|/api/\U\1|')"; do
    for hdr in "" "X-User-Id: $OWNER"; do
      a=(-H "$J" -H "Origin: $B" -d "$d"); [ -n "$hdr" ] && a+=(-H "$hdr")
      req civ "$m" "$v" --path-as-is "${a[@]}"
      expect SEC "平民 $m $v ${hdr:+[伪造 X-User-Id]}" "$DENY"
    done
  done
done
req owner GET /api/emails; present SEC "平民攻击之后 owner 的邮箱仍在" "ownerbox"; absent SEC "平民没能以 owner 身份建邮箱" "civbox"
req civ GET /api/emails -H "X-User-Id: $CIV"; absent SEC "平民自己名下也没建出邮箱" "civbox"
req owner GET /api/config; absent SEC "平民没能改站点配置" "evil.invalid"
req owner GET /api/webhook; absent SEC "平民没能改 owner 的 webhook" "attacker.invalid"
[ "$(role_of civ)" = "civilian" ] && ok "[SEC] 平民没能给自己升级" || bad "[SEC] civ 的角色变成了 $(role_of civ)"
req owner POST /api/roles/users -H "$J" -H "Origin: $B" -d '{"searchText":"victim1"}'; present SEC "平民没能删除用户 victim1" "victim1"

echo "== 3. 有权限的普通用户不能冒充别人 =="
for v in /api/emails /api/emails.rsc "/api/emails/$BOX" "/api/emails/$BOX.rsc"; do
  req kn GET "$v" -H "X-User-Id: $OWNER"; absent SEC "骑士 GET $v [伪造 X-User-Id] 读不到 owner 的邮箱" "ownerbox"
done
req kn DELETE "/api/emails/$BOX" -H "X-User-Id: $OWNER" -H "Origin: $B"; req owner GET /api/emails; present SEC "骑士冒充 owner 删邮箱不成功" "ownerbox"
req kn GET /api/emails; present FUNC "骑士能看到自己的邮箱" "knbox"

echo "== 4. 跨站写请求 (CSRF) =="
req owner POST /api/webhook -H 'Content-Type: text/plain' -H 'Origin: https://other.example.com' -d '{"url":"https://attacker.invalid/csrf","enabled":true}'
expect SEC "owner 会话 + 其它子域名的 Origin 写 webhook" "403"
req owner POST /api/webhook -H 'Content-Type: text/plain' -H 'Origin: null' -d '{"url":"https://attacker.invalid/csrf","enabled":true}'
expect SEC "owner 会话 + Origin: null 写 webhook" "403"
req owner POST /api/webhook -H 'Content-Type: text/plain' -H 'Sec-Fetch-Site: same-site' -d '{"url":"https://attacker.invalid/csrf","enabled":true}'
expect SEC "owner 会话 + Sec-Fetch-Site: same-site 写 webhook" "403"
req owner POST /api/emails/generate -H 'Content-Type: text/plain' -H 'Origin: https://evil.example' -d '{"name":"csrfbox","expiryTime":0,"domain":"moemail.app"}'
expect SEC "owner 会话 + 外站 Origin 建邮箱" "403"
req owner DELETE "/api/emails/$BOX" -H 'Origin: https://evil.example'; expect SEC "owner 会话 + 外站 Origin 删邮箱" "403"
req owner GET /api/webhook; absent SEC "跨站请求没能改 webhook" "attacker.invalid/csrf"
req owner GET /api/emails; absent SEC "跨站请求没能建邮箱" "csrfbox"; present SEC "跨站请求没能删邮箱" "ownerbox"
req owner POST /api/webhook -H "$J" -H "Origin: $B" -d '{"url":"https://example.com/hook","enabled":false}'; expect FUNC "owner 同源 Origin 写 webhook" "200"
req owner POST /api/webhook -H "$J" -H 'Sec-Fetch-Site: same-origin' -d '{"url":"https://example.com/hook","enabled":false}'; expect FUNC "owner Sec-Fetch-Site: same-origin 写 webhook" "200"
req owner POST /api/webhook -H "$J" -d '{"url":"https://example.com/hook","enabled":false}'; expect FUNC "owner 无 Origin（非浏览器客户端）写 webhook" "200"
req owner POST /api/webhook -H "$J" -H 'Sec-Fetch-Site: same-origin' -H 'Origin: null' -d '{"url":"https://example.com/hook","enabled":false}'; expect FUNC "Sec-Fetch-Site: same-origin 时即使 Origin 为 null 也放行" "200"
req owner POST /api/webhook -H 'Content-Type: text/plain' -H 'Sec-Fetch-Site: cross-site' -H "Origin: $B" -d '{"url":"https://attacker.invalid/csrf2","enabled":true}'; expect SEC "Sec-Fetch-Site: cross-site 时即使 Origin 写成本站也拒绝" "403"
req owner GET /api/emails -H 'Origin: https://evil.example'; expect FUNC "带外站 Origin 的读请求不受影响" "200"

echo "== 5. 正常功能 =="
req owner GET /api/emails; expect FUNC "owner 列邮箱" "200"; present FUNC "owner 列邮箱含 ownerbox" "ownerbox"
req owner GET "/api/emails/$BOX"; expect FUNC "owner 读邮箱里的邮件列表" "200"
req owner GET /api/emails/send-permission; expect FUNC "owner 查发件权限" "200"
req owner GET /api/config; expect FUNC "owner 读配置" "200"; present FUNC "owner 读配置含 turnstile 块" "turnstile"
req civ GET /api/config; expect FUNC "平民读公开配置" "200"; absent FUNC "平民读公开配置不含 turnstile 密钥" "secretKey"
req owner GET /api/config/email-service; expect FUNC "owner 读发件服务配置" "200"
req owner GET /api/api-keys; expect FUNC "owner 列 API Key" "200"
req owner GET /api/webhook; expect FUNC "owner 读 webhook" "200"
req owner GET '/api/roles/users?page=1'; expect FUNC "owner 列用户" "200"; present FUNC "用户列表含 civ1" "civ1"
req owner POST /api/config -H "$J" -H "Origin: $B" -d '{"defaultRole":"civilian","emailDomains":"moemail.app","adminContact":"","maxEmails":"30"}'; expect FUNC "owner 保存配置" "200"
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"tmpbox","expiryTime":3600000,"domain":"moemail.app"}'; expect FUNC "owner 建临时邮箱" "200"; TMPBOX=$(jq -r '.id // empty' "$T/body")
req owner POST "/api/emails/$BOX/share" -H "$J" -H "Origin: $B" -d '{"expiresIn":3600000}'; expect FUNC "owner 建分享链接" "200|201"; TOKEN=$(jq -r '.token // empty' "$T/body")
if [ -n "$TOKEN" ]; then req - GET "/api/shared/$TOKEN"; expect FUNC "匿名通过分享链接读邮箱" "200"; fi
req owner DELETE "/api/emails/$TMPBOX" -H "Origin: $B"; expect FUNC "owner 删临时邮箱" "200"
req kn GET /api/emails; expect FUNC "骑士列邮箱" "200"
req kn GET /api/api-keys; expect FUNC "骑士无 API Key 权限" "403"
req civ GET /api/roles/init-emperor; expect FUNC "已有皇帝后 init-emperor 拒绝" "400"
req - GET /zh-CN/login; expect FUNC "登录页可访问" "200"
req - GET /; expect FUNC "首页跳转语言前缀" "307"
req owner GET /zh-CN/moe; expect FUNC "owner 打开邮箱页" "200"
req owner GET /zh-CN/profile; expect FUNC "owner 打开个人中心" "200"
req - GET /api/auth/session; expect FUNC "匿名查会话接口" "200"
req - GET /api/auth/providers; expect FUNC "认证 providers 接口" "200"

echo "== 6. API Key =="
req - GET /api/emails -H "X-API-Key: $OKEY"; expect FUNC "owner 的 Key 列邮箱" "200"; present FUNC "Key 列邮箱含 ownerbox" "ownerbox"
req - GET /api/config -H "X-API-Key: $OKEY"; expect FUNC "owner 的 Key 读配置" "200"; absent SEC "owner 的 Key 读配置不含 turnstile 密钥" "secretKey"
req - POST /api/config -H "X-API-Key: $OKEY" -H "$J" -d '{"defaultRole":"duke","emailDomains":"evil.invalid","adminContact":"x","maxEmails":"99"}'; expect SEC "owner 的 Key 不能改站点配置" "403"
req - GET /api/config/email-service -H "X-API-Key: $OKEY"; expect SEC "owner 的 Key 不能读发件服务配置" "403"
req - POST /api/config/email-service -H "X-API-Key: $OKEY" -H "$J" -d '{"enabled":false,"apiKey":""}'; expect SEC "owner 的 Key 不能改发件服务配置" "403"
req owner GET /api/config; absent SEC "owner 的 Key 没能改站点配置" "evil.invalid"
req - POST /api/emails/generate -H "X-API-Key: $OKEY" -H "$J" -d '{"name":"keybox","expiryTime":3600000,"domain":"moemail.app"}'; expect FUNC "owner 的 Key 建邮箱" "200"
req - POST /api/emails/generate -H "X-API-Key: $OKEY" -H "$J" -H 'Origin: https://some-tool.example' -d '{"name":"keybox2","expiryTime":3600000,"domain":"moemail.app"}'; expect FUNC "Key 请求不受 Origin 限制" "200"
req - GET /api/emails -H "X-API-Key: mk_invalid_key_000000000000000000000"; expect FUNC "无效 Key 被拒" "401"
req - GET /api/emails.rsc -H "X-API-Key: mk_invalid_key_000000000000000000000"; expect SEC "无效 Key + .rsc 被拒" "$DENY"; absent SEC "无效 Key + .rsc 不泄露" "ownerbox"
req - GET /api/emails.rsc -H "X-API-Key: mk_invalid_key_000000000000000000000" -H "X-User-Id: $OWNER"; expect SEC "无效 Key + .rsc + 伪造 X-User-Id 被拒" "$DENY"; absent SEC "无效 Key + 伪造头不泄露" "ownerbox"
req - GET /api/api-keys -H "X-API-Key: $OKEY"; expect FUNC "Key 不能访问 api-keys 接口" "403|401"
req - GET /api/api-keys.rsc -H "X-API-Key: $OKEY"; expect SEC "Key 不能经 .rsc 访问 api-keys 接口" "$DENY"
req - GET /api/roles/users.rsc -H "X-API-Key: $OKEY"; expect SEC "Key 不能经 .rsc 访问用户列表" "$DENY"
req - GET /api/emails -H "X-API-Key: $DKEY" -H "X-User-Id: $OWNER"; absent SEC "公爵的 Key + 伪造 X-User-Id 读不到 owner 的邮箱" "ownerbox"
req - GET /api/emails -H "X-API-Key: $DKEY"; expect FUNC "公爵的 Key 列邮箱" "200"
req - POST /api/config -H "X-API-Key: $DKEY" -H "$J" -d '{"defaultRole":"duke","emailDomains":"evil.invalid","adminContact":"x","maxEmails":"99"}'; expect SEC "公爵的 Key 不能改站点配置" "403"
req owner POST /api/roles/promote -H "$J" -H "Origin: $B" -d "{\"userId\":\"$DK\",\"roleName\":\"civilian\"}"; expect FUNC "owner 把公爵降为平民" "200"
req - GET /api/emails -H "X-API-Key: $DKEY"; expect SEC "被降为平民后，旧 Key 不能再访问邮箱接口" "403"
req - POST /api/emails/generate -H "X-API-Key: $DKEY" -H "$J" -d '{"name":"demotedbox","expiryTime":3600000,"domain":"moemail.app"}'; expect SEC "被降为平民后，旧 Key 不能建邮箱" "403"

echo "== 7. 注册开关 =="
req owner GET /api/config; present NEW "配置里有 allowRegistration 字段" "allowRegistration"
req owner POST /api/config -H "$J" -H "Origin: $B" -d '{"defaultRole":"civilian","emailDomains":"moemail.app","adminContact":"","maxEmails":"30","allowRegistration":false}'; expect FUNC "owner 关闭注册" "200"
register closed1 "$PW"; expect NEW "关闭后注册被拒" "403"
req - POST /api/auth/register.rsc -H "$J" -d "{\"username\":\"closed2\",\"password\":\"$PW\"}"; expect NEW "关闭后经 .rsc 注册也被拒" "403|404|405"
req owner POST /api/roles/users -H "$J" -H "Origin: $B" -d '{"searchText":"closed1"}'; absent NEW "关闭注册后没有建出账号 closed1" '"username":"closed1"'
req - GET /zh-CN/login; expect FUNC "关闭注册后登录页可访问" "200"
CIV2=$(login civ civ1 "$PW"); [ -n "$CIV2" ] && ok "[FUNC] 关闭注册后已有账号仍可登录" || bad "[FUNC] 关闭注册后已有账号登录失败"
req owner POST /api/config -H "$J" -H "Origin: $B" -d '{"defaultRole":"civilian","emailDomains":"moemail.app","adminContact":"","maxEmails":"30"}'; expect FUNC "不带 allowRegistration 保存配置" "200"
register closed3 "$PW"; expect NEW "保存其它配置不会把注册重新打开" "403"
req owner POST /api/config -H "$J" -H "Origin: $B" -d '{"defaultRole":"civilian","emailDomains":"moemail.app","adminContact":"","maxEmails":"30","allowRegistration":true}'; expect FUNC "owner 重新打开注册" "200"
register reopened1 "$PW"; expect FUNC "打开后可以注册" "200"

echo "== 8. 不经过中间件时，handler 自己也要守住（x-prerender-revalidate 跳过中间件） =="
# next-on-pages 给中间件路由编了 missing 条件：带上本次构建的 preview mode ID 时中间件不执行。
# 这个 ID 是构建期生成的服务端秘密，本机测试从构建产物里取（PREVIEW_ID 或 CONFIG_JSON 环境变量，默认 .vercel/output/config.json）。
PID="${PREVIEW_ID:-$(jq -r '[.routes[]? | .missing[]? | select(.key=="x-prerender-revalidate" and .value != null) | .value][0] // empty' "$CONFIG_JSON" 2>/dev/null)}"
if [ -z "$PID" ]; then
  bad "[SEC] 取不到 preview mode ID（设置 PREVIEW_ID 或 CONFIG_JSON 指向 .vercel/output/config.json），第 8 节没有执行"
else
  SK="x-prerender-revalidate: $PID"
  # 先确认跳过确实生效：首页正常会被中间件 307 到语言前缀，跳过后就不会
  req - GET / -H "$SK"
  if [ "$CODE" != "307" ]; then ok "[SEC] 跳过头生效（GET / -> $CODE，不是中间件的 307）"; else bad "[SEC] 跳过头没有生效，第 8 节的结果不可信"; fi

  for p in /api/emails "/api/emails/$BOX" "/api/emails/$BOX/$FAKE" "/api/emails/$BOX/share" /api/emails/send-permission \
           /api/config /api/config/email-service /api/api-keys /api/webhook /api/roles/users /api/roles/init-emperor; do
    req - GET "$p" -H "$SK"; expect SEC "跳过中间件 + 匿名 GET $p 返回 401（不是 500）" "401"; absent SEC "跳过中间件 + 匿名 GET $p" "ownerbox"
  done
  req - DELETE "/api/emails/$BOX" -H "$SK"; expect SEC "跳过中间件 + 匿名删邮箱" "401"
  req civ GET /api/emails -H "$SK"; expect SEC "跳过中间件 + 平民列邮箱（缺 MANAGE_EMAIL）" "403"
  req civ GET /api/emails/send-permission -H "$SK"; expect SEC "跳过中间件 + 平民查发件权限" "403"
  req civ POST /api/emails/generate -H "$SK" -H "$J" -d '{"name":"civskip","expiryTime":3600000,"domain":"moemail.app"}'; expect SEC "跳过中间件 + 平民建邮箱" "403"
  req dk GET /api/emails -H "$SK"; expect SEC "跳过中间件 + 被降为平民的公爵会话列邮箱" "403"
  req civ GET /api/config -H "$SK"; expect FUNC "跳过中间件 + 平民读公开配置（登录即可）" "200"; absent SEC "跳过中间件 + 平民读配置不含密钥块" "secretKey"
  # API Key 的使用范围在 handler 里也要执行
  req - GET /api/emails -H "$SK" -H "X-API-Key: $OKEY"; expect FUNC "跳过中间件 + owner 的 Key 列邮箱" "200"
  req - GET /api/emails -H "$SK" -H "X-API-Key: $DKEY"; expect SEC "跳过中间件 + 降级后的旧 Key 列邮箱" "403"
  req - GET /api/emails -H "$SK" -H "X-API-Key: mk_invalid_key_000000000000000000000"; expect SEC "跳过中间件 + 无效 Key" "401"
  for w in "GET /api/roles/users" "GET /api/api-keys" "GET /api/webhook" "GET /api/config/email-service" \
           "POST /api/config {\"defaultRole\":\"duke\",\"emailDomains\":\"evil.invalid\",\"adminContact\":\"x\",\"maxEmails\":\"99\"}" \
           "POST /api/config/email-service {\"enabled\":false,\"apiKey\":\"\"}" \
           "POST /api/roles/promote {\"userId\":\"$CIV\",\"roleName\":\"duke\"}" \
           "POST /api/api-keys {\"name\":\"viakey\"}" "POST /api/webhook {\"url\":\"https://attacker.invalid/viakey\",\"enabled\":true}" \
           "POST /api/webhook/test {\"url\":\"http://127.0.0.1:9/\"}" "DELETE /api/users/$VICTIM" "GET /api/roles/init-emperor"; do
    m=${w%% *}; rest=${w#* }; p=${rest%% *}; d=""; [ "$rest" != "$p" ] && d=${rest#* }
    a=(-H "$SK" -H "X-API-Key: $OKEY"); [ -n "$d" ] && a+=(-H "$J" -d "$d")
    req - "$m" "$p" "${a[@]}"; expect SEC "跳过中间件 + 皇帝的 Key 调只支持会话的 $m $p" "403"
  done
  req - GET /api/config -H "$SK" -H "X-API-Key: $OKEY"; expect FUNC "跳过中间件 + 皇帝的 Key 读公开配置" "200"; absent SEC "跳过中间件 + 皇帝的 Key 读配置不含 turnstile 密钥" "secretKey"
  # 混用身份：会话是 owner，Key 是别人的。只支持会话的接口必须直接拒绝，不能按 Key 判权限、按会话读写
  req owner POST /api/webhook -H "$SK" -H "X-API-Key: $DKEY" -H "$J" -d '{"url":"https://attacker.invalid/mixed","enabled":true}'; expect SEC "跳过中间件 + owner 会话 + 别人的 Key 写 webhook" "403"
  req owner GET /api/api-keys -H "$SK" -H "X-API-Key: $DKEY"; expect SEC "跳过中间件 + owner 会话 + 别人的 Key 列 API Key" "403"
  req owner GET /api/webhook; absent SEC "混用身份没能改 webhook" "attacker.invalid"
  req owner POST /api/roles/users -H "$J" -H "Origin: $B" -d '{"searchText":"victim1"}'; present SEC "跳过中间件也没能删除用户 victim1" "victim1"
  [ "$(role_of civ)" = "civilian" ] && ok "[SEC] 跳过中间件也没能提升 civ 的角色" || bad "[SEC] civ 的角色变成了 $(role_of civ)"
fi

echo "== 9. 低权限 Key + 别人的 Cookie、注册开关输入校验、防嵌套响应头 =="
req owner GET /api/emails -H "X-API-Key: $DKEY"; expect SEC "降级后的旧 Key + owner 的 Cookie 列邮箱（按 Key 判身份）" "403"; absent SEC "低权限 Key + owner 的 Cookie" "ownerbox"
req owner GET /api/emails -H "X-API-Key: mk_invalid_key_000000000000000000000"; expect SEC "无效 Key + owner 的 Cookie" "401"; absent SEC "无效 Key + owner 的 Cookie" "ownerbox"
req owner GET /api/webhook -H "X-API-Key: $OKEY"; expect SEC "Key + Cookie 访问只支持会话的接口" "403"
for v in '"false"' '1' 'null' '"yes"'; do
  req owner POST /api/config -H "$J" -H "Origin: $B" -d "{\"defaultRole\":\"civilian\",\"emailDomains\":\"moemail.app\",\"adminContact\":\"\",\"maxEmails\":\"30\",\"allowRegistration\":$v}"
  expect NEW "allowRegistration=$v（非布尔）返回 400" "400"
done
register reopened2 "$PW"; expect FUNC "非布尔值没有改动注册开关（仍是打开）" "200"
hdrs() { curl -s -m 30 -o /dev/null -D - -H "$XFP" "$@" | tr -d '\r' | tr 'A-Z' 'a-z'; }
for p in /zh-CN/login /en/login /zh-CN /api/auth/session; do
  h=$(hdrs "$B$p")
  grep -q "^content-security-policy: frame-ancestors 'none'" <<<"$h" && ok "[NEW] $p 带 frame-ancestors 'none'" || bad "[NEW] $p 缺少 frame-ancestors 'none'"
  grep -q "^x-frame-options: deny" <<<"$h" && ok "[NEW] $p 带 X-Frame-Options: DENY" || bad "[NEW] $p 缺少 X-Frame-Options: DENY"
done
h=$(hdrs -b "$T/owner.jar" "$B/zh-CN/profile")
grep -q "^x-frame-options: deny" <<<"$h" && ok "[NEW] 个人中心带 X-Frame-Options: DENY" || bad "[NEW] 个人中心缺少 X-Frame-Options: DENY"
if [ -n "${TOKEN:-}" ]; then
  h=$(hdrs "$B/zh-CN/shared/$TOKEN")
  grep -q "^x-frame-options: deny" <<<"$h" && ok "[NEW] 分享页带 X-Frame-Options: DENY" || bad "[NEW] 分享页缺少 X-Frame-Options: DENY"
fi

echo "== 10. 路径与请求头的其它变体 =="
EXTRA_PATHS=(/api%2femails /api%2Femails "/api/emails%2f$BOX" "/api/emails%2F$BOX" /api/%2565mails /api%252femails
             "/api/emails;x" "/api;/emails" "/api/emails/$BOX;.rsc" "/api/emails;.rsc" "/api/emails/;/$BOX"
             "/api/emails/%2e%2e/emails" "/api/x/%2e%2e/emails" "/api/x/..%2femails" "/api\\emails" "/%2fapi/emails"
             "/api/emails%00" "/api/emails%20" "/api/emails/" "/api/emails/./" "/api/emails?x=1#frag")
for v in "${EXTRA_PATHS[@]}"; do
  req - GET "$v" --path-as-is; expect SEC "匿名 GET $v" "$DENY|500"; absent SEC "匿名 GET $v" "ownerbox"
  req civ GET "$v" --path-as-is; absent SEC "平民 GET $v" "ownerbox"
done
for m in PUT PATCH OPTIONS TRACE PROPFIND CONNECT FOO; do
  for p in /api/emails "/api/emails/$BOX" /api/config /api/webhook "/api/users/$VICTIM"; do
    req - "$m" "$p" -H "$J" -d '{}'; expect SEC "匿名 $m $p" "$DENY|501"; absent SEC "匿名 $m $p" "ownerbox"
  done
  req civ "$m" "/api/emails/$BOX" -H "$J" -H "Origin: $B" -d '{}'; absent SEC "平民 $m /api/emails/$BOX" "ownerbox"
done
INTERNAL_HDRS=("x-invoke-path: /api/shared/x" "x-invoke-query: {}" "x-invoke-output: /api/shared/x" "x-matched-path: /api/shared/[token]"
               "x-now-route-matches: token=x" "x-middleware-prefetch: 1" "x-middleware-invoke: 1" "x-middleware-next: 1"
               "x-middleware-rewrite: /api/shared/x" "x-middleware-override-headers: x-user-id" "x-middleware-request-x-user-id: $OWNER"
               "x-original-url: /api/shared/x" "x-rewrite-url: /api/shared/x" "x-forwarded-host: evil.example"
               "x-nextjs-data: 1" "next-router-state-tree: %5B%22%22%5D" "next-action: 1" "purpose: prefetch" "x-vercel-id: 1"
               "x-prerender-revalidate: 0" "x-prerender-revalidate-if-generated: 1" "cf-connecting-ip: 127.0.0.1" "host: localhost")
for hv in "${INTERNAL_HDRS[@]}"; do
  for p in /api/emails "/api/emails/$BOX" /api/config; do
    req - GET "$p" -H "$hv"; expect SEC "匿名 GET $p [$hv]" "$DENY"; absent SEC "匿名 GET $p [$hv]" "ownerbox"; absent SEC "匿名 GET $p [$hv]" "secretKey"
  done
  req - DELETE "/api/emails/$BOX" -H "$hv"; expect SEC "匿名 DELETE /api/emails/$BOX [$hv]" "$DENY"
done
# 只带 X-Forwarded-Proto: https（不带本机测试默认的 http）。两个值同时出现时 next-auth 拼 URL 失败返回 500（失败即拒绝，
# 线上由 Cloudflare 设置这个头，客户端给的值会被覆盖），这里只测单独的 https
c=$(curl -s -m 30 -o "$T/body" -w '%{http_code}' -H 'X-Forwarded-Proto: https' "$B/api/emails"); CODE=$c
expect SEC "匿名 GET /api/emails [X-Forwarded-Proto: https]" "$DENY"; absent SEC "匿名 GET /api/emails [X-Forwarded-Proto: https]" "ownerbox"
c=$(curl -s -m 30 -o "$T/body" -w '%{http_code}' -H 'X-Forwarded-Proto: https' -b "$T/owner.jar" "$B/api/emails"); CODE=$c
expect SEC "owner 的 http Cookie + X-Forwarded-Proto: https（找的是 __Secure- Cookie）" "$DENY"
req owner GET /api/emails; present SEC "第 10 节之后 owner 的邮箱仍在" "ownerbox"

echo "== 11. 页面路径只接受 GET/HEAD（挡住 RSC / Server Action 反序列化入口） =="
for p in /en /zh-CN /zh-CN/login /en.rsc /zh-CN.rsc /zh-CN/login.rsc /en/moe /en/moe.rsc /zh-CN/profile.rsc /EN /x/y.rsc; do
  for na in "" "Next-Action: x"; do
    a=(-F a=b); [ -n "$na" ] && a+=(-H "$na")
    req - POST "$p" --path-as-is "${a[@]}"; expect SEC "匿名 POST $p ${na:+[$na]} multipart" "405"; absent SEC "匿名 POST $p ${na:+[$na]}" '"a":"$@1"'
  done
  req owner POST "$p" --path-as-is -H "Next-Action: x" -H "Origin: $B" -H 'Content-Type: text/plain;charset=UTF-8' -d '[]'; expect SEC "owner POST $p [Next-Action] text/plain" "405"
done
req - POST "/_next/data/$BUILD_ID/en.json" -H 'x-nextjs-data: 1' -H 'Next-Action: x' -F a=b; expect SEC "匿名 POST /_next/data/…/en.json [Next-Action]" "405|404"; absent SEC "匿名 POST /_next/data/…/en.json" '"a":"$@1"'
for m in PUT PATCH DELETE OPTIONS; do req - "$m" /zh-CN/login; expect SEC "匿名 $m /zh-CN/login" "405"; done
req - GET /zh-CN/login.rsc -H 'RSC: 1'; expect FUNC "GET /zh-CN/login.rsc（RSC 请求）" "200"
req - HEAD /zh-CN/login; expect FUNC "HEAD /zh-CN/login" "200"
for p in /favicon.ico /manifest.json /sw.js; do req - GET "$p"; expect FUNC "GET $p（静态文件不被语言跳转）" "200"; done
for p in /favicon.ico /zh-CN/login.rsc; do
  h=$(hdrs "$B$p")
  grep -q "^x-frame-options: deny" <<<"$h" && ok "[NEW] $p 带 X-Frame-Options: DENY" || bad "[NEW] $p 缺少 X-Frame-Options: DENY"
done

echo "== 12. 会被路由器改写到 /api 的两类路径写法：中间件要自己拒绝，不能只靠 handler =="
# 中间件拿到的是原始路径，路由器按改写后的路径选处理函数。下面两类写法会落到 /api 的处理函数上，原始路径却不在 /api 下：
#   /_next/data/<buildId>/api/…   路由器去掉前缀再匹配（不区分大小写，.json 里的点是通配符）
#   //<任意>/api/…                改写时被当成“//主机/路径”重新解析，前面那段被丢掉
# 怎么看请求有没有越过中间件：带一把无效 Key 访问只认会话的接口，中间件回“无权限查看”，handler 回“此接口不支持 API Key”。
# 这两类地址本站用不到，修复后一律是中间件的 404 {"error":"Not Found"}。
BADKEY='X-API-Key: mk_invalid'
mw404() { # mw404 <name>：必须是中间件的 404，不是 handler 的回应
  expect SEC "$1" "404"; present SEC "$1（中间件的 404）" '"error":"Not Found"'
  absent SEC "$1" "此接口不支持 API Key"; absent SEC "$1" "ownerbox"; absent SEC "$1" "emailDomains"
}
DP="/_next/data/$BUILD_ID"
[ "$BUILD_ID" != x ] && ok "[SEC] 取到了 buildId" || bad "[SEC] 取不到 buildId，/_next/data 的用例测不到真实写法"
for v in "$DP/api/api-keysXjson" "$DP/api/api-keys/json" "/_NEXT/DATA/$BUILD_ID/api/api-keys.json" "/_next/DATA/$BUILD_ID/api/api-keys.json" \
         "$DP/api/api-keys.JSON" "$DP/api/webhookXjson" "$DP/api/roles/usersXjson" "$DP/api/emailsXjson" "$DP/api/configXjson" \
         "$DP$DP/api/api-keysXjson.json"; do
  req - GET "$v" -H 'x-nextjs-data: 1' -H "$BADKEY"; mw404 "匿名 GET $v [x-nextjs-data]"
  req civ GET "$v" -H 'x-nextjs-data: 1'; mw404 "平民 GET $v [x-nextjs-data]"
  req owner GET "$v" -H 'x-nextjs-data: 1'; mw404 "owner GET $v [x-nextjs-data]"
done
for v in "$DP/api/api-keys/${FAKE}Xjson" "/_NEXT/data/$BUILD_ID/api/api-keys/$FAKE.json" "$DP/api/emails/${BOX}Xjson" "$DP/api/users/${VICTIM}Xjson"; do
  req - GET "$v" -H "$BADKEY"; mw404 "匿名 GET $v（不带特殊请求头）"
  req owner GET "$v"; mw404 "owner GET $v（不带特殊请求头）"
done
# 注意：结尾小写的 /.rsc 在调用中间件前会被 Next 去掉（区分大小写），修复前这几条是被语言跳转挡住的（307），
# 它们只检查“现在统一是中间件的 404”。修复前真正到得了 handler 的是 /.prefetch.rsc 和下面大写的 /.RSC。
for v in "//x/api/api-keys/$FAKE/.prefetch.rsc" "//x.y/api/config/.rsc" "//x.y/api/emails/$BOX/.rsc" "//x.y/api/emails/.rsc" "//x.y/api/roles/users/.rsc"; do
  req - GET "$v" --path-as-is -H "$BADKEY"; mw404 "匿名 GET $v（不带特殊请求头）"
  req - GET "$v" --path-as-is; mw404 "匿名 GET $v（不带 Key）"
  req civ GET "$v" --path-as-is; mw404 "平民 GET $v"
  req owner GET "$v" --path-as-is; mw404 "owner GET $v"
done
# 路由器匹配 .rsc 不区分大小写：结尾写成 /.RSC 时 Next 不会去掉它，中间件把它当带点号的路径放行，
# 路由器再改写到 /api/…。不需要任何特殊请求头，HEAD 也行。/// 和反斜杠开头的写法同理。
for v in "//x.y/api/webhook/.RSC" "//x.y/api/config/.RSC" "//x.y/api/roles/users/.RSC" "//x.y/api/api-keys/.RSC" "//x.y/api/emails/.Rsc" \
         "///x.y/api/config/.RSC" "/\\x.y/api/config/.RSC"; do
  req - GET "$v" --path-as-is -H "$BADKEY"; mw404 "匿名 GET $v（不带特殊请求头）"
  req civ GET "$v" --path-as-is; mw404 "平民 GET $v（不带特殊请求头）"
  req owner GET "$v" --path-as-is; mw404 "owner GET $v（不带特殊请求头）"
done
req owner HEAD "//x.y/api/config/.RSC" --path-as-is --head; expect SEC "owner HEAD //x.y/api/config/.RSC" "404"
# buildId 换大小写（路由器连它也不区分大小写）；规范写法的 data 地址里再套一层 //（Next 还原后变成 // 开头）
LBID=$(printf '%s' "$BUILD_ID" | tr 'A-Z' 'a-z'); UBID=$(printf '%s' "$BUILD_ID" | tr 'a-z' 'A-Z')
for v in "/_next/data/$LBID/api/configXjson" "/_next/data/$UBID/api/configXjson" "$DP//x.y/api/emails/$BOX/.foo.json" "$DP//x.y/api/config/.RSC.json"; do
  req - GET "$v" --path-as-is -H 'x-nextjs-data: 1' -H "$BADKEY"; mw404 "匿名 GET $v [x-nextjs-data]"
  req civ GET "$v" --path-as-is -H 'x-nextjs-data: 1'; mw404 "平民 GET $v [x-nextjs-data]"
  req owner GET "$v" --path-as-is -H 'x-nextjs-data: 1'; mw404 "owner GET $v [x-nextjs-data]"
done
req owner HEAD "$DP/api/configXjson" -H 'x-nextjs-data: 1' --head; expect SEC "owner HEAD /_next/data/<id>/api/configXjson" "404"
req owner OPTIONS "$DP/api/configXjson" -H 'x-nextjs-data: 1'; expect SEC "owner OPTIONS /_next/data/<id>/api/configXjson" "404"
for hv in "RSC: 1" "x-nextjs-data: 1"; do
  for v in "//x.y/api/config" "//x.y/api/emails" "//x.y/api/emails/$BOX" "//x.y/api/emails/$BOX/.foo" "//x.y/api/api-keys" "//x.y/api/roles/users" "//x.y/en/login"; do
    req - GET "$v" --path-as-is -H "$hv"; mw404 "匿名 GET $v [$hv]"
    req civ GET "$v" --path-as-is -H "$hv"; mw404 "平民 GET $v [$hv]"
    req owner GET "$v" --path-as-is -H "$hv"; mw404 "owner GET $v [$hv]"
  done
done
req - HEAD "//x.y/api/config" --path-as-is -H 'RSC: 1' --head; expect SEC "匿名 HEAD //x.y/api/config [RSC]" "404"
# 写请求同样到不了 handler。期望的是这条规则的 404（修复前这些地址靠“页面只接受 GET/HEAD”返回 405）
w404() { expect SEC "$1" "404"; present SEC "$1（中间件的 404）" '"error":"Not Found"'; }
req owner POST "//x.y/api/webhook/.RSC" --path-as-is -H "$J" -H "Origin: $B" -d '{"url":"https://example.com/h-sec12","enabled":true}'; w404 "owner POST //x.y/api/webhook/.RSC"
req owner POST "//x.y/api/webhook/.rsc" --path-as-is -H "$J" -H "Origin: $B" -d '{"url":"https://example.com/h-sec12","enabled":true}'; w404 "owner POST //x.y/api/webhook/.rsc"
req owner POST "$DP/api/webhookXjson" -H 'x-nextjs-data: 1' -H "$J" -H "Origin: $B" -d '{"url":"https://example.com/h-sec12","enabled":true}'; w404 "owner POST /_next/data/…/api/webhookXjson"
req owner DELETE "//x.y/api/emails/$BOX" --path-as-is -H 'RSC: 1' -H "Origin: $B"; w404 "owner DELETE //x.y/api/emails/<id> [RSC]"
req owner DELETE "$DP/api/emails/${BOX}Xjson" -H "Origin: $B"; w404 "owner DELETE /_next/data/…/api/emails/<id>Xjson"
req owner GET /api/emails; present SEC "第 12 节之后 owner 的邮箱仍在" "ownerbox"
req owner GET /api/webhook; absent SEC "第 12 节之后 owner 的 webhook 没被改" "h-sec12"
# 写法规范的 data 地址，Next 会先还原成 /api/…，仍由中间件的 /api 分支处理
req - GET "$DP/api/api-keys.json" -H 'x-nextjs-data: 1' -H "$BADKEY"; expect SEC "匿名 GET /_next/data/<id>/api/api-keys.json（规范写法）" "403"; present SEC "规范写法由中间件的 /api 分支拒绝" "无权限查看"
req - GET "$DP/api/emails.json" -H 'x-nextjs-data: 1'; expect SEC "匿名 GET /_next/data/<id>/api/emails.json（规范写法）" "401"
# 编码过的前缀路由器不认，同样到不了 handler
for v in "/%5Fnext/data/$BUILD_ID/api/api-keysXjson" "/_next%2Fdata/$BUILD_ID/api/api-keysXjson" "/%2Fx.y/api/config" "/%2f/x.y/api/config/.rsc" "/x.y/api/config" "/en//x.y/api/config"; do
  req - GET "$v" --path-as-is -H 'x-nextjs-data: 1' -H 'RSC: 1' -H "$BADKEY"; expect SEC "匿名 GET $v" "$DENY"
  absent SEC "匿名 GET $v" "此接口不支持 API Key"; absent SEC "匿名 GET $v" "emailDomains"
  req owner GET "$v" --path-as-is -H 'RSC: 1'; absent SEC "owner GET $v [RSC]" "ownerbox"; absent SEC "owner GET $v [RSC]" "emailDomains"
done
# 正常要用到的 /_next 地址、静态文件、页面不受影响
for p in /manifest.json /sw.js /icons/icon-192x192.png /zh-CN/login /en; do req - GET "$p"; expect FUNC "GET $p" "200"; done
req - GET "/zh-CN/login?_rsc=abc12" -H 'RSC: 1' -H 'Next-Router-Prefetch: 1'; expect FUNC "GET /zh-CN/login（客户端导航的 RSC 请求）" "200"
req - GET /; expect FUNC "GET /（跳到语言前缀）" "307"

echo "== 13. 图片代理接口 /_next/image 已关闭 =="
# next-on-pages 自带的 /_next/image 只判断 url 是不是以 / 开头就当成本站地址，而 /\host/…、/<TAB>/host/… 这类写法
# 经 URL 解析后指向任意外部主机：worker 会去抓取，并把对方的响应头（含 Set-Cookie）原样转发给访问者。
# 本站头像是 data: 地址，用不到这个接口：根目录 _routes.json 把 /_next/image* 排除在 worker 之外，请求只会得到静态 404。
HP="${B#*://}"
img_closed() { # img_closed <name>：没有到达图片处理代码
  expect SEC "$1" "404|405|307|308"; absent SEC "$1" "csrfToken"; absent SEC "$1" "start_url"
  if tr -d '\r' < "$T/hdr" 2>/dev/null | grep -qi '^set-cookie:'; then bad "[SEC] $1 -> 响应带了 Set-Cookie"; else ok "[SEC] $1（没有 Set-Cookie）"; fi
  if tr -d '\r' < "$T/hdr" 2>/dev/null | grep -qi '^content-disposition: attachment'; then bad "[SEC] $1 -> 是图片代理的响应（Content-Disposition: attachment）"; else ok "[SEC] $1（不是图片代理的响应）"; fi
}
for q in "url=%2Ficons%2Ficon-192x192.png&w=64&q=75" "url=%2Fmanifest.json&w=64&q=75" "url=%2Fapi%2Fauth%2Fcsrf&w=64&q=75" \
         "url=%2F%5C${HP}%2Fapi%2Fauth%2Fcsrf&w=64&q=75" "url=%2F%5C${HP}%2Fmanifest.json&w=64&q=75" "url=%2F%09%2F${HP}%2Fapi%2Fauth%2Fcsrf&w=64&q=75" \
         "url=%5C%5C${HP}%2Fapi%2Fauth%2Fcsrf&w=64&q=75" "url=%2F%2F${HP}%2Fapi%2Fauth%2Fcsrf&w=64&q=75" "url=http%3A%2F%2F${HP}%2Fapi%2Fauth%2Fcsrf&w=64&q=75"; do
  for base in /_next/image /_next/image/ /_next/imageX /_next/image/x/y /_next/image.png; do
    req - GET "$base?$q" --path-as-is; img_closed "匿名 GET $base?$q"
  done
  req owner GET "/_next/image?$q"; img_closed "owner GET /_next/image?$q"
  req - POST "/_next/image?$q" -H "$J" -d '{}'; img_closed "匿名 POST /_next/image?$q"
done
# 大小写、编码过的写法不会被排除规则匹配，但 worker 里的判断区分大小写、也不解码，同样到不了图片处理代码
for base in /_NEXT/IMAGE /_next/IMAGE /_next/%69mage /_next%2Fimage //_next/image /x/../_next/image "/_next/./image"; do
  req - GET "$base?url=%2F%5C${HP}%2Fapi%2Fauth%2Fcsrf&w=64&q=75" --path-as-is; img_closed "匿名 GET $base（变体）"
  req - GET "$base?url=%2Fmanifest.json&w=64&q=75" --path-as-is; img_closed "匿名 GET $base（变体，本站文件）"
done
# 页面里的图片不依赖这个接口
req owner GET /zh-CN/profile; expect FUNC "owner GET /zh-CN/profile" "200"; absent FUNC "个人中心页面不引用 /_next/image" "/_next/image"
req - GET /zh-CN/login; expect FUNC "GET /zh-CN/login" "200"; absent FUNC "登录页不引用 /_next/image" "/_next/image"
for p in /icons/icon-192x192.png /manifest.json /favicon.ico; do req - GET "$p"; expect FUNC "GET $p（静态文件照常）" "200"; done

echo "== 14. 登录错误提示与 404 页面 =="
for badu in "owner1:wrong-password-123" "nonexistent_user_xyz:$PW"; do
  u="${badu%%:*}"; p="${badu#*:}"; jar="$T/badlogin.jar"; rm -f "$jar"
  csrf=$(curl -s -m 30 -H "$XFP" -c "$jar" -b "$jar" "$B/api/auth/csrf" | jq -r '.csrfToken // empty')
  CODE=$(curl -s -m 30 -o "$T/body" -w '%{http_code}' -c "$jar" -b "$jar" -X POST "$B/api/auth/callback/credentials" \
    -H 'X-Auth-Return-Redirect: 1' -H "$XFP" \
    --data-urlencode "csrfToken=$csrf" --data-urlencode "username=$u" --data-urlencode "password=$p" \
    --data-urlencode "callbackUrl=$B/")
  present NEW "错误凭据 ($u) 返回 CredentialsSignin" "error=CredentialsSignin"
  present NEW "错误凭据 ($u) 返回 invalid_credentials" "code=invalid_credentials"
  absent NEW "错误凭据 ($u) 不返回 Configuration" "error=Configuration"
  req - GET /api/auth/session -b "$jar"; absent SEC "错误凭据 ($u) 不会建立会话" '"user"'
done
req - GET /zh-CN/this-page-does-not-exist; expect NEW "不存在的页面返回 404" "404"
present NEW "404 页面包含完整 html 根元素" "<html"
present NEW "404 页面包含 404 文案" "404"
present NEW "404 页面声明 noindex" "noindex"
req - GET /this-page-does-not-exist; expect FUNC "无语言前缀的不存在路径先跳语言前缀" "307"

echo
echo "== 结果 [$LABEL]: 通过 $PASS, 失败 $FAIL (本地模拟器故障重试 $RETRIES 次) =="
[ "$FAIL" -eq 0 ]
