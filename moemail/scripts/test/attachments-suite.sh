#!/usr/bin/env bash
# 附件与转发的本机测试。只对本机实例使用；由 run-local.sh 调用（也可以 SUITES=attachments 单独跑）。
# 收信 Worker 通过 email-harness.ts 直接调用（真实代码，模拟的 D1/KV）。
#   STATE=<pages dev 的 --persist-to 目录> scripts/test/attachments-suite.sh <BASE_URL>
set -uo pipefail
B="${1:?base url}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${STATE:?需要环境变量 STATE}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
case "$B" in http://127.0.0.1:*|http://localhost:*) ;; *) echo "只允许对本机实例运行" >&2; exit 2;; esac

PASS=0; FAIL=0; CODE=""; XFP="X-Forwarded-Proto: http"; J='Content-Type: application/json'
req() { # req <jar|-> <METHOD> <path> [curl 参数...]
  local jar="$1" method="$2" path="$3"; shift 3
  local args=(-s -m 30 -o "$T/body" -D "$T/hdr" -w '%{http_code}' -X "$method" -H "$XFP")
  [ "$jar" != "-" ] && args+=(-b "$T/$jar.jar")
  local try
  for try in 1 2 3 4; do
    CODE=$(curl "${args[@]}" "$@" "$B$path" 2>/dev/null) || CODE="000"
    if [ "$CODE" = "000" ] || { [ "$CODE" = "503" ] && grep -q "restarted mid-request" "$T/body" 2>/dev/null; }; then sleep 0.3; continue; fi
    break
  done
}
body() { head -c 200 "$T/body" 2>/dev/null | tr '\n' ' '; }
ok()  { PASS=$((PASS+1)); [ -n "${VERBOSE:-}" ] && echo "  ok   $1"; return 0; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1"; }
expect() { if [[ "$CODE" =~ ^($2)$ ]]; then ok "$1 -> $CODE"; else bad "$1 -> $CODE (期望 $2) | $(body)"; fi; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 -> 实际 [$2]，期望 [$3]"; fi; }
header() { grep -i "^$1:" "$T/hdr" | head -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ //'; }
login() { # login <jar> <user> <pass>
  local jar="$T/$1.jar" csrf; rm -f "$jar"
  csrf=$(curl -s -m 30 -H "$XFP" -c "$jar" -b "$jar" "$B/api/auth/csrf" | jq -r '.csrfToken // empty')
  curl -s -m 30 -o /dev/null -c "$jar" -b "$jar" -X POST "$B/api/auth/callback/credentials" \
    -H 'X-Auth-Return-Redirect: 1' -H "$XFP" \
    --data-urlencode "csrfToken=$csrf" --data-urlencode "username=$2" --data-urlencode "password=$3" \
    --data-urlencode "callbackUrl=$B/"
  req "$1" GET /api/auth/session
  jq -r '.user.id // empty' "$T/body" 2>/dev/null
}
# 测试桩打包到 node_modules 下面，运行时才找得到依赖
HARNESS="$ROOT/node_modules/.cache/moemail-test/email-harness.mjs"
mkdir -p "$(dirname "$HARNESS")"
(cd "$ROOT" && node -e "
  const esbuild = require(require.resolve('esbuild', { paths: [require.resolve('wrangler')] }))
  esbuild.buildSync({ entryPoints: ['scripts/test/email-harness.ts'], bundle: true, platform: 'node',
    format: 'esm', packages: 'external', outfile: process.argv[1], logLevel: 'error' })
" "$HARNESS") || { echo "打包测试桩失败"; exit 3; }
harness() { (cd "$ROOT" && STATE="$STATE" node "$HARNESS" "$@" 2>"$T/harness.err") | sed -n 's/^RESULT //p' | tail -1; }
deliver() { harness deliver "$@"; } # deliver <from> <to> <eml> [投递几次]
keys_of() { harness keys | jq -r --arg p "att/$1/" '[.[] | select(.name | startswith($p))] | length'; }
# 删除接口在返回响应之后才删 KV 里的附件，等一会儿再数
keys_gone() { local n i; for i in 1 2 3 4 5 6 7 8 9 10; do n=$(keys_of "$1"); [ "$n" = 0 ] && break; sleep 0.5; done; echo "$n"; }
latest_message() { # latest_message <jar> <box> <subject>
  req "$1" GET "/api/emails/$2"; jq -r --arg s "$3" '[.messages[] | select(.subject == $s)][0].id // empty' "$T/body"
}

echo "== 附件与转发 ($B) =="
python3 -I - "$T" <<'EOF'
import base64, sys
from email.message import EmailMessage
out = sys.argv[1]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
PDF = b"%PDF-1.4\n% moemail attachment test\n" + bytes(range(256)) * 40
open(f"{out}/logo.png", "wb").write(PNG); open(f"{out}/report.pdf", "wb").write(PDF)
m = EmailMessage()
m["From"] = "sender@example.com"; m["To"] = "attbox@moemail.app"; m["Subject"] = "Attachment test"
m.set_content("plain body")
m.add_alternative('<p>hello <img src="cid:logo123@example.com" alt="logo"></p>', subtype="html")
m.get_payload()[1].add_related(PNG, maintype="image", subtype="png", cid="<logo123@example.com>", filename="logo.png")
m.add_attachment(PDF, maintype="application", subtype="pdf", filename="报告 2026.pdf")
m.add_attachment(b"<script>alert(document.cookie)</script>", maintype="text", subtype="html", filename="evil.html")
m.add_attachment(b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', maintype="image", subtype="svg+xml", filename="x.svg")
m.add_attachment(b"\x00\x01binary", maintype="application", subtype="octet-stream")
m.add_attachment(b"MZ fake", maintype="application", subtype="octet-stream", filename="invoice\u202efdp.exe")
open(f"{out}/mixed.eml", "wb").write(bytes(m))
# 22 张内嵌图片排在前面、一个 PDF 附件排在最后：名额（每封 20 个）应当先给 PDF
r = EmailMessage()
r["From"] = "sender@example.com"; r["To"] = "attbox@moemail.app"; r["Subject"] = "Many inline images"
r.set_content("plain")
r.add_alternative("".join(f'<img src="cid:img{i}@example.com">' for i in range(22)), subtype="html")
for i in range(22):
    r.get_payload()[1].add_related(PNG, maintype="image", subtype="png", cid=f"<img{i}@example.com>", filename=f"img{i}.png")
r.add_attachment(PDF, maintype="application", subtype="pdf", filename="last.pdf")
open(f"{out}/many-inline.eml", "wb").write(bytes(r))
p = EmailMessage()
p["From"] = "sender@example.com"; p["To"] = "attbox@moemail.app"; p["Subject"] = "Plain test"
p.set_content("no attachments here")
open(f"{out}/plain.eml", "wb").write(bytes(p))
EOF
sha() { sha256sum "$1" | cut -d' ' -f1; }

PW='Passw0rd-local-test'
# owner1：安全回归套件建的皇帝账号；单独跑时在全新实例上建它，并让它成为皇帝（已有皇帝时 init-emperor 什么也不做）
for u in owner1 attother1 attvictim1; do req - POST /api/auth/register -H "$J" -d "{\"username\":\"$u\",\"password\":\"$PW\"}"; done
OWNER=$(login owner owner1 "$PW"); req owner GET /api/roles/init-emperor
OTHER=$(login other attother1 "$PW"); VICTIM=$(login victim attvictim1 "$PW")
[ -n "$OWNER" ] && [ -n "$OTHER" ] && [ -n "$VICTIM" ] || { echo "登录失败，无法继续（本机实例要开着注册）"; exit 3; }
for id in "$OTHER" "$VICTIM"; do req owner POST /api/roles/promote -H "$J" -H "Origin: $B" -d "{\"userId\":\"$id\",\"roleName\":\"knight\"}"; done
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"attbox","expiryTime":0,"domain":"moemail.app"}'
BOX=$(jq -r '.id // empty' "$T/body"); ADDR=$(jq -r '.email // empty' "$T/body")
req other POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"attother","expiryTime":0,"domain":"moemail.app"}'
OTHERBOX=$(jq -r '.id // empty' "$T/body"); OTHERADDR=$(jq -r '.email // empty' "$T/body")
[ -n "$BOX" ] && [ -n "$OTHERBOX" ] || { echo "建邮箱失败：$(body)"; exit 3; }

echo "-- 收信：已注册的地址存附件，未注册的地址转发"
R=$(deliver sender@example.com "$ADDR" "$T/mixed.eml"); check "带附件的信投给已注册地址，不转发" "$(jq -r .forwardedTo <<<"$R")" null
R=$(deliver sender@example.com "nobody-$RANDOM@moemail.app" "$T/plain.eml")
check "未注册地址的信转发到 FORWARD_TO" "$(jq -r .forwardedTo <<<"$R")" "$(jq -r '.vars.FORWARD_TO // "null"' "$ROOT/wrangler.email.json")"
R=$(deliver sender@example.com "$(tr '[:lower:]' '[:upper:]' <<<"$ADDR")" "$T/plain.eml"); check "收件地址大小写不同也算已注册" "$(jq -r .forwardedTo <<<"$R")" null
R=$(deliver sender@example.com "$OTHERADDR" "$T/mixed.eml"); check "投给另一个用户的邮箱" "$(jq -r .forwardedTo <<<"$R")" null
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"attexpired","expiryTime":3600000,"domain":"moemail.app"}'
EXPBOX=$(jq -r '.id // empty' "$T/body"); EXPADDR=$(jq -r '.email // empty' "$T/body"); harness expire "$EXPBOX" >/dev/null
R=$(deliver sender@example.com "$EXPADDR" "$T/mixed.eml")
check "已过期、还没被清理的邮箱按未注册处理（转发）" "$(jq -r .forwardedTo <<<"$R")" "$(jq -r '.vars.FORWARD_TO // "null"' "$ROOT/wrangler.email.json")"

MSG=$(latest_message owner "$BOX" "Attachment test"); OTHERMSG=$(latest_message other "$OTHERBOX" "Attachment test")
[ -n "$MSG" ] && [ -n "$OTHERMSG" ] || { echo "没找到投递的邮件：$(body)"; cat "$T/harness.err" | tail -5; exit 3; }
req owner GET "/api/emails/$BOX"
check "列表不带正文（正文要读单封邮件）" "$(jq -r '[.messages[] | has("content") or has("html")] | any' "$T/body")" false
check "列表标出有附件" "$(jq -r --arg id "$MSG" '.messages[] | select(.id == $id) | .has_attachments' "$T/body")" true
check "没附件的信不标" "$(jq -r '[.messages[] | select(.subject == "Plain test")][0].has_attachments' "$T/body")" false
req owner GET "/api/emails/$BOX/$MSG"; expect "读邮件" 200
check "附件个数" "$(jq -r '.message.attachments | length' "$T/body")" 6
check "附件都存下了" "$(jq -r '[.message.attachments[].stored] | all' "$T/body")" true
check "内嵌图片标为 inline" "$(jq -r '.message.attachments[0] | "\(.filename) \(.inline) \(.contentId)"' "$T/body")" "logo.png true logo123@example.com"
check "中文文件名" "$(jq -r '.message.attachments[1].filename' "$T/body")" "报告 2026.pdf"
check "没有文件名的附件给默认名" "$(jq -r '.message.attachments[4].filename' "$T/body")" "attachment-5.bin"
check "文件名里的双向控制符被去掉（不能把 .exe 显示成 .pdf）" "$(jq -r '.message.attachments[5].filename' "$T/body")" "invoicefdp.exe"
check "永久邮箱的附件不设到期" "$(harness keys | jq -r --arg p "att/$MSG/" '[.[] | select(.name | startswith($p)) | .expiration] | unique | tostring')" "[null]"

echo "-- 下载：内容、类型和防执行的响应头"
U="/api/emails/$BOX/$MSG/attachments"
req owner GET "$U/0"; expect "下载内嵌图片" 200
check "图片按原类型返回" "$(header Content-Type)" "image/png"; check "图片内容一致" "$(sha "$T/body")" "$(sha "$T/logo.png")"
req owner GET "$U/1"; expect "下载 PDF" 200
check "PDF 内容一致" "$(sha "$T/body")" "$(sha "$T/report.pdf")"
check "非图片一律按二进制返回" "$(header Content-Type)" "application/octet-stream"
check "中文文件名按 RFC 5987 编码" "$(header Content-Disposition)" "attachment; filename=\"__ 2026.pdf\"; filename*=UTF-8''%E6%8A%A5%E5%91%8A%202026.pdf"
req owner GET "$U/2"; expect "下载 HTML 附件" 200
check "HTML 附件不按网页返回" "$(header Content-Type)" "application/octet-stream"
check "HTML 附件强制下载" "$(header Content-Disposition | cut -d';' -f1)" "attachment"
check "禁止嗅探类型" "$(header X-Content-Type-Options)" "nosniff"
req owner GET "$U/3"; check "SVG 不按图片返回（可带脚本）" "$(header Content-Type)" "application/octet-stream"
for bad_index in 6 99 abc -1 1.0 0x1 "1%2F..%2F0"; do req owner GET "$U/$bad_index"; expect "不存在的附件序号 $bad_index" "404"; done

echo "-- 权限"
req - GET "$U/1"; expect "匿名下载" 401
req - GET "$U/1" -H "X-User-Id: $OWNER"; expect "匿名 + 伪造 X-User-Id" 401
req other GET "$U/1"; expect "别人下载" 403
req other GET "/api/emails/$OTHERBOX/$MSG/attachments/1"; expect "把别人的邮件 ID 接在自己邮箱下" 404
req owner POST /api/api-keys -H "$J" -H "Origin: $B" -d '{"name":"att-key"}'; KEY=$(jq -r '.key // empty' "$T/body")
req - GET "$U/1" -H "X-API-Key: $KEY"; expect "主人的 API Key 下载" 200

echo "-- 分享链接"
req owner POST "/api/emails/$BOX/share" -H "$J" -H "Origin: $B" -d '{"expiresIn":0}'; ST=$(jq -r '.token // empty' "$T/body")
req - GET "/api/shared/$ST/messages/$MSG"; check "分享邮箱里读邮件带附件信息" "$(jq -r '.message.attachments | length' "$T/body")" 6
req - GET "/api/shared/$ST/messages/$MSG/attachments/1"; expect "凭邮箱分享链接下载" 200
check "分享下载内容一致" "$(sha "$T/body")" "$(sha "$T/report.pdf")"
req - GET "/api/shared/$ST/messages/$OTHERMSG/attachments/1"; expect "分享链接拿不到别的邮箱的附件" 404
req - GET "/api/shared/xxxxxxxxxxxxxxxx/messages/$MSG/attachments/1"; expect "无效的分享链接" 404
req owner POST "/api/emails/$BOX/messages/$MSG/share" -H "$J" -H "Origin: $B" -d '{"expiresIn":0}'; MT=$(jq -r '.token // empty' "$T/body")
req - GET "/api/shared/message/$MT"; check "分享单封邮件带附件信息" "$(jq -r '.message.attachments | length' "$T/body")" 6
req - GET "/api/shared/message/$MT/attachments/2"; expect "凭单封分享链接下载" 200
check "分享下载同样按二进制返回" "$(header Content-Type)" "application/octet-stream"
req - GET "/api/shared/message/xxxxxxxxxxxxxxxx/attachments/0"; expect "无效的单封分享链接" 404

echo "-- 删除时一起删掉 KV 里的附件"
check "删除前有 6 个附件" "$(keys_of "$MSG")" 6
req owner DELETE "/api/emails/$BOX/$MSG" -H "Origin: $B"; expect "删除单封邮件" 200
check "删邮件后附件也没了" "$(keys_gone "$MSG")" 0
req - GET "/api/shared/message/$MT/attachments/1"; expect "删了的邮件，分享链接也下不到" "404"
deliver sender@example.com "$ADDR" "$T/mixed.eml" >/dev/null; MSG2=$(latest_message owner "$BOX" "Attachment test")
check "再投一封" "$(keys_of "$MSG2")" 6
deliver sender@example.com "$ADDR" "$T/many-inline.eml" >/dev/null; MANY=$(latest_message owner "$BOX" "Many inline images")
req owner GET "/api/emails/$BOX/$MANY"
check "内嵌图片很多时，排在最后的 PDF 附件也存下了" "$(jq -r '.message.attachments[] | select(.filename == "last.pdf") | .stored' "$T/body")" true
check "每封最多存 20 个" "$(jq -r '[.message.attachments[] | select(.stored)] | length' "$T/body")" 20
check "其余内嵌图片记为未保存" "$(jq -r '[.message.attachments[] | select(.stored | not)] | length' "$T/body")" 3
req owner DELETE "/api/emails/$BOX" -H "Origin: $B"; expect "删除邮箱" 200
check "删邮箱后其中邮件的附件也没了" "$(keys_gone "$MSG2")" 0
check "删邮箱后另一封的附件也没了" "$(keys_gone "$MANY")" 0
req victim POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"attvictim","expiryTime":3600000,"domain":"moemail.app"}'
VBOX=$(jq -r '.id // empty' "$T/body"); VADDR=$(jq -r '.email // empty' "$T/body")
deliver sender@example.com "$VADDR" "$T/mixed.eml" >/dev/null; VMSG=$(latest_message victim "$VBOX" "Attachment test")
check "临时邮箱的附件有 6 个" "$(keys_of "$VMSG")" 6
EXP=$(harness keys | jq -r --arg p "att/$VMSG/" '[.[] | select(.name | startswith($p)) | .expiration][0]')
NOW=$(date +%s)
if [ "$EXP" != null ] && [ "$EXP" -gt $((NOW + 7000)) ] && [ "$EXP" -lt $((NOW + 7400)) ]; then ok "临时邮箱的附件在邮箱到期一小时后到期"; else bad "临时邮箱附件的到期时间 $EXP，现在 $NOW"; fi
req owner DELETE "/api/users/$VICTIM" -H "Origin: $B"; expect "删除用户" 200
check "删用户后其邮件的附件也没了" "$(keys_gone "$VMSG")" 0

echo "-- 清空邮箱"
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"attclear","expiryTime":0,"domain":"moemail.app"}'
CBOX=$(jq -r '.id // empty' "$T/body"); CADDR=$(jq -r '.email // empty' "$T/body")
deliver sender@example.com "$CADDR" "$T/mixed.eml" >/dev/null; deliver sender@example.com "$CADDR" "$T/plain.eml" >/dev/null
CMSG=$(latest_message owner "$CBOX" "Attachment test")
check "清空前有 6 个附件" "$(keys_of "$CMSG")" 6
req other DELETE "/api/emails/$CBOX/messages" -H "Origin: $B"; expect "别人不能清空这个邮箱" 403
req owner DELETE "/api/emails/$CBOX/messages?type=sent" -H "Origin: $B"; expect "清空发出的邮件" 200
check "没有发出的邮件，一封也没删" "$(jq -r .deleted "$T/body")" 0
req owner DELETE "/api/emails/$CBOX/messages" -H "Origin: $B"; expect "清空收到的邮件" 200
check "删掉了 2 封" "$(jq -r .deleted "$T/body")" 2
req owner GET "/api/emails/$CBOX"; check "清空后列表是空的" "$(jq -r '.messages | length' "$T/body")" 0
check "清空后附件也没了" "$(keys_gone "$CMSG")" 0

