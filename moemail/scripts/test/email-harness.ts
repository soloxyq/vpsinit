// 本机测试用：通过 wrangler 的 getPlatformProxy 拿到和本地 pages dev 同一份模拟 D1/KV，
// 直接调用收信 Worker 的 email() 投递一封信，或查看、清理附件。不连 Cloudflare。
// 由 attachments-suite.sh 先用 esbuild 打包成普通 JS 再用 node 运行（用 tsx 直接跑，miniflare 会报
// "Cannot set properties of undefined (setting 'compositeIndex')"），在仓库根目录调用：
//   STATE=<pages dev 的 --persist-to 目录> node <打包结果> deliver <from> <to> <eml 文件>
//   ... keys                # 列出 KV 里的附件键和到期时间
//   ... put-orphan <key> [expiring]  # 写一个没有对应邮件的附件（expiring：带到期时间）
//   ... expire <邮箱 ID>     # 把邮箱的到期时间改到过去
//   ... sweep               # 立即扫描孤儿附件（不等一小时的保护期）
// 结果打印成一行 "RESULT <json>"。
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { getPlatformProxy } from "wrangler"
import worker from "../../workers/email-receiver"
import { ATTACHMENT_KEY_PREFIX, sweepOrphanAttachments } from "../../app/lib/attachments"

async function main() {
  const state = process.env.STATE
  if (!state) throw new Error("需要环境变量 STATE")
  // attachments-suite.sh 在仓库根目录调用
  const root = process.cwd()
  const [mode, ...args] = process.argv.slice(2)

  const proxy = await getPlatformProxy<Env>({
    configPath: join(root, "wrangler.email.json"),
    persist: { path: join(state, "v3") },
  })
  const { env } = proxy
  const kv = env.ATTACHMENTS
  if (!kv) throw new Error("wrangler.email.json 里没有绑定 ATTACHMENTS")

  try {
    if (mode === "deliver") {
      const [from, to, file] = args
      const raw = readFileSync(file)
      let forwardedTo: string | null = null
      const message = {
        from,
        to,
        raw: new Response(raw).body,
        rawSize: raw.byteLength,
        headers: new Headers(),
        forward: async (rcpt: string) => {
          forwardedTo = rcpt
        },
        setReject: () => {},
        reply: async () => {},
      }
      await worker.email(message as unknown as ForwardableEmailMessage, env)
      console.log(`RESULT ${JSON.stringify({ forwardedTo })}`)
    } else if (mode === "keys") {
      const list = await kv.list({ prefix: ATTACHMENT_KEY_PREFIX })
      console.log(
        `RESULT ${JSON.stringify(list.keys.map((k) => ({ name: k.name, expiration: k.expiration ?? null })))}`
      )
    } else if (mode === "put-orphan") {
      await kv.put(args[0], "orphan", {
        metadata: { t: 0 },
        ...(args[1] === "expiring" ? { expirationTtl: 3600 } : {}),
      })
      console.log(`RESULT ${JSON.stringify({ ok: true })}`)
    } else if (mode === "expire") {
      await env.DB.prepare("UPDATE email SET expires_at = 1 WHERE id = ?").bind(args[0]).run()
      console.log(`RESULT ${JSON.stringify({ ok: true })}`)
    } else if (mode === "sweep") {
      const deleted = await sweepOrphanAttachments(env.DB, kv, { minAgeMs: 0 })
      console.log(`RESULT ${JSON.stringify({ deleted })}`)
    } else {
      throw new Error(`未知命令 ${mode}`)
    }
  } finally {
    await proxy.dispose()
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
