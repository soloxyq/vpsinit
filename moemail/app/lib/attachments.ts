// 收到的附件存在 KV 里（Workers 免费套餐自带，不用收费的 R2）：每个附件一个键 att/<邮件 ID>/<序号>，
// 文件名、类型、大小等记在 message.attachments（JSON）里。
// 收信 Worker、清理 Worker 和网页端都引用这个文件，所以这里不能引入 Next.js 的模块。
//
// KV 免费额度：总共 1 GB，每天 1000 次写入、1000 次删除，整个账号共用（站点配置 SITE_CONFIG 也在里面）。所以：
//   - 每天最多存 DAILY_ATTACHMENT_WRITES 个附件，全部附件合计不超过 TOTAL_ATTACHMENT_BYTES，超出时只记信息
//   - 临时邮箱的附件写入时带上到期时间，到期由 KV 自动删除（不占删除次数）
//   - 删除邮件、邮箱、用户时，接口当场删掉对应的附件
//   - 清理 Worker 每小时扫一部分，删掉对应邮件已经不存在的附件（兜底）

export interface StoredAttachment {
  filename: string
  mimeType: string
  size: number
  contentId?: string
  // 被 HTML 正文用 cid: 引用的内嵌图片：在正文里显示，不列进附件栏
  inline?: boolean
  // false：没有存下来（超过单个大小上限、超过每封数量上限，或写入失败，例如超出了免费额度）
  stored: boolean
}

// 接口返回给页面的形式
export interface AttachmentInfo extends StoredAttachment {
  index: number
}

// KV 单个值的上限是 25 MiB。Email Routing 收的整封信也不超过 25 MiB，正常碰不到
export const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024 - 1024
// 每封信最多存这么多个附件，避免一封带几百张图的信把当天的写入额度用光
export const MAX_ATTACHMENTS_PER_MESSAGE = 20
// 每天最多存这么多个附件、全部附件合计最多这么大，给站点配置等其它用途留出 KV 额度
export const DAILY_ATTACHMENT_WRITES = 600
export const TOTAL_ATTACHMENT_BYTES = 800 * 1024 * 1024
// 每封信最多记录这么多个附件的信息
const MAX_ATTACHMENT_RECORDS = 100
// 一次请求里最多删这么多个附件（免费套餐每次调用只有 10 ms CPU），剩下的由清理 Worker 的扫描删掉
const MAX_DELETES_PER_CALL = 200

export const ATTACHMENT_KEY_PREFIX = "att/"
export const attachmentKey = (messageId: string, index: number) =>
  `${ATTACHMENT_KEY_PREFIX}${messageId}/${index}`

export function parseAttachments(value: unknown): StoredAttachment[] {
  let list = value
  if (typeof list === "string") {
    try {
      list = JSON.parse(list)
    } catch {
      return []
    }
  }
  if (!Array.isArray(list)) return []
  return list.filter(
    (a): a is StoredAttachment =>
      !!a && typeof a === "object" && typeof a.filename === "string" && typeof a.size === "number"
  )
}

export const publicAttachments = (value: unknown): AttachmentInfo[] =>
  parseAttachments(value).map((a, index) => ({ ...a, filename: safeFilename(a.filename), index }))

// 是否有列在附件栏里的附件（列表里显示回形针）
export const hasListedAttachments = (value: unknown) =>
  parseAttachments(value).some((a) => !a.inline)

// ---- 收信时保存 ----

// postal-mime 解析出来的附件（只用到这些字段）
interface ParsedAttachment {
  filename: string | null
  mimeType: string
  disposition?: string | null
  related?: boolean
  contentId?: string
  content: ArrayBuffer | Uint8Array | string
}

const EXTENSIONS: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/gif": "gif",
  "image/webp": "webp",
  "application/pdf": "pdf",
  "text/plain": "txt",
  "text/calendar": "ics",
  "message/rfc822": "eml",
}

// 控制字符，以及能让文件名反向显示的 Unicode 双向控制符（防止把 “invoice‮fdp.exe” 显示成 invoiceexe.pdf）
const UNSAFE_NAME_CHARS = /[\u0000-\u001f\u007f\u200e\u200f\u202a-\u202e\u2066-\u2069]/g
// 落单的代理项：encodeURIComponent 遇到会抛错，那个附件就永远下载不了
const LONE_SURROGATES = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g

export const safeFilename = (name: string) =>
  name.replace(UNSAFE_NAME_CHARS, "").replace(LONE_SURROGATES, "\uFFFD")

function cleanFilename(name: string | null, index: number, mimeType: string) {
  // 按码点截断，不把 emoji 这类字符截成两半
  const cleaned = Array.from(safeFilename(name ?? "").replace(/[\\/]/g, "_").trim())
    .slice(0, 200)
    .join("")
  if (cleaned) return cleaned
  return `attachment-${index + 1}.${EXTENSIONS[mimeType] ?? "bin"}`
}