echo "-- 未读状态"
# unread_of <jar> <box> [请求头]。接口没返回 counts（出错了）时输出 ERR，免得“期望 0”的检查在接口失败时也通过
unread_of() { req "$1" GET /api/emails/unread ${3:+-H "$3"}; jq -r --arg b "$2" 'if has("counts") then (.counts[$b] // 0) else "ERR" end' "$T/body"; }
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"attunread","expiryTime":0,"domain":"moemail.app"}'
UBOX=$(jq -r '.id // empty' "$T/body"); UADDR=$(jq -r '.email // empty' "$T/body")
deliver sender@example.com "$UADDR" "$T/plain.eml" >/dev/null; deliver sender@example.com "$UADDR" "$T/plain.eml" >/dev/null
check "新到的两封邮件算未读" "$(unread_of owner "$UBOX")" 2
check "别人的未读数里没有这个邮箱" "$(unread_of other "$UBOX")" 0
req owner GET "/api/emails/$UBOX"; UMSG=$(jq -r '.messages[0].id // empty' "$T/body")
check "列表里两封都标着未读" "$(jq -r '[.messages[].read_at == null] | all' "$T/body")" true
req owner POST "/api/emails/$UBOX/share" -H "$J" -H "Origin: $B" -d '{"expiresIn":0}'; UT=$(jq -r '.token // empty' "$T/body")
req - GET "/api/shared/$UT/messages"; check "分享链接的列表不带已读状态" "$(jq -r '[.messages[] | has("read_at")] | any' "$T/body")" false
req - GET "/api/shared/$UT/messages/$UMSG"; expect "通过分享链接读这封邮件" 200
check "分享链接的邮件不带已读状态" "$(jq -r '.message | has("read_at")' "$T/body")" false
req owner POST "/api/emails/$UBOX/messages/$UMSG/share" -H "$J" -H "Origin: $B" -d '{"expiresIn":0}'; UMT=$(jq -r '.token // empty' "$T/body")
req - GET "/api/shared/message/$UMT"; expect "通过单封分享链接读这封邮件" 200
check "单封分享链接的邮件不带已读状态" "$(jq -r '.message | has("read_at")' "$T/body")" false
req other GET "/api/emails/$UBOX/$UMSG"; expect "别人读不到这封邮件" 403
req other GET "/api/emails/$OTHERBOX/$UMSG"; expect "把这封邮件的 ID 接在自己邮箱下也读不到" 404
check "分享链接和别人的请求都不算读过" "$(unread_of owner "$UBOX")" 2
req owner GET "/api/emails/$UBOX/$UMSG"; expect "主人读这封邮件" 200
check "第一次读，返回的是读之前的状态（未读）" "$(jq -r '.message.read_at' "$T/body")" null
check "读过一封，未读数减一" "$(unread_of owner "$UBOX")" 1
req owner GET "/api/emails/$UBOX"; check "列表里这封变成已读" "$(jq -r --arg id "$UMSG" '.messages[] | select(.id == $id) | .read_at != null' "$T/body")" true
req owner GET "/api/emails/$UBOX/$UMSG"; check "再读一次，返回已读时间" "$(jq -r '.message.read_at != null' "$T/body")" true
req other PATCH "/api/emails/$UBOX/messages" -H "$J" -H "Origin: $B" -d '{"read":true}'; expect "别人不能把这个邮箱标为已读" 403
check "别人标记之后未读数没变" "$(unread_of owner "$UBOX")" 1
deliver sender@example.com "$UADDR" "$T/plain.eml" >/dev/null
req owner GET "/api/emails/$UBOX"; OLDEST=$(jq -r '.messages[-1].received_at' "$T/body")
check "又来一封，未读的是最早和最新的两封" "$(jq -r '[.messages[].read_at == null] | join(",")' "$T/body")" "true,false,true"
req owner PATCH "/api/emails/$UBOX/messages" -H "$J" -H "Origin: $B" -d "{\"read\":true,\"before\":$OLDEST}"; expect "只标到最早那封为止" 200
req owner GET "/api/emails/$UBOX"; check "比 before 新的那封还是未读" "$(jq -r '[.messages[].read_at == null] | join(",")' "$T/body")" "true,false,false"
req owner PATCH "/api/emails/$UBOX/messages" -H "$J" -H "Origin: $B" -d '{"read":true,"before":"2026-01-01"}'; expect "before 不是数字被拒" 400
check "被拒的请求没有改动" "$(unread_of owner "$UBOX")" 1
req owner PATCH "/api/emails/$UBOX/messages" -H "$J" -H "Origin: $B" -d '{"read":true}'; expect "全部标为已读" 200
check "全部已读后没有未读" "$(unread_of owner "$UBOX")" 0
deliver sender@example.com "$UADDR" "$T/plain.eml" >/dev/null
check "API Key 也能查未读数" "$(unread_of - "$UBOX" "X-API-Key: $KEY")" 1
req - GET "/api/emails/$UBOX" -H "X-API-Key: $KEY"; UMSG2=$(jq -r '.messages[0].id // empty' "$T/body")
req - GET "/api/emails/$UBOX/$UMSG2" -H "X-API-Key: $KEY"; expect "用 API Key 读新邮件" 200
check "用 API Key 读过也算已读" "$(unread_of owner "$UBOX")" 0
deliver sender@example.com "$UADDR" "$T/plain.eml" 11 >/dev/null
req owner GET "/api/emails/$UBOX"; check "一次投 11 封都到了" "$(jq -r '[.messages[] | select(.read_at == null)] | length' "$T/body")" 11
check "未读数每个邮箱最多数到 10" "$(unread_of owner "$UBOX")" 10

