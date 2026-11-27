# 个人域名邮箱（MoeMail + Cloudflare）

用自己的域名收信的网页邮箱：先在网页里建一个地址（比如 `abc@7879710.xyz`），之后发到这个地址的邮件都能在 <https://mail.7879710.xyz> 登录查看。程序是开源项目 [MoeMail](https://github.com/beilunyang/moemail)，整套东西跑在 Cloudflare 上（Pages、D1、KV、Email Routing、Workers），不需要自己的服务器。

这份文档记录它平时怎么用、怎么更新、是怎么搭起来的，以及换机器或换账号时怎么恢复。

## 概览

| 项目 | 内容 |
| --- | --- |
| 网页端 | <https://mail.7879710.xyz> |
| 邮箱后缀 | `@7879710.xyz` |
| 登录方式 | 用户名加密码，没有启用 GitHub、Google 登录 |
| 注册 | 已关闭。站长（界面里的角色名是“皇帝”）可以随时重新打开 |
| 代码 | 本仓库的 `moemail/` 目录：上游 `beilunyang/moemail` 的提交 `5722ceb` 加本地改动 |
| 线上版本 | 见文末的[部署记录](#部署记录) |
| 首次部署 | 2026-11-26 |

## 工作原理

1. 发信方把邮件投给 `7879710.xyz` 的 MX，也就是 Cloudflare Email Routing。
2. Email Routing 的 catch-all 规则把这个域名下所有地址的来信都交给 `email-receiver-worker`。
3. 这个 Worker 按收件地址找对应的邮箱。找到了就解析邮件，把发件人、主题、纯文本正文和 HTML 正文写进 D1 数据库，附件存进 KV 命名空间 `moemail-attachments`。找不到的，也就是没在 MoeMail 里建过的地址，整封信原样转发到一个私人邮箱，附件跟着信走，MoeMail 里不留。
4. 网页端从 D1 读邮件。
5. `cleanup-worker` 每小时整点删除过期的邮箱和里面的邮件，每次最多 100 个；顺带检查一部分附件（16 小时轮完一遍），删掉对应邮件已经不存在的。

| Cloudflare 资源 | 名称 | 作用 |
| --- | --- | --- |
| Pages 项目 | `moemail` | 网页端和接口。Next.js 应用，用 next-on-pages 构建后跑在 Pages Functions 上；绑定 D1（`DB`）和两个 KV（`SITE_CONFIG`、`ATTACHMENTS`），运行时密钥只有 `AUTH_SECRET` 一个 |
| D1 数据库 | `moemail-db` | 账号和角色、邮箱、邮件、分享链接、API Key、Webhook |
| KV 命名空间 | `moemail-kv` | 站点配置，也就是“网站配置”和“Resend 发件服务配置”两个面板里的设置。目前只写了可用域名 `EMAIL_DOMAINS` 和注册开关 `ALLOW_REGISTRATION` |
| KV 命名空间 | `moemail-attachments` | 收到的附件，每个附件一个键 `att/<邮件 ID>/<序号>`；文件名、大小等记在 D1 的 `message.attachments` 列里。绑定名 `ATTACHMENTS`，网页端和两个 Worker 都绑了 |
| Worker | `email-receiver-worker` | 收信。绑定 D1 和 `ATTACHMENTS`；变量 `FORWARD_TO` 是未注册地址的转发目标，写在工作目录的 `wrangler.email.json` 里，这个文件不进仓库 |
| Worker | `cleanup-worker` | 定时清理，cron 是 `0 * * * *`。绑定 D1 和 `ATTACHMENTS` |
| Email Routing | catch-all 规则 `MoeMail catch-all` | 把所有来信交给 `email-receiver-worker`，是这个域名上唯一的路由规则 |
| Email Routing | 目标地址（Destination addresses） | 账号级的已验证邮箱。Worker 只能转发到这里验证过的地址，`FORWARD_TO` 必须是其中之一 |
| DNS | `mail` 的 CNAME，指向 Pages 项目的 `pages.dev` 子域名，开代理 | 网页端的域名 |
| DNS | 根域名的 3 条 MX 和 SPF，以及 `cf2024-1._domainkey` 的 DKIM | 收信用，由 Email Routing 生成 |

这个域名上原有的转发规则已经全部删除。从 2026-11-27 起，没在 MoeMail 里建过的地址由收信 Worker 转发到私人邮箱；要让某个地址的信进 MoeMail，在 MoeMail 里建同名的“永久”邮箱。

## 日常使用

### 建邮箱和收信

1. 打开 <https://mail.7879710.xyz/zh-CN/login> ，用用户名和密码登录。
2. 在首页点“进入邮箱”，再点左边“我的邮箱”这一栏里、邮箱数量右边的“创建邮箱”。
3. 填邮箱名，也就是地址里 `@` 前面那段；点旁边的刷新图标可以随机生成一个。“有效期”选 1 小时、1 天、3 天或永久。对话框下方会显示完整的地址。
4. 点“创建”。新邮箱出现在“我的邮箱”的列表里，点它就能看到收到的邮件。邮箱打开着的时候，新邮件大约每 10 秒自动刷出来。

几条要知道的规则：

- 发到建好的邮箱地址的信存进 MoeMail；发到其它地址的信原样转发到私人邮箱，附件跟着信走，MoeMail 里不保存。过期了、但还没被清理掉的邮箱，来信也按这样处理。信存不进 MoeMail 时（比如数据库出错）同样转发过去。转发失败（比如私人邮箱在 Email Routing 里的验证被取消了）时 Worker 会报错，Email Routing 的活动日志里能看到；这种情况下发信方是收到退信还是过后重试，没有实测。
- 要拿一个地址去注册网站，先把它建成“永久”邮箱。对话框默认选中的是“1 天”，建好以后不能改有效期；地址过期被清理之后，那个网站发来的找回密码邮件就收不到了，这个地址还可能被别的有建邮箱权限的账号建走。
- 附件存在 KV 里，列在邮件头下方，点一下就下载；正文里内嵌的图片直接显示在正文中。用的是 Workers 免费套餐自带的额度：KV 总共 1 GB，每天 1000 次写入、1000 次删除，整个 Cloudflare 账号共用。所以每天最多存 600 个附件，全部附件合计最多 800 MB，单个附件最大约 25 MB，每封信最多存 20 个（名额不够时先存附件栏里的文件，再存正文里的内嵌图片）。没存下的附件显示“未保存”，邮件本身照收。
- 删除邮件、邮箱或账号时，附件一起删除。临时邮箱的附件比邮箱晚一小时到期，由 KV 自动删除；清理 Worker 每小时检查一部分，16 小时轮完一遍，删掉漏删的。
- 通过分享链接能看到的邮件，附件也能下载。
- 没有 IMAP、POP3、SMTP，只能在网页里看，或者用 API Key 通过接口读。
- 地址不区分大小写。
- 有效期到了的邮箱，会在之后整点的清理中连同里面的邮件一起被删除。
- 删除邮箱会同时删除里面的全部邮件和附件，不能恢复。
- 每个账号最多 30 个邮箱，站长不受限制。上限可以在“网站配置”里改。

### 收不到信时

1. 先确认收件地址的邮箱已经建好，而且没有过期。发到没建的地址的信转发到了私人邮箱，去那边找；建好邮箱以后，之后的信才进 MoeMail。
2. 在 Cloudflare 控制台看这个域名的 Email Routing：状态正常，catch-all 规则是启用的，并且指向 `email-receiver-worker`。
3. 看收信 Worker 的实时日志，然后让对方重发一封。这一步要在工作目录里做（见[代码放在哪](#代码放在哪)），先导出部署凭据（见[更新和部署](#更新和部署)的第 4 步），令牌要有 Workers Tail 的读权限：

   ```bash
   pnpm exec wrangler tail --config wrangler.email.json --format pretty
   ```

   - 出现 `Email processed: 发件人 -> 收件地址`：信已经存进数据库。这里的发件人是信封上的发件人，可能和邮件里显示的不一样，按收件地址找更可靠。带附件的信后面还有 `attachments stored 存下的个数/附件总数`。
   - 出现 `Email forwarded: 发件人 -> 收件地址`：没有这个邮箱，信已转发到私人邮箱。那边没收到的话，先看垃圾箱，再到 Email Routing 的“目标地址”里确认它还是已验证状态。
   - 出现 `Email not found: 收件地址`：没有这个邮箱，`wrangler.email.json` 里也没配 `FORWARD_TO`，信已丢弃。
   - 出现 `Failed to store email`：入库时出错，后面跟着错误信息。紧接着出现 `Email forwarded after store failure` 的话，这封信已经转发到私人邮箱。
   - 什么都没出现：信没有到 Worker，回到第 2 步查 Email Routing。

### 账号和角色

注册现在是关闭的。新注册的账号默认是“平民”，没有任何权限，点“进入邮箱”时会看到“权限不足”，要站长提升之后才能用。

| 角色 | 能做什么 |
| --- | --- |
| 皇帝（站长） | 全部：邮箱、Webhook、API Key、站点配置、管理用户；邮箱数量不限 |
| 公爵 | 邮箱、Webhook、API Key |
| 骑士 | 邮箱、Webhook |
| 平民 | 什么都不能做 |

站长只有一个：部署后第一个登录并访问 `/api/roles/init-emperor` 的账号。已经有站长之后，这个地址只会报错。

骑士和公爵可以创建这个域名下任何还没被占用的地址，所以这两个角色只给信得过的人。

### 给别人开账号

程序没有替别人建账号的功能，只能临时打开注册：

1. 站长登录后点右上角的头像进个人中心，在“网站配置”里打开“允许注册新账号”，点“保存配置”。过几十秒，登录页会出现“注册”页签。
2. 对方打开 <https://mail.7879710.xyz/zh-CN/login> ，在“注册”页签填用户名、密码和确认密码，点“注册”。用户名最长 20 个字符，只能用字母、数字、下划线和横杠；密码至少 8 位。注册后会自动登录，这时进邮箱会提示“权限不足”，是正常的。
3. 站长在个人中心的“角色管理”里找到这个账号，把它右边的下拉框从“平民”改成“骑士”，选完就生效，会提示“用户角色更新成功”。要让对方自己能建 API Key，就选“公爵”。
4. 对方刷新页面，就能进邮箱了。
5. 站长回到“网站配置”，关掉“允许注册新账号”，点“保存配置”。

### 忘了密码

程序没有重置密码的功能。站长可以直接改数据库里的密码。在工作目录里执行，先导出部署凭据（见[更新和部署](#更新和部署)的第 4 步，下面用到的 `getenv` 也在那里定义）：

```bash
IFS= read -rs -p '新密码（至少 8 位）: ' NEWPW; echo
h=$(printf '%s%s' "$NEWPW" "$(getenv AUTH_SECRET)" | openssl dgst -sha256 -binary | base64)
pnpm exec wrangler d1 execute moemail-db --remote --command "UPDATE user SET password='$h' WHERE username='<用户名>' RETURNING username"
unset NEWPW
```

新密码至少 8 位，短了登录时会被拒绝。输出的结果里出现这个用户名才算改到了；结果是空的，就是用户名写错了。这个办法在本机的测试实例上验证过，还没有在线上用过。

### 个人中心

点右上角的头像或用户名进入个人中心。站长能看到这些面板：

| 面板 | 用途 |
| --- | --- |
| 网站配置 | 新用户默认角色、邮箱域名、管理员联系方式、每个用户最大邮箱数、允许注册新账号、Cloudflare Turnstile（登录和注册时的人机验证，没有启用）。改完要点“保存配置” |
| Resend 发件服务配置 | 发信功能，没有启用 |
| 角色管理 | 调整其他账号的角色，删除用户 |
| Webhook 配置 | 收到新邮件时把内容发到一个 URL |
| API Key 管理 | 创建、停用和删除 API Key |

“网站配置”和“Resend 发件服务配置”存在 KV 里，保存后可能要过几十秒才生效；角色、Webhook 和 API Key 存在 D1 里，改了马上生效。

### API Key

1. 进个人中心，在“API Key 管理”里点“创建 API Key”。
2. 填“密钥名称”，点对话框里的“创建 API Key”。
3. 把显示出来的密钥复制下来。它只显示这一次，有效期一年。

调用接口时把它放在请求头 `X-API-Key` 里。它只能用于邮箱相关的接口（`/api/emails` 下面的全部接口）和读取站点配置（`GET /api/config`），不能改站点配置，也不能管理用户、Webhook 和 API Key。它的权限跟着主人的角色走：主人被降成平民后，邮箱接口就都用不了了，只剩读取站点配置（`GET /api/config`）还能用。要彻底作废，在“API Key 管理”里停用或删除它。

接口列表见上游文档 `moemail/README.zh-CN.md` 的“OpenAPI”一节。

### 发信、Webhook 和分享链接

- 发信：在“Resend 发件服务配置”里填 Resend 的 API Key 并启用之后才能用，目前没有启用。
- Webhook：每个账号一个地址，收到新邮件时把发件人、主题和正文 POST 过去。通知不带签名，失败了也不重试。
- 分享链接：邮箱或单封邮件可以生成不用登录就能看的链接，可以设有效期，也可以随时删除。

## 代码放在哪

| 位置 | 内容 |
| --- | --- |
| 工作目录 `~/moemail`，在部署机（平时做构建和部署的那台电脑）上 | 上游仓库的克隆加本地改动，本地改动都是未提交的修改。带真实的 `.env` 和生成出来的 `wrangler.json`、`wrangler.email.json`、`wrangler.cleanup.json`。改代码、构建、测试、部署都在这里做 |
| 本仓库的 `moemail/` | 工作目录的镜像，用工作目录里的 `scripts/sync-to-vpsinit.sh` 同步过来。`.env` 是脱敏副本；三个 `wrangler*.json` 带资源 ID，被 `.gitignore` 忽略，不入库 |

本仓库是公开的，真实的 `.env` 只留在工作目录里。两条规矩：

- 不要在仓库的 `moemail/` 里填真实密钥：`.env` 在这里是入库文件。
- 不要直接改仓库 `moemail/` 里的文件：每次同步都会用工作目录的内容把它整个覆盖，工作目录里没有的文件会被删掉。

## 更新和部署

下面的命令都在工作目录里执行。需要 Node.js（部署时用的是 22）、jq、curl 和 rsync。pnpm 通过 corepack 使用：`package.json` 的 `packageManager` 把版本固定在 9.15.9，corepack 会自动切换。新机器上先执行一次 `corepack enable`；Node.js 25 起不再自带 corepack，要先 `npm install -g corepack`。

```bash
# 1. 检查和构建，产物在 .vercel/output/static
pnpm exec tsc --noEmit
pnpm run lint
pnpm run build:pages

# 2. 本地回归：在本机起一个模拟实例跑全部测试，不连 Cloudflare，不需要凭据
scripts/test/run-local.sh

# 3. 同步到本仓库（.env 自动脱敏），然后到仓库里提交
scripts/sync-to-vpsinit.sh

# 4. 导出部署凭据。.env 的写法是 KEY = "value"，不能直接 source
getenv() { sed -n -E "s/^$1[[:space:]]*=[[:space:]]*\"?([^\"]*)\"?[[:space:]]*\$/\1/p" .env | head -1; }
export CLOUDFLARE_API_TOKEN="$(getenv CLOUDFLARE_API_TOKEN)"
export CLOUDFLARE_ACCOUNT_ID="$(getenv CLOUDFLARE_ACCOUNT_ID)"

# 5. 部署网页端
pnpm exec wrangler pages deploy .vercel/output/static --branch main --commit-dirty=true

# 6. 线上验证：只发匿名请求，不带凭据，不改数据
scripts/test/live-verify.sh https://mail.7879710.xyz
```

第 6 步通过以后，再自己登录走一遍：进邮箱，给一个永久邮箱发封信，确认能收到。然后：

1. 删除旧部署，见[删除旧部署和回滚](#删除旧部署和回滚)。
2. 在文末的[部署记录](#部署记录)里加一行，提交。
3. 把提交推送到 GitHub。本仓库是公开的，涉及安全修复的提交要等线上部署并验证通过之后再推送。

几点说明：

- `--branch main` 不能省。工作目录是上游仓库的克隆，当前分支叫 `master`，而 Pages 项目的生产分支是 `main`；省掉的话 wrangler 会按 `master` 部署成预览版，线上不会更新。
- Cloudflare 的部署列表里显示的提交号是上游的 `5722ceb`，也就是工作目录的 git HEAD，不是本仓库的提交。线上对应本仓库的哪个提交，以部署记录为准。
- 部署网页端不会更新两个 Worker。改了 `workers/` 下的文件、两个 Worker 都引用的 `app/lib/attachments.ts`、收信 Worker 引用的 `app/lib/schema.ts`、`app/lib/webhook.ts`、`app/config/webhook.ts`，或者升级了它打包进去的 `drizzle-orm`、`postal-mime`，要另外部署：收信 Worker 用 `pnpm exec wrangler deploy --config wrangler.email.json`，清理 Worker 用 `pnpm exec wrangler deploy --config wrangler.cleanup.json`。本地测试里，附件与转发测试会直接调用收信 Worker 的代码，但不经过真的 Email Routing；部署收信 Worker 之后按[收不到信时](#收不到信时)的第 3 步开着日志收一封信确认。
- 数据库结构有变化时（合并上游，或者像 2026-11-27 加附件那样本地改了 `app/lib/schema.ts`），在部署网页端和两个 Worker 之前执行 `pnpm run db:migrate-remote`。新代码要读写新加的列，先部署代码会出错；旧代码不碰新列，先迁移没有影响。它直接改线上的数据库，执行前先读一遍新增的迁移 SQL，并做一份备份：`pnpm exec wrangler d1 export moemail-db --remote --output <路径>`。备份文件放在工作目录和本仓库以外的地方，里面有全部邮件。这条备份命令还没有实际用过。

### 删除旧部署和回滚

每次部署之后，旧部署仍然可以通过它自己的地址访问，用的还是线上的数据库。地址是 `https://<部署短 ID>.<项目的 pages.dev 子域名>`，子域名带一段随机后缀，在控制台的 Pages 项目页能看到。所以旧部署不要留着：修了安全问题的版本，验证通过后马上删旧部署；其它情况可以等自己登录确认没问题再删。

```bash
# 列出部署。Build 一栏链接的最后一段是完整部署 ID
pnpm exec wrangler pages deployment list --project-name moemail

# 删除一个旧部署（wrangler 3.93 没有对应的命令，直接调 API）
curl -s -X DELETE -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/moemail/deployments/<完整部署 ID>"
```

只删不在线上的部署。平时线上就是列表里最新的那条 Production 部署；在控制台回滚过，或者最新那次部署失败了，线上就不是它，以控制台 Pages 项目页上 Production 显示的那条为准。把 ID 粘进地址之前核对一下不是它。

新版本有问题时：

- 旧部署还在：在 Cloudflare 控制台 Pages 项目的 Deployments 列表里，对旧部署选 “Rollback to this deployment”（见[官方说明](https://developers.cloudflare.com/pages/configuration/rollbacks/)）。回滚不会撤销已经执行的数据库迁移。回滚以后，出问题的那个新部署还能通过它自己的地址访问，用的也是线上数据库；确认线上已经是回滚到的版本后，按上面的命令把它删掉。
- 旧部署已经删了：删掉的部署不能回滚，要在工作目录里撤掉出问题的那个提交，再重新构建部署。本地改动的历史在本仓库里，在工作目录里执行：

  ```bash
  git -C ~/WIKI/vpsinit show --binary <出问题的提交> -- moemail ':!moemail/.env' | git apply -p2 -R
  ```

  它只撤掉这一个提交的改动，前提是工作目录和本仓库的最新提交是同步的，也不动 `.env`。报错说明后面的提交又改过同样的地方，要手工改回去。不要把整个代码退回到某个旧提交：那之后的提交大多是安全修复，会跟着一起退掉。也不要把仓库里的 `moemail/` 整个复制回工作目录，那样会用脱敏的 `.env` 盖掉真实的。撤掉之后：
  - 这个提交改过 `package.json` 或 `pnpm-lock.yaml` 的话，先执行 `pnpm install --frozen-lockfile`，否则构建用的还是 `node_modules` 里的版本。
  - 从第 1 步重新构建、测试、部署。测试脚本是按撤掉之前的代码写的，撤掉的那部分会报失败；确认失败的只有这几项，再往下做。
  - 这个提交改过 `workers/` 或收信 Worker 引用的文件，网页端部署完还要重新部署对应的 Worker。
- 收信或清理 Worker 出了问题：网页端的回滚管不到它们。在工作目录里导出部署凭据，执行 `pnpm exec wrangler rollback --config wrangler.email.json` 退回上一个版本，清理 Worker 换成 `wrangler.cleanup.json`。这条命令没有实际用过。收信 Worker 坏着的时候，来信可能存不进数据库，要尽快退。
- 回滚或撤掉提交之后，在部署记录里加一行，写明做了什么。

### 部署用的令牌

在 Cloudflare 控制台的 API 令牌页创建自定义令牌，建议设过期时间。

- 日常更新：账户级的 Cloudflare Pages、Workers Scripts、D1、Workers KV Storage 四项 Edit。要看收信日志，再加 Workers Tail 的 Read。
- 用 API 改 DNS 或邮件路由时：再给这一个域名加区域级的 DNS、Email Routing Rules、Zone Settings 三项 Edit。在控制台里手动改的话不需要。

这两份清单是按官方文档和实际用到的接口整理的，还没有实测过。wrangler 报权限错误时，先补上 Account Settings、User Details、Memberships 三项 Read。

令牌的值只在创建时显示一次，之后查不回来。丢了就新建一个，并删掉旧的。新令牌填进工作目录 `.env` 的 `CLOUDFLARE_API_TOKEN`（不是仓库里那份），部署前照[更新和部署](#更新和部署)的第 4 步导出。

### 测试脚本

| 脚本 | 用途 | 说明 |
| --- | --- | --- |
| `scripts/test/run-local.sh` | 部署前的本地回归 | 要先 `pnpm run build:pages`。它用 `wrangler pages dev` 在 127.0.0.1 起一个实例（D1 和 KV 都是本地模拟的），依次跑下面三个脚本，结束后自动清理。默认端口 8792，换端口用 `PORT=8795 scripts/test/run-local.sh`；只跑其中几个用 `SUITES="sec live attachments"` 里的名字，比如 `SUITES=attachments`。输出里的“已应用迁移数”和“本地模拟器故障重试 N 次”只是统计，不算失败 |
| `scripts/test/sec-suite.sh` | 安全和功能回归 | 只允许对本机实例运行，会注册测试账号、改站点配置。最后一行报告通过和失败的数量，失败数是 0 才算通过 |
| `scripts/test/attachments-suite.sh` | 附件与转发 | 由 `run-local.sh` 调用。它用 `email-harness.ts` 直接调用收信 Worker 的代码投递测试信（D1 和 KV 是同一个本地实例的），检查附件的保存、下载权限和响应头、未注册地址的转发，以及删除邮件、邮箱、账号时附件一起删掉 |
| `scripts/test/live-verify.sh <地址>` | 部署后的线上验证 | 只发匿名请求。它按仓库里最新的代码检查，并且假定注册已关闭、只有密码登录；线上不是最新版，或者这两项改了，对应的检查会报失败 |

### 合并上游的新版本

还没有合并过。下面是打算采用的做法，没有实际走过：

1. 在工作目录里执行 `git stash -u` 把本地改动收起来，`git pull` 拉上游，再 `git stash pop` 放回来，逐个解决冲突。`middleware.ts` 改得最多，冲突也会最多。解决时对照[相对上游的改动](#相对上游的改动)，那里列的都要保留。
2. 执行 `pnpm install`。看 `drizzle/` 里有没有新的迁移文件，有的话按上面说的先备份、再迁移。
3. 构建，跑 `scripts/test/run-local.sh`，然后照上面的步骤部署，两个 Worker 也重新部署一遍。
4. 在部署记录里记下新的上游提交号，并把文中写死的 `5722ceb` 都改成它：概览、“几点说明”，以及换一台机器维护第 1 步的 `git reset --hard 5722ceb`。

## 换一台机器维护

工作目录丢了或者要换机器时，线上不受影响。新机器上先装好 Node.js 22、git、jq、curl 和 rsync，执行一次 `corepack enable`（Node.js 25 起要先 `npm install -g corepack`），再把本仓库克隆下来：`git clone https://github.com/soloxyq/vpsinit.git ~/WIKI/vpsinit`。然后按下面的步骤恢复出一个和原来一样的工作目录，也就是上游克隆加未提交的本地改动：

```bash
REPO=~/WIKI/vpsinit        # 本仓库在这台机器上的位置

# 1. 克隆上游并退到当时的提交，再把本仓库的 moemail/ 盖上去。
#    三条用 && 连着：~/moemail 已经存在时克隆会失败，后面两条就不会执行。先把它挪开再来
git clone https://github.com/beilunyang/moemail.git ~/moemail &&
  cd ~/moemail && git reset --hard 5722ceb &&
  rsync -a "$REPO/moemail/" ~/moemail/

# 2. 编辑 ~/moemail/.env（不是仓库里那份）：删掉开头三行脱敏说明，
#    把 CLOUDFLARE_API_TOKEN、CLOUDFLARE_ACCOUNT_ID 和 AUTH_SECRET 的 "xxxxxx" 换成真实值

# 3. 装依赖
pnpm install --frozen-lockfile

# 4. 导出部署凭据（同“更新和部署”的第 4 步），然后从模板生成三个 wrangler 配置。
#    FORWARD_TO 填 Email Routing 目标地址里那个私人邮箱（未注册地址的来信转发到这里），它不写进仓库
FORWARD_TO=""
D1_ID=$(pnpm exec wrangler d1 list --json | jq -r '.[] | select(.name=="moemail-db") | .uuid')
KV_ID=$(pnpm exec wrangler kv namespace list | jq -r '.[] | select(.title=="moemail-kv") | .id')
ATT_ID=$(pnpm exec wrangler kv namespace list | jq -r '.[] | select(.title=="moemail-attachments") | .id')
if [ -n "$D1_ID" ] && [ -n "$KV_ID" ] && [ -n "$ATT_ID" ] && [ -n "$FORWARD_TO" ]; then
  for f in wrangler wrangler.email wrangler.cleanup; do
    jq --arg id "$D1_ID" '.d1_databases[0].database_name = "moemail-db" | .d1_databases[0].database_id = $id' "$f.example.json" > "$f.json"
  done
  jq --arg id "$KV_ID" --arg att "$ATT_ID" '.kv_namespaces[0].id = $id | .kv_namespaces += [{"binding": "ATTACHMENTS", "id": $att}]' wrangler.json > wrangler.json.tmp && mv wrangler.json.tmp wrangler.json
  jq --arg att "$ATT_ID" --arg to "$FORWARD_TO" '.kv_namespaces = [{"binding": "ATTACHMENTS", "id": $att}] | .vars = {"FORWARD_TO": $to}' wrangler.email.json > wrangler.email.json.tmp && mv wrangler.email.json.tmp wrangler.email.json
  jq --arg att "$ATT_ID" '.kv_namespaces = [{"binding": "ATTACHMENTS", "id": $att}]' wrangler.cleanup.json > wrangler.cleanup.json.tmp && mv wrangler.cleanup.json.tmp wrangler.cleanup.json
else
  echo "取不到 D1 或 KV 的 ID，或者没填 FORWARD_TO：先检查凭据和第一行。三个 wrangler 配置没有改"
fi
```

第 2 步的三个真实值从哪里来：

- `AUTH_SECRET`：从另存的那一份里取。它必须是原来的值，见[密钥](#密钥)。
- `CLOUDFLARE_API_TOKEN`：不用找回，按[部署用的令牌](#部署用的令牌)新建一个，再到 Cloudflare 的 API 令牌页删掉旧机器上用的那个。
- `CLOUDFLARE_ACCOUNT_ID`：在 Cloudflare 控制台域名概览页的 API 一栏能看到。

之后就可以照[更新和部署](#更新和部署)做了。几点注意：

- 同步脚本默认写到 `~/WIKI/vpsinit/moemail`。仓库不在这个位置时，把仓库里 `moemail` 子目录的完整路径作为第一个参数传给它。注意不是仓库根目录，也不是工作目录：脚本会用 `rsync --delete` 把目标目录变成工作目录的镜像，传错了会删掉目标里的其它文件。拿不准就先加 `DRY_RUN=1` 跑一遍，看它要改什么。
- 不要为了省事去跑上游的部署脚本 `scripts/deploy/index.ts`。它每次都会把 `.env` 文件里的 `AUTH_SECRET` 重新推到线上；`.env` 里还是 `xxxxxx` 的话，线上的会话密钥就变成了这个公开的值，所有账号的密码也立刻失效。
- 上游仓库哪天不在了，第 1 步改成直接复制 `$REPO/moemail` 也能构建和部署，只是工作目录不再是 git 仓库，没法用 git 合并上游。

## 从零部署

这一节用于在一个还没有这套资源的 Cloudflare 账号上重新搭一套，步骤是根据 2026-11-26 的操作整理的。搭出来的是一套空的系统，原来的账号和邮件不会跟过去。前提是域名已经托管在 Cloudflare。

同一个账号里只是换域名或加域名，不要用这一节，看后面的[同一个账号里换域名或加域名](#同一个账号里换域名或加域名)。

1. **准备令牌。** 见[部署用的令牌](#部署用的令牌)。第 5、7 步打算用 API 做的话，要带上区域级的三项权限。
2. **取代码，装依赖。** 照[换一台机器维护](#换一台机器维护)开头的准备工作和第 1 步（连同 `REPO=` 那一行）恢复出工作目录，执行 `pnpm install --frozen-lockfile`。
3. **写 `.env`。** 编辑工作目录里的 `.env`，不要改仓库里的 `moemail/.env`。先删掉开头三行脱敏说明，再填这几项：
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`：新账号的 ID，在控制台域名概览页的 API 一栏能看到
   - `CUSTOM_DOMAIN`：网页端的域名，不带 `https://`
   - `NEXT_PUBLIC_BASE_URL`：`https://` 加网页端的域名。它在构建时写进页面的元数据，不设的话会指向上游的 `moemail.app`
   - `AUTH_SECRET`：用 `openssl rand -hex 32` 新生成一个，并另外存一份
   - `AUTH_GITHUB_*`、`AUTH_GOOGLE_*` 留空，表示只用用户名密码登录
4. **运行上游的部署脚本。** 先做两项检查，再运行：

   ```bash
   grep -n xxxxxx .env                                # 必须没有输出
   unset CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID   # 免得用上终端里残留的旧账号凭据
   pnpm exec tsx ./scripts/deploy/index.ts
   ```

   脚本推到线上的是 `.env` 文件里的 `AUTH_SECRET`，留着 `xxxxxx` 就会把这个公开的值设成线上的会话密钥。它依次做这些事：从模板生成三个 `wrangler*.json`，建 D1 数据库并执行迁移，建 KV 命名空间，建 Pages 项目并登记自定义域名，把 `AUTH_SECRET` 设成 Pages 的密钥，构建并部署网页端，部署两个 Worker。它不配置 DNS 和 Email Routing，也不写站点配置。两点要留意：Worker 部署失败时它只打印错误，最后仍然报成功，跑完要确认两个 Worker 确实在；它推密钥和部署 Worker 用的是 `pnpm dlx wrangler`，会临时下载最新版的 wrangler，不是锁文件里的版本。
5. **网页端的域名。** 让 `mail` 的 CNAME 指向 Pages 项目的 `pages.dev` 子域名，并打开代理。这个名字上原来有别的记录的话要改掉，否则 Pages 里的自定义域名会一直停在 “CNAME record not set”。改完等一两分钟，状态变成 active 就能访问了。
6. **建站长账号，关闭注册。** 域名一生效就做，照[建站长账号和第一个邮箱](#建站长账号和第一个邮箱)的前三步。
7. **Email Routing。** 在控制台里做，上游文档 `moemail/README.zh-CN.md` 的“Cloudflare 邮件路由配置”一节有说明：
   - 在域名的“电子邮件”→“电子邮件路由”里启用，并让它添加 MX、SPF、DKIM 记录。域名上已经有别家邮件服务的 MX 的话，这一步之后根域名的信会改由 Cloudflare 接收，先想好再做。
   - 把 Catch-all 规则启用，动作选“发送到 Worker”，目标选 `email-receiver-worker`。
   - 域名上原有的、针对具体地址的规则优先于 catch-all。这些地址以后要进 MoeMail 的话，先在 MoeMail 里给它们各建一个“永久”邮箱，再删规则；也可以保留规则，让它们照旧转发。
8. **附件和转发。** 上游的部署脚本不管这两样，要自己补：
   - 建存附件的 KV：`pnpm exec wrangler kv namespace create moemail-attachments`，按[换一台机器维护](#换一台机器维护)第 4 步那样把 `ATTACHMENTS` 绑定加进三个 wrangler 配置，把 `FORWARD_TO` 加进 `wrangler.email.json`。
   - 在 Email Routing 的“目标地址”里添加那个私人邮箱，到它的收件箱里点验证链接。
   - 执行 `pnpm run db:migrate-remote`，再重新部署网页端和两个 Worker（命令见[更新和部署](#更新和部署)）。
9. **建第一个邮箱，发测试信。** 照[建站长账号和第一个邮箱](#建站长账号和第一个邮箱)的后两步。
10. **收尾。** 删掉这次用的令牌，以后部署另建一个只有日常更新权限的。

### 建站长账号和第一个邮箱

下面的地址是这套部署的；在别的域名上做，就换成那里的网页端域名。部署脚本跑完以后，注册对所有人开放，谁先做完前两步，谁就是站长，所以网页端域名一生效就马上做前三步。

1. 打开 <https://mail.7879710.xyz/zh-CN/login> ，在“注册”页签建账号。密码请用长的随机密码，因为这套登录没有限速。
2. 登录后在同一浏览器访问 <https://mail.7879710.xyz/api/roles/init-emperor> ，看到“登基成功”即可。这个账号从此就是站长。
3. 点右上角的头像进个人中心，在“网站配置”里把“邮箱域名”改成收信的根域名 `7879710.xyz`，关掉“允许注册新账号”，点“保存配置”。注意邮箱域名不是网页端的 `mail.7879710.xyz`；有多个域名时用英文逗号隔开，不加空格。过几十秒，开一个浏览器无痕窗口打开 <https://mail.7879710.xyz/zh-CN/login> ，确认“注册”页签不见了。已经登录的窗口打开登录页会直接跳回首页，看不到页签。
4. 回到原来的窗口，先刷新一次页面，再回首页点“进入邮箱”，创建一个邮箱，有效期选“永久”。不刷新的话，页面用的还是保存前的配置，建邮箱时会提示“无效的域名”。
5. 从别的邮箱给这个地址发一封信，确认能在网页里看到。

### 同一个账号里换域名或加域名

这两件事都没有实际做过，下面是按程序的行为整理的做法。都不要运行部署脚本，`AUTH_SECRET` 保持不变。

- 加一个收信域名：在新域名上照上面第 7 步配好 Email Routing，catch-all 指向同一个 `email-receiver-worker`；然后在“网站配置”的“邮箱域名”里加上它，多个域名用英文逗号隔开，不加空格。保存后刷新页面，建邮箱的对话框里才会出现新域名。
- 网页端换地址：在 Pages 项目里加上新的自定义域名并配好 CNAME，把工作目录 `.env` 里的 `CUSTOM_DOMAIN` 和 `NEXT_PUBLIC_BASE_URL` 改成新地址，再按[更新和部署](#更新和部署)重新构建部署。

### 当时实际是怎么做的

2026-11-26 的做法和上面的步骤有几处不同，记在这里备查：

- Email Routing 是用 API 配的。这个域名早先就启用过 Email Routing，所以当时是先设 catch-all，再生成 DNS 记录。设 catch-all 的接口是 `PUT /zones/{zone_id}/email/routing/rules/catch_all`，请求体是 `{"name":"MoeMail catch-all","enabled":true,"matchers":[{"type":"all"}],"actions":[{"type":"worker","value":["email-receiver-worker"]}]}`。生成 DNS 记录的接口是 `POST /zones/{zone_id}/email/routing/dns`，请求体用空对象 `{}`；带上根域名的 `name` 会报 2007，那个字段是给子域名用的。
- `mail` 的 CNAME 原来指向别处，是用 API 改的，改完又用 API 触发过重新校验。
- 邮箱域名和注册开关没有走界面，是直接写进 KV 的（`EMAIL_DOMAINS` 和 `ALLOW_REGISTRATION`）。注册开关是首次部署之后才加的功能。
- 域名上原有的 5 条转发规则，是站长账号和第一个邮箱建好、确认能收信之后才删的。

## 相对上游的改动

本地改动都在 `d172b27`（原样导入上游）之后的提交里，在本仓库的根目录执行 `git log d172b27..HEAD -- moemail` 可以看到全部。数据库结构改过一次：`message` 表加了 `attachments` 列（迁移 `drizzle/0019_steady_ultimatum.sql`）。合并上游时下面这些要保留：

| 改动 | 作用 | 主要位置 |
| --- | --- | --- |
| 身份只认 API Key 或登录会话 | 接口不接受请求里自报的用户身份 | `moemail/app/lib/apiKey.ts` |
| 接口各自检查身份和权限 | 每个需要登录的处理函数开头调用 `requireUser()`，不依赖中间件 | `moemail/app/lib/guard.ts` 和 `moemail/app/api/` 下的各个 `route.ts` |
| 中间件 | matcher 覆盖除 `/_next/static/` 以外的全部路径；`/api` 前缀的权限表，没登记的一律拒绝；路径统一转小写再判断；靠 Cookie 的写请求必须来自本站页面；`/_next/data/` 和 `//` 开头的路径返回 404；页面路径只接受 GET 和 HEAD | `moemail/middleware.ts` |
| 禁止被 iframe 嵌入 | 页面和接口的响应都带防点击劫持的响应头，由中间件加；`next.config.ts` 的 `headers()` 也配了同样的头，两处都要保留。`/_next/static/` 下的构建文件和 `/_next/image` 不经过 Worker，不带这两个头，它们不是页面，不影响 | `moemail/middleware.ts`、`moemail/next.config.ts` |
| API Key 的范围 | 只能用于 `/api/emails` 下的接口和 `GET /api/config`。中间件和处理函数各查一遍 | `moemail/middleware.ts`、`moemail/app/lib/guard.ts` |
| 关闭图片代理接口 | `/_next/image` 的请求不进 Worker，页面也不生成这类地址。两处设置要一起保留 | `moemail/_routes.json`、`moemail/next.config.ts` |
| 注册开关 | KV 里的 `ALLOW_REGISTRATION`；没配置的第三方登录不显示；注册接口只返回 id 和用户名 | `moemail/app/lib/auth.ts`、`moemail/app/api/auth/register/route.ts` |
| 收信日志 | 只记发件人、收件地址和附件个数，不记邮件内容和文件名 | `moemail/workers/email-receiver.ts` |
| 未注册地址转发 | 收信 Worker 找不到邮箱（包括过期还没清理的）时，把整封信原样转发到 `FORWARD_TO`，不解析；信存不进数据库时也转发；转发失败时报错，不吞掉 | `moemail/workers/email-receiver.ts` |
| 邮件正文的显示方式 | 正文 HTML 放进 `blob:` 地址的独立页面里，再装进 iframe（`sandbox="allow-same-origin allow-popups"`，脚本不运行）。不能改回用 `document.write` 写进空白 iframe：那样 iframe 的地址就是外层页面的地址，在邮箱分享页上是 `/shared/<token>`，邮件里的外链图片或链接加上 `referrerpolicy="unsafe-url"`，就能通过 Referer 头拿到分享 token。深浅色切换直接改已经显示的页面，不重新加载 | `moemail/app/components/emails/email-html-frame.tsx` |
| 附件 | 存进 KV（`ATTACHMENTS`），临时邮箱的附件带到期时间。下载接口三个：本人、邮箱分享链接、单封邮件分享链接，各自按读邮件的规则检查权限；非位图一律按二进制下载，防止 HTML、SVG 附件在本站域名下执行脚本。每天和总量各有上限，给 KV 的其它用途留出免费额度。正文里的内嵌图片由页面取回后换成 `blob:` 地址显示，不把下载地址写进邮件 HTML（分享页的地址里带 token）。删除邮件、邮箱、账号时一起删，清理 Worker 每小时扫一部分漏删的 | `moemail/app/lib/attachments.ts`、`moemail/app/api/` 下的 `attachments/[index]/route.ts`、`moemail/workers/` |
| 不让搜索引擎收录 | 页面元数据里是 noindex；`.env` 里设了 `NEXT_PUBLIC_BASE_URL`，页面里的站点地址在构建时取它 | `moemail/app/[locale]/layout.tsx`、`moemail/.env` |
| 登录失败的提示和 404 页面 | 密码错误时显示“用户名或密码错误”；不存在的页面有正常的 404 页 | `moemail/app/lib/auth.ts`、`moemail/app/not-found.tsx` |
| 依赖版本 | 见[依赖版本](#依赖版本) | `moemail/package.json` |
| 同步脚本和测试脚本 | 上游没有 | `moemail/scripts/sync-to-vpsinit.sh`、`moemail/scripts/test/` |

改代码时要守的几条规矩：

- 新增 `/api` 接口要做两件事：在 `middleware.ts` 的 `API_PERMISSIONS` 里登记前缀（不需要登录的登记到 `PUBLIC_API_ROUTES`），否则一律被拒绝；处理函数开头调用 `requireUser(权限, { apiKey })`，之后只用它返回的 `userId`。
- `API_PERMISSIONS` 取第一条匹配的前缀，更具体的前缀要排在更宽的前面。
- 要让一个接口支持 API Key，中间件的 `isApiKeyAllowed` 和处理函数的 `{ apiKey: true }` 两处要一起改。
- `PUBLIC_API_ROUTES` 下的接口中间件不做任何检查，要自己保护自己。
- 要用 Server Action，得先放开中间件里“页面只接受 GET 和 HEAD”的限制。
- 中间件里凡是按路径做的判断，都要对照构建产物 `.vercel/output/config.json` 里的路由表。next-on-pages 交给中间件的是请求的原始地址，选处理函数时用的却是改写后的路径，而且不区分大小写。比如 `/_next/data/<buildId>/api/x.json` 这样的地址，进的是 `/api/x` 的处理函数。
- 改完跑 `scripts/test/run-local.sh`。

## 上游文档里不适用的地方

`moemail/README.zh-CN.md` 是上游的说明，下面几处和这套部署不一样：

- 它把 GitHub 登录写成必需的。实际上用户名密码登录一直可用，GitHub 和 Google 登录要配置了才出现。
- 它讲的 GitHub Actions 部署在本仓库不起作用：工作流文件在 `moemail/.github/` 里，不在仓库根目录。
- “Deploy to Cloudflare Workers” 按钮部署的是上游代码，不含本地改动。
- 邮箱有效期只接受 1 小时、1 天、3 天和永久，没有它写的 7 天。
- 默认角色的取值是小写的 `civilian`、`knight`、`duke`。

## 依赖版本

| 依赖 | 版本 | 为什么是这个版本 |
| --- | --- | --- |
| pnpm | 9.15.9 | 用 pnpm 10 时 next-on-pages 1.13.6 认不出本地装的 vercel，改去下载最新版的 Vercel CLI，构建失败 |
| next | 15.1.12 | 15.1.x 的最后一个补丁版本，修了上游 15.1.1 里包括远程代码执行在内的多个已公开漏洞，不能退回去。往上升也不行：按提交 `5c32548` 的记录，15.5.29 配 next-on-pages 1.13.6 能构建，但页面全部报 500，要先迁移到 OpenNext |
| next-auth、@auth/drizzle-adapter | 5.0.0-beta.32、1.11.3 | 修了上游 beta.25 里已公开的漏洞，见提交 `1e40f3c` 的说明，不能退回去。两个包要一起升，保证锁文件里只有一份 `@auth/core` |
| vercel | 39.1.1 | 上游固定的版本，next-on-pages 构建时用它 |
| drizzle-orm | `^0.36.4`，锁文件里是 0.36.4 | 上游原有的范围。不要升到 0.44 及以上：从那一版起数据库的报错信息里带 SQL 和参数，而注册和发信两个接口会把异常信息原样返回给调用方，升级前要先改这两处 |

`moemail/package-lock.json` 是上游留下的，没有随本地的升级更新，以 `moemail/pnpm-lock.yaml` 为准。

## 密钥

- `AUTH_SECRET` 既是登录会话的密钥，又掺在密码哈希里。改了它，所有账号的密码都会失效。Cloudflare 上的密钥读不回来，真实值只在工作目录的 `.env` 里，一定要另外存一份，比如放进密码管理器。
- `AUTH_SECRET` 真的丢了，只能换一个新的：用 `openssl rand -hex 32` 生成，写进工作目录 `.env` 的 `AUTH_SECRET` 并另存一份；导出部署凭据后执行 `pnpm exec wrangler pages secret put AUTH_SECRET --project-name moemail`，按提示粘贴新值；再照[更新和部署](#更新和部署)重新部署网页端，新值要等新部署上线才生效；最后按[忘了密码](#忘了密码)的办法给每个账号重设密码。那里的命令从 `.env` 读 `AUTH_SECRET`，`.env` 里不是新值的话，重设后的密码登不上。这条路没有走过。
- `CLOUDFLARE_API_TOKEN` 只在部署时用，只放在工作目录的 `.env` 里。
- 入库的 `moemail/.env` 是脱敏副本：名字以 `TOKEN`、`SECRET`、`PASSWORD`、`API_KEY`、`ACCOUNT_ID` 结尾的项，值被换成了 `xxxxxx`。以后新加密钥或账号标识类的配置项要按这个规则起名，否则同步脚本认不出来。
- 同步脚本写完以后会在目标目录里搜一遍真实密钥，搜到就报错。它只同步，不提交。
- Resend 的 API Key 在“Resend 发件服务配置”里填，Turnstile 的 Secret Key 在“网站配置”里填。它们存在 KV 里，不在 `.env` 里。
- 转发目标 `FORWARD_TO` 是私人邮箱地址，不是密钥，但也不进仓库：它只写在工作目录的 `wrangler.email.json` 里。这个文件在两边都被 `.gitignore` 忽略；不要把这个地址挪进 `.env`，同步脚本只给 `TOKEN`、`SECRET` 这类名字脱敏，它会原样进入公开仓库。

## 部署记录

每次部署后在这里加一行。“部署”一栏填 `wrangler pages deploy` 输出的地址里那 8 位短 ID；只部署了 Worker 或者做了回滚也记一行，在“内容”里写明。日期按 UTC。

文档其余部分讲的是仓库里最新的代码，线上跑的是表里最后一行对应的提交。两者不一致时，在本仓库的根目录执行 `git log <那个提交>..HEAD -- moemail` 看差了什么。

| 日期 | 部署 | 本仓库提交 | 内容 |
| --- | --- | --- | --- |
| 2026-11-26 | `820d3862`（已删除） | `cb944ae` | 首次部署：上游代码，只固定了 pnpm 的版本 |
| 2026-11-26 | `40cda5aa`（已删除） | `8ceded5` | 修复接口鉴权，加注册开关，收信日志不再带邮件内容，不让搜索引擎收录。收信 Worker 也在这一次重新部署，到 `036a9746` 才再次部署 |
| 2026-11-26 | `341c13ab`（已删除） | `6248fd7` | 接口各自检查身份和权限，禁止被 iframe 嵌入，页面只接受 GET 和 HEAD，升级 Next.js 和 next-auth，拒绝两类路径写法，关闭图片代理接口 |
| 2026-11-27 | `9cd60a46`（已删除） | `2f69b92` | 收紧 API Key 的范围，修正登录失败的提示，加 404 页面，测试脚本收进仓库 |
| 2026-11-27 | `80ac9754`（已删除） | `af31280` | 替换像素字体为现代极简界面，并完成第二轮全站 UI 打磨（深色白纸阅读与自动缩放、对比度与多语言字体、基础组件与弹层、个人中心与分享页） |
| 2026-11-27 | `a1a400b0`（已删除） | `603ae0c` | 修复手机端分享弹窗溢出遮住按钮，分享页时间改按访客时区显示 |
| 2026-11-27 | `036a9746` | `8416c18` | 未注册地址的来信转发到私人邮箱；保留附件（存 KV，删除邮件、邮箱、账号时一起删）。D1 加了 `attachments` 列（迁移 0019），收信和清理两个 Worker 同时重新部署 |
