import { Env } from '../types'
import { drizzle } from 'drizzle-orm/d1'
import { messages, emails, webhooks } from '../app/lib/schema'
import { and, eq, gt, sql } from 'drizzle-orm'
import PostalMime from 'postal-mime'
import { WEBHOOK_CONFIG, isHttpsUrl } from '../app/config/webhook'
import { EmailMessage } from '../app/lib/webhook'
import {
  attachmentBudget,
  attachmentKeysOf,
  deleteAttachmentKeys,
  saveAttachments,
  type StoredAttachment,
} from '../app/lib/attachments'

const handleEmail = async (message: ForwardableEmailMessage, env: Env) => {
  const db = drizzle(env.DB, { schema: { messages, emails, webhooks } })

  // 过期了、但清理 Worker 还没删掉的邮箱，页面上已经看不到，按没建过处理
  const targetEmail = await db.query.emails.findFirst({
    where: and(
      eq(sql`LOWER(${emails.address})`, message.to.toLowerCase()),
      gt(emails.expiresAt, new Date())
    )
  })

  if (!targetEmail) {
    // 没在 MoeMail 里建过的地址：整封信原样转发（附件跟着信走），不解析、不入库。
    // 转发失败（例如目标地址没在 Email Routing 里验证）时把错误抛出去，
    // Email Routing 的活动日志里能看到，不会悄悄丢信。没配置转发目标就和以前一样丢弃。
    if (env.FORWARD_TO) {
      await message.forward(env.FORWARD_TO)
      console.log(`Email forwarded: ${message.from} -> ${message.to}`)
    } else {
      console.error(`Email not found: ${message.to}`)
    }
    return
  }

  const messageId = crypto.randomUUID()
  let attachments: StoredAttachment[] | null = null
  let savedMessage: typeof messages.$inferSelect

  try {
    const parsedMessage = await PostalMime.parse(message.raw)

    // 额度查不出来时照常保存，只是不按额度限制
    const budget = parsedMessage.attachments.length > 0
      ? await attachmentBudget(env.DB).catch((error) => {
          console.error('Failed to read attachment usage:', error)
          return undefined
        })
      : undefined
    attachments = await saveAttachments(
      env.ATTACHMENTS,
      messageId,
      parsedMessage.attachments,
      parsedMessage.html,
      targetEmail.expiresAt,
      budget
    )

    savedMessage = await db.insert(messages).values({
      id: messageId,
      emailId: targetEmail.id,
      fromAddress: message.from,
      subject: parsedMessage.subject || '(无主题)',
      content: parsedMessage.text || '',
      html: parsedMessage.html || '',
      type: 'received',
      attachments,
    }).returning().get()
  } catch (error) {
    // 没存进去：刚写进 KV 的附件删掉；能转发就转发到私人邮箱，免得信丢了；
    // 转发也不行就把错误抛出去，让 Email Routing 记下这次失败
    console.error('Failed to store email:', error)
    await deleteAttachmentKeys(env.ATTACHMENTS, attachmentKeysOf([{ id: messageId, attachments }]))
    if (env.FORWARD_TO) {
      await message.forward(env.FORWARD_TO)
      console.log(`Email forwarded after store failure: ${message.from} -> ${message.to}`)
      return
    }
    throw error
  }

  // 信已经入库，webhook 出错只记日志，不能让 Email Routing 当成投递失败而重发
  try {
    const webhook = await db.query.webhooks.findFirst({
      where: eq(webhooks.userId, targetEmail.userId!)
    })

    if (webhook?.enabled && isHttpsUrl(webhook.url)) {
      await fetch(webhook.url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Webhook-Event': WEBHOOK_CONFIG.EVENTS.NEW_MESSAGE
        },
        body: JSON.stringify({
          emailId: targetEmail.id,
          messageId: savedMessage.id,
          fromAddress: savedMessage.fromAddress,
          subject: savedMessage.subject,
          content: savedMessage.content,
          html: savedMessage.html,
          receivedAt: savedMessage.receivedAt.toISOString(),
          toAddress: targetEmail.address
        } as EmailMessage),
        signal: AbortSignal.timeout(WEBHOOK_CONFIG.TIMEOUT),
      })
    }
  } catch (error) {
    console.error('Failed to send webhook:', error)
  }

  // 日志只记收发双方和附件个数：正文、主题和文件名里常有验证码等私人内容
  const attachmentNote = attachments
    ? `, attachments stored ${attachments.filter(a => a.stored).length}/${attachments.length}`
    : ''
  console.log(`Email processed: ${message.from} -> ${message.to}${attachmentNote}`)
}

const worker = {
  async email(message: ForwardableEmailMessage, env: Env): Promise<void> {
    await handleEmail(message, env)
  }
}

export default worker