echo "-- 邮件列表：总数和翻页"
# walk <jar> <路径> <时间字段> [别的参数]：带 total=false 从第一页翻到最后一页（网页端翻页也是这样），
# 输出“页数 邮件数 不重复的邮件数 是否按（时间, id）倒序”
walk() {
  local jar="$1" path="$2" field="$3" extra="${4:+&$4}" cursor="" all="[]" n=0
  while [ "$n" -lt 10 ]; do
    req "$jar" GET "$path?total=false$extra${cursor:+&cursor=$(jq -rn --arg c "$cursor" '$c | @uri')}"
    [ "$CODE" = 200 ] || { echo "HTTP $CODE"; return; }
    all=$(jq -c --argjson a "$all" --arg f "$field" '$a + [.messages[] | {id, t: .[$f]}]' "$T/body")
    cursor=$(jq -r '.nextCursor // empty' "$T/body"); n=$((n+1))
    [ -n "$cursor" ] || break
  done
  jq -rn --argjson a "$all" --arg n "$n" '"\($n) \($a | length) \($a | map(.id) | unique | length) \($a == ($a | sort_by(.t, .id) | reverse))"'
}
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"attpage","expiryTime":0,"domain":"moemail.app"}'
PBOX=$(jq -r '.id // empty' "$T/body"); PADDR=$(jq -r '.email // empty' "$T/body")
deliver sender@example.com "$PADDR" "$T/plain.eml" 45 >/dev/null
# 收到的和发出的各二十多封，每个列表按 id 每 7 封一组、同组同一毫秒（见 email-harness.ts 的 retime）：
# 两个列表都要翻两页，第二页里既有和第一页最后一封同一毫秒的，也有时间更早、id 更大的
check "邮件时间改成成组重复" "$(harness retime "$PBOX" 1767225600000 | jq -r .ok)" true
req owner POST /api/config/email-service -H "$J" -H "Origin: $B" -d '{"enabled":true,"apiKey":"re_local_test","roleLimits":{}}'; expect "临时打开发件服务（查看发件列表要它）" 200
req owner GET "/api/emails/$PBOX"; RTOTAL=$(jq -r '.total' "$T/body")
req owner GET "/api/emails/$PBOX?type=sent"; STOTAL=$(jq -r '.total' "$T/body")
check "收到的和发出的总数加起来是 45" "$((RTOTAL + STOTAL))" 45
check "两个列表都不止一页" "$([ "$RTOTAL" -gt 20 ] && [ "$STOTAL" -gt 20 ] && echo yes)" yes
check "收件列表翻到底：不重不漏、顺序对" "$(walk owner "/api/emails/$PBOX" received_at)" "2 $RTOTAL $RTOTAL true"
check "发件列表翻到底：不重不漏、顺序对" "$(walk owner "/api/emails/$PBOX" sent_at type=sent)" "2 $STOTAL $STOTAL true"
req owner GET "/api/emails/$PBOX?total=false"; check "total=false 时不带总数" "$(jq -r 'has("total")' "$T/body")" false
check "total=false 时第一页照常返回" "$(jq -r '.messages | length' "$T/body")" 20
req - GET "/api/emails/$PBOX?total=false" -H "X-API-Key: $KEY"; expect "API Key 带 total=false 读列表" 200
check "API Key 带 total=false 时也不带总数" "$(jq -r 'if has("messages") then has("total") else "ERR" end' "$T/body")" false
req owner POST "/api/emails/$PBOX/share" -H "$J" -H "Origin: $B" -d '{"expiresIn":0}'; PT=$(jq -r '.token // empty' "$T/body")
req - GET "/api/shared/$PT/messages"; check "分享链接的列表总数只数收到的" "$(jq -r '.total' "$T/body")" "$RTOTAL"
check "分享链接的列表翻到底：不重不漏、顺序对" "$(walk - "/api/shared/$PT/messages" received_at)" "2 $RTOTAL $RTOTAL true"
req - GET "/api/shared/$PT/messages?total=false"; expect "分享链接带 total=false 读列表" 200
check "分享链接 total=false 时不带总数" "$(jq -r 'if has("messages") then has("total") else "ERR" end' "$T/body")" false
req owner POST /api/config/email-service -H "$J" -H "Origin: $B" -d '{"enabled":false,"apiKey":"","roleLimits":{}}'; expect "关回发件服务" 200

