import { createDb } from "@/lib/db"
import { emailShares, messages } from "@/lib/schema"
import { eq, and, lt, lte, or, sql, ne, isNull } from "drizzle-orm"
import { NextResponse } from "next/server"
import { encodeCursor, decodeCursor } from "@/lib/cursor"
import { hasListedAttachments } from "@/lib/attachments"

export const runtime = "edge"

const PAGE_SIZE = 20

// 通过分享token获取邮箱的消息列表
export async function GET(
  request: Request,
  { params }: { params: Promise<{ token: string }> }
) {
  const { token } = await params
  const db = createDb()
  const { searchParams } = new URL(request.url)
  const cursor = searchParams.get('cursor')

  try {
    // 验证分享token
    const share = await db.query.emailShares.findFirst({
      where: eq(emailShares.token, token),
      with: {
        email: true
      }
    })

    if (!share) {
      return NextResponse.json(
        { error: "Share link not found or expired" },
        { status: 404 }
      )
    }

    // 检查分享是否过期
    if (share.expiresAt && share.expiresAt < new Date()) {
      return NextResponse.json(
        { error: "Share link has expired" },
        { status: 410 }
      )
    }

    // 检查邮箱是否过期
    if (share.email.expiresAt < new Date()) {
      return NextResponse.json(
        { error: "Email has expired" },
        { status: 410 }
      )
    }

    const emailId = share.email.id

    // 只显示接收的邮件，不显示发送的邮件
    const baseConditions = and(
      eq(messages.emailId, emailId),
      or(
        ne(messages.type, "sent"),
        isNull(messages.type)
      )
    )

    const conditions = [baseConditions]

    if (cursor) {
      const decoded = decodeCursor(cursor)
      if (!decoded) {
        return NextResponse.json({ error: "Invalid cursor" }, { status: 400 })
      }
      const { timestamp, id } = decoded
      const time = new Date(timestamp)
      // 和 /api/emails/[id] 一样：多写一个 received_at <= T，索引才能直接从游标的位置往下读
      conditions.push(
        and(
          lte(messages.receivedAt, time),
          or(lt(messages.receivedAt, time), lt(messages.id, id))
        )
      )
    }

    const page = db.query.messages.findMany({
      // 列表只取要显示的列：正文（尤其是 HTML）可能很大，读出来再序列化很费 CPU
      columns: { id: true, fromAddress: true, toAddress: true, subject: true, receivedAt: true, sentAt: true, attachments: true },
      where: and(...conditions),
      orderBy: (messages, { desc }) => [
        desc(messages.receivedAt),
        desc(messages.id)
      ],
      limit: PAGE_SIZE + 1
    })
    // 和 /api/emails/[id] 一样：total=false 不数总数（分享页的轮询和翻页这样用），要数就和这一页放进同一个 batch
    const [results, totalResult] = searchParams.get('total') === 'false'
      ? [await page, null]
      : await db.batch([page, db.select({ count: sql<number>`count(*)` }).from(messages).where(baseConditions)])

    const hasMore = results.length > PAGE_SIZE
    const nextCursor = hasMore
      ? encodeCursor(
          results[PAGE_SIZE - 1].receivedAt.getTime(),
          results[PAGE_SIZE - 1].id
        )
      : null
    const messageList = hasMore ? results.slice(0, PAGE_SIZE) : results

    return NextResponse.json({
      messages: messageList.map(msg => ({
        id: msg.id,
        from_address: msg.fromAddress,
        to_address: msg.toAddress,
        subject: msg.subject,
        received_at: msg.receivedAt,
        sent_at: msg.sentAt,
        has_attachments: hasListedAttachments(msg.attachments)
      })),
      nextCursor,
      // 传了 total=false 时没有这个字段
      total: totalResult ? Number(totalResult[0].count) : undefined
    })
  } catch (error) {
    console.error("Failed to fetch shared messages:", error)
    return NextResponse.json(
      { error: "Failed to fetch messages" },
      { status: 500 }
    )
  }
}