const cleanContentId = (id?: string) => {
  const cleaned = (id ?? "").trim().replace(/^<|>$/g, "").trim().slice(0, 200)
  return cleaned || undefined
}

// HTML 正文里用 cid: 引用到的内容 ID（小写）
function referencedContentIds(html: string) {
  const ids = new Set<string>()
  for (const match of html.matchAll(/cid:([^"'\s<>()]+)/gi)) {
    let id = match[1]
    try {
      id = decodeURIComponent(id)
    } catch {
      // 保留原样
    }
    ids.add(id.toLowerCase())
  }
  return ids
}

export interface AttachmentBudget {
  remainingWrites: number
  remainingBytes: number
}

// 今天已经存了多少个附件、目前一共存了多少字节（按数据库里还在的邮件算，近似值）
export async function attachmentBudget(db: D1Database): Promise<AttachmentBudget> {
  const startOfDay = new Date()
  startOfDay.setUTCHours(0, 0, 0, 0)
  const row = await db
    .prepare(
      `SELECT
         COALESCE(SUM(CASE WHEN m.received_at >= ? THEN 1 ELSE 0 END), 0) AS today,
         COALESCE(SUM(json_extract(j.value, '$.size')), 0) AS bytes
       FROM message m, json_each(m.attachments) j
       WHERE m.attachments IS NOT NULL AND json_extract(j.value, '$.stored') = 1`
    )
    .bind(startOfDay.getTime())
    .first<{ today: number; bytes: number }>()
  return {
    remainingWrites: DAILY_ATTACHMENT_WRITES - (row?.today ?? 0),
    remainingBytes: TOTAL_ATTACHMENT_BYTES - (row?.bytes ?? 0),
  }
}

export async function saveAttachments(
  kv: KVNamespace | undefined,
  messageId: string,
  list: ParsedAttachment[] | undefined,
  html: string | undefined,
  mailboxExpiresAt: Date,
  budget?: AttachmentBudget
): Promise<StoredAttachment[] | null> {
  if (!list || list.length === 0) return null

  // 临时邮箱的附件比邮箱晚一小时到期（清理 Worker 每小时删一次过期邮箱）；永久邮箱的不设到期
  const permanent = mailboxExpiresAt.getUTCFullYear() >= 9999
  const nowSeconds = Math.floor(Date.now() / 1000)
  const expiration = permanent
    ? undefined
    : Math.max(Math.floor(mailboxExpiresAt.getTime() / 1000) + 3600, nowSeconds + 120)

  const cids = referencedContentIds(html ?? "")
  const records = list.slice(0, MAX_ATTACHMENT_RECORDS).map((attachment, index) => {
    const bytes =
      typeof attachment.content === "string"
        ? new TextEncoder().encode(attachment.content)
        : new Uint8Array(attachment.content)
    const mimeType = (attachment.mimeType || "application/octet-stream").toLowerCase().slice(0, 100)
    const contentId = cleanContentId(attachment.contentId)
    const item: StoredAttachment = {
      filename: cleanFilename(attachment.filename, index, mimeType),
      mimeType,
      size: bytes.byteLength,
      ...(contentId ? { contentId } : {}),
      inline: !!contentId && cids.has(contentId.toLowerCase()),
      stored: false,
    }
    return { index, bytes, item }
  })

  // 名额有限时先存附件栏里的文件，再存正文里的内嵌图片（MIME 结构里内嵌图片往往排在前面）
  const order = [...records.filter((r) => !r.item.inline), ...records.filter((r) => r.item.inline)]
  let writesLeft = Math.min(MAX_ATTACHMENTS_PER_MESSAGE, budget?.remainingWrites ?? Infinity)
  let bytesLeft = budget?.remainingBytes ?? Infinity

  for (const { index, bytes, item } of order) {
    if (!kv || writesLeft <= 0) break
    if (bytes.byteLength === 0 || bytes.byteLength > MAX_ATTACHMENT_BYTES || bytes.byteLength > bytesLeft) {
      continue
    }
    try {
      await kv.put(attachmentKey(messageId, index), bytes, {
        ...(expiration ? { expiration } : {}),
        // 写入时间，清理 Worker 扫描时跳过刚写进来、邮件可能还没入库的附件
        metadata: { t: Date.now() },
      })
      item.stored = true
      writesLeft--
      bytesLeft -= bytes.byteLength
    } catch (error) {
      console.error(
        `Failed to store attachment ${index}:`,
        error instanceof Error ? error.message : String(error)
      )
    }
  }
  return records.map((r) => r.item)
}

// ---- 删除 ----

export function attachmentKeysOf(rows: { id: string; attachments: unknown }[]) {
  const keys: string[] = []
  for (const row of rows) {
    parseAttachments(row.attachments).forEach((a, index) => {
      if (a.stored) keys.push(attachmentKey(row.id, index))
    })
  }
  return keys
}

export async function deleteAttachmentKeys(kv: KVNamespace | undefined, keys: string[]) {
  if (!kv || keys.length === 0) return 0
  if (keys.length > MAX_DELETES_PER_CALL) {
    console.log(`${keys.length - MAX_DELETES_PER_CALL} attachments left for the cleanup sweep`)
  }
  const results = await Promise.allSettled(
    keys.slice(0, MAX_DELETES_PER_CALL).map((key) => kv.delete(key))
  )
  const failed = results.filter((r) => r.status === "rejected").length
  if (failed > 0) console.error(`Failed to delete ${failed} attachments`)
  return results.length - failed
}

// 清理 Worker 每小时调用一次，每次扫一片（prefix 是 att/ 加邮件 ID 的首个十六进制字符，16 小时扫完一轮）：
// 删掉对应邮件已经不存在的附件（删除接口没删成的、超出单次上限的，或者邮件没能入库的）。
// 带到期时间的键（临时邮箱的附件）跳过，它们会自己消失，不占删除额度。
// 每次最多看 maxPages 页（每页 1000 个键）、删 maxDeletes 个：KV 免费额度每天 1000 次列出、1000 次删除
export async function sweepOrphanAttachments(
  db: D1Database,
  kv: KVNamespace,
  { prefix = ATTACHMENT_KEY_PREFIX, minAgeMs = 60 * 60 * 1000, maxPages = 5, maxDeletes = 20 } = {}
) {
  const { results } = await db
    .prepare("SELECT id FROM message WHERE attachments IS NOT NULL")
    .all<{ id: string }>()
  const existing = new Set(results.map((row) => row.id))
  // 刚写进 KV、邮件可能还没入库的附件不算
  const cutoff = Date.now() - minAgeMs

  const orphans: string[] = []
  let cursor: string | undefined
  for (let page = 0; page < maxPages; page++) {
    const list = await kv.list<{ t?: number }>({ prefix, cursor })
    for (const key of list.keys) {
      if (key.expiration) continue
      const messageId = key.name.slice(ATTACHMENT_KEY_PREFIX.length).split("/")[0]
      if (!existing.has(messageId) && (key.metadata?.t ?? 0) <= cutoff) orphans.push(key.name)
    }
    if (list.list_complete || orphans.length >= maxDeletes) break
    if (page === maxPages - 1) console.log(`Attachment sweep of ${prefix} stopped after ${maxPages} pages`)
    cursor = list.cursor
  }
  return deleteAttachmentKeys(kv, orphans.slice(0, maxDeletes))
}

// ---- 下载 ----

// 浏览器能直接显示的位图按原类型返回（正文里的 cid: 内嵌图片要用），其余一律按二进制下载：
// HTML、SVG 这类附件要是在本站域名下被当成网页打开，里面的脚本就能用访问者的登录状态调接口
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp"])

const encodeRfc5987 = (value: string) =>
  encodeURIComponent(value).replace(
    /['()*]/g,
    (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`
  )

export function contentDisposition(filename: string) {
  const cleaned = safeFilename(filename)
  const ascii = cleaned.replace(/[^\x20-\x7e]/g, "_").replace(/["\\]/g, "_")
  return `attachment; filename="${ascii}"; filename*=UTF-8''${encodeRfc5987(cleaned)}`
}

const jsonError = (error: string, status: number) => Response.json({ error }, { status })

// 三个下载接口共用：调用前各自确认访问者能看这封邮件
export async function serveAttachment(
  kv: KVNamespace | undefined,
  messageId: string,
  attachments: unknown,
  indexParam: string
) {
  if (!/^\d{1,3}$/.test(indexParam)) return jsonError("Attachment not found", 404)
  const index = Number(indexParam)
  const meta = parseAttachments(attachments)[index]
  if (!meta) return jsonError("Attachment not found", 404)
  if (!meta.stored || !kv) return jsonError("Attachment was not saved", 404)

  const body = await kv.get(attachmentKey(messageId, index), "arrayBuffer")
  // KV 写入后最长约 60 秒才同步到各地，刚收到的信可能暂时读不到
  if (!body) return jsonError("Attachment is not available yet, try again in a minute", 404)

  const type = IMAGE_TYPES.has(meta.mimeType) ? meta.mimeType : "application/octet-stream"
  return new Response(body, {
    headers: {
      "Content-Type": type,
      "Content-Disposition": contentDisposition(meta.filename),
      "Content-Length": String(body.byteLength),
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "private, max-age=3600",
    },
  })
}

// ---- 显示 ----

export function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