echo "-- 邮箱备注与搜索（含 LIKE 通配符转义）"
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"notebox1","expiryTime":0,"domain":"moemail.app","note":"GitHub 100%_test\\slash"}'
expect "创建带备注永久邮箱" 200
NBOX1=$(jq -r '.id // empty' "$T/body"); NADDR1=$(jq -r '.email // empty' "$T/body")
check "创建返回备注原文" "$(jq -r '.note' "$T/body")" 'GitHub 100%_test\slash'
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"notebox2","expiryTime":3600000,"domain":"moemail.app","note":"账单通知"}'
expect "创建带备注临时邮箱" 200
NBOX2=$(jq -r '.id // empty' "$T/body")
req owner POST /api/emails/generate -H "$J" -H "Origin: $B" -d '{"name":"notebox3","expiryTime":0,"domain":"moemail.app"}'
expect "创建无备注邮箱" 200
NBOX3=$(jq -r '.id // empty' "$T/body")

req owner GET '/api/emails?q=GitHub'
check "按备注搜邮箱只命中 notebox1" "$(jq -r '[.emails[].id] | join(",")' "$T/body")" "$NBOX1"
req owner GET '/api/emails?q=100%25_test'
check "按含 % 和 _ 的备注搜索只命中 notebox1" "$(jq -r '[.emails[].id] | join(",")' "$T/body")" "$NBOX1"
req owner GET '/api/emails?q=%25'
check "搜单个 % 不当通配符（只命中 notebox1）" "$(jq -r '[.emails[].id] | join(",")' "$T/body")" "$NBOX1"
req owner GET '/api/emails?q=_'
check "搜单个 _ 不当通配符（只命中 notebox1）" "$(jq -r '[.emails[].id] | join(",")' "$T/body")" "$NBOX1"
req owner GET '/api/emails?q=%5C'
check "搜反斜杠只命中 notebox1" "$(jq -r '[.emails[].id] | join(",")' "$T/body")" "$NBOX1"
req owner GET '/api/emails?q=notebox2'
check "按地址搜邮箱只命中 notebox2" "$(jq -r '[.emails[].id] | join(",")' "$T/body")" "$NBOX2"
req owner GET '/api/emails?q=NoSuchBoxKeyword999'
check "搜不存在的邮箱关键词返回空" "$(jq -r '.emails | length' "$T/body")" 0

