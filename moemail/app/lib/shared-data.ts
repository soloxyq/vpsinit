import { createDb } from "@/lib/db"
import { emailShares, messageShares, messages, emails } from "@/lib/schema"
import { eq, desc, and, or, ne, isNull } from "drizzle-orm"
import { publicAttachments, hasListedAttachments, type AttachmentInfo } from "@/lib/attachments"

export interface SharedEmail {
  id: string
  address: string
  createdAt: Date
  expiresAt: Date
}

export interface SharedMessage {
  id: string
  from_address?: string
  to_address?: string
  subject: string
  content?: string
  html?: string
  received_at?: Date
  sent_at?: Date
  expiresAt?: Date
  emailAddress?: string
  emailExpiresAt?: Date
  attachments?: AttachmentInfo[]
  has_attachments?: boolean
}

export async function getSharedEmail(token: string): Promise<SharedEmail | null> {
  const db = createDb()

  try {
    const share = await db.query.emailShares.findFirst({
      where: eq(emailShares.token, token),
      with: {
        email: true
      }
    })

    if (!share) {
      return null
    }

    // 检查分享是否过期
    if (share.expiresAt && share.expiresAt < new Date()) {
      return null
    }

    // 检查邮箱是否过期
    if (share.email.expiresAt < new Date()) {
      return null
    }

    return {
      id: share.email.id,
      address: share.email.address,
      createdAt: share.email.createdAt,
      expiresAt: share.email.expiresAt
    }
  } catch (error) {
    console.error("Failed to fetch shared email:", error)
    return null
  }
}

export interface SharedMessagesResult {
  messages: SharedMessage[]
  nextCursor: string | null
  total: number
}

export async function getSharedEmailMessages(token: string, limit = 20): Promise<SharedMessagesResult> {
  const db = createDb()

  try {
    const share = await db.query.emailShares.findFirst({
      where: eq(emailShares.token, token),
      with: {
        email: true
      }
    })

    if (!share) {
      return { messages: [], nextCursor: null, total: 0 }
    }

    // 检查分享是否过期
    if (share.expiresAt && share.expiresAt < new Date()) {
      return { messages: [], nextCursor: null, total: 0 }
    }

    // 只显示接收的邮件，不显示发送的邮件
    const baseConditions = and(
      eq(messages.emailId, share.emailId),
      or(
        ne(messages.type, "sent"),
        isNull(messages.type)
      )
    )

    // 第一页（多取一条用来判断还有没有下一页）和总数（只数收到的邮件）放进同一个 batch：
    // 分享页之后的轮询不再数总数，只在这个数上加减，所以两者得对得上
    const { sql } = await import("drizzle-orm")
    const [messageList, totalResult] = await db.batch([
      db.query.messages.findMany({
        // 列表只取要显示的列：正文（尤其是 HTML）可能很大，读出来再序列化很费 CPU
        columns: { id: true, fromAddress: true, toAddress: true, subject: true, receivedAt: true, sentAt: true, attachments: true },
        where: baseConditions,
        orderBy: [desc(messages.receivedAt), desc(messages.id)],
        limit: limit + 1
      }),
      db.select({ count: sql<number>`count(*)` }).from(messages).where(baseConditions),
    ])
    const totalCount = Number(totalResult[0].count)

    const hasMore = messageList.length > limit
    const results = hasMore ? messageList.slice(0, limit) : messageList

    // 生成下一页的cursor
    let nextCursor: string | null = null
    if (hasMore) {
      const { encodeCursor } = await import("@/lib/cursor")
      const lastMessage = results[results.length - 1]
      nextCursor = encodeCursor(
        lastMessage.receivedAt.getTime(),
        lastMessage.id
      )
    }

    return {
      messages: results.map(msg => ({
        id: msg.id,
        from_address: msg.fromAddress ?? undefined,
        to_address: msg.toAddress ?? undefined,
        subject: msg.subject,
        received_at: msg.receivedAt,
        sent_at: msg.sentAt,
        has_attachments: hasListedAttachments(msg.attachments)
      })),
      nextCursor,
      total: totalCount
    }
  } catch (error) {
    console.error("Failed to fetch shared email messages:", error)
    return { messages: [], nextCursor: null, total: 0 }
  }
}

export async function getSharedMessage(token: string): Promise<SharedMessage | null> {
  const db = createDb()

  try {
    const share = await db.query.messageShares.findFirst({
      where: eq(messageShares.token, token)
    })

    if (!share) {
      return null
    }

    // 检查分享是否过期
    if (share.expiresAt && share.expiresAt < new Date()) {
      return null
    }

    // 获取消息详情
    const message = await db.query.messages.findFirst({
      where: eq(messages.id, share.messageId)
    })

    if (!message) {
      return null
    }

    // 获取邮箱信息
    const email = await db.query.emails.findFirst({
      where: eq(emails.id, message.emailId)
    })

    return {
      id: message.id,
      from_address: message.fromAddress ?? undefined,
      to_address: message.toAddress ?? undefined,
      subject: message.subject,
      content: message.content ?? undefined,
      html: message.html ?? undefined,
      received_at: message.receivedAt,
      sent_at: message.sentAt,
      expiresAt: share.expiresAt ?? undefined,
      emailAddress: email?.address,
      emailExpiresAt: email?.expiresAt,
      attachments: publicAttachments(message.attachments)
    }
  } catch (error) {
    console.error("Failed to fetch shared message:", error)
    return null
  }
}