req owner PATCH "/api/emails/$NBOX3" -H "$J" -H "Origin: $B" -d '{"note":"  云服务账单  "}'
expect "PATCH 修改邮箱备注" 200
check "PATCH 自动去除首尾空白" "$(jq -r '.note' "$T/body")" "云服务账单"
req owner GET "/api/emails?q=$(jq -rn --arg q '云服务' '$q | @uri')"
check "改完备注后可按新备注搜到" "$(jq -r '[.emails[].id] | join(",")' "$T/body")" "$NBOX3"
req owner PATCH "/api/emails/$NBOX3" -H "$J" -H "Origin: $B" -d '{"note":"   "}'
expect "PATCH 空白串清空备注" 200
check "清空后返回 null" "$(jq -r '.note == null' "$T/body")" true
req owner GET "/api/emails?q=$(jq -rn --arg q '云服务' '$q | @uri')"
check "清空备注后不再命中" "$(jq -r '.emails | length' "$T/body")" 0

cat > "$T/search1.eml" <<'EOF'
From: alice@alpha.example
To: notebox1@moemail.app
Subject: =?UTF-8?B?55m75b2V6YCa55+lIDUwJV9vZmY=?=
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="s1"

--s1
Content-Type: text/plain; charset="utf-8"

plain body line one
--s1
Content-Type: text/html; charset="utf-8"

<p>html_only_secret_marker_1</p>
--s1--
EOF
cat > "$T/search2.eml" <<'EOF'
From: billing@beta.example
To: notebox1@moemail.app
Subject: =?UTF-8?B?5pyI5bqm6LSm5Y2V?=
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

Invoice ID: INV-99881
EOF
cat > "$T/search3.eml" <<'EOF'
From: noreply@gamma.example
To: notebox1@moemail.app
Subject: HTML Only Mail
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<p>only_in_html_999</p>
EOF
deliver alice@alpha.example "$NADDR1" "$T/search1.eml" >/dev/null
deliver billing@beta.example "$NADDR1" "$T/search2.eml" >/dev/null
deliver noreply@gamma.example "$NADDR1" "$T/search3.eml" >/dev/null

req owner GET "/api/emails/$NBOX1?q=50%25_off&total=false"
expect "按主题含 %_ 搜邮件" 200
check "搜 50%_off 只命中第 1 封且不带 total" "$(jq -r '[(.messages | length), has("total")] | join(" ")' "$T/body")" "1 false"
req owner GET "/api/emails/$NBOX1?q=%25&total=false"
check "邮件搜索 % 不当通配符（只命中 1 封）" "$(jq -r '.messages | length' "$T/body")" 1
req owner GET "/api/emails/$NBOX1?q=billing@beta&total=false"
check "按发件人搜邮件只命中 1 封" "$(jq -r '.messages | length' "$T/body")" 1
req owner GET "/api/emails/$NBOX1?q=INV-99881&total=false"
check "按纯文本正文搜邮件只命中 1 封" "$(jq -r '.messages | length' "$T/body")" 1
req owner GET "/api/emails/$NBOX1?q=html_only_secret_marker_1&total=false"
check "邮件搜索不扫 HTML 列（有纯文本时）" "$(jq -r '.messages | length' "$T/body")" 0
req owner GET "/api/emails/$NBOX1?q=only_in_html_999&total=false"
check "邮件搜索不扫 HTML 列（纯 HTML 邮件）" "$(jq -r '.messages | length' "$T/body")" 0

req owner DELETE "/api/emails/$NBOX1" -H "Origin: $B" >/dev/null
req owner DELETE "/api/emails/$NBOX2" -H "Origin: $B" >/dev/null
req owner DELETE "/api/emails/$NBOX3" -H "Origin: $B" >/dev/null

echo "-- 清理 Worker 的孤儿扫描"
ORPHAN="att/00000000-0000-4000-8000-0000000000aa/0"; EXPIRING="att/00000000-0000-4000-8000-0000000000bb/0"
harness put-orphan "$ORPHAN" >/dev/null; harness put-orphan "$EXPIRING" expiring >/dev/null
check "写入两个孤儿附件" "$(harness keys | jq -r --arg a "$ORPHAN" --arg b "$EXPIRING" '[.[] | select(.name == $a or .name == $b)] | length')" 2
R=$(harness sweep); check "扫描删掉不会自己到期的孤儿附件" "$(jq -r '.deleted' <<<"$R")" 1
check "孤儿附件没了" "$(harness keys | jq -r --arg k "$ORPHAN" '[.[] | select(.name == $k)] | length')" 0
check "带到期时间的不删（不占删除额度）" "$(harness keys | jq -r --arg k "$EXPIRING" '[.[] | select(.name == $k)] | length')" 1
check "别人邮件的附件还在" "$(keys_of "$OTHERMSG")" 6

echo "== 结果 [attachments]: 通过 $PASS, 失败 $FAIL =="
[ "$FAIL" -eq 0 ]
