import { NextResponse } from "next/server"
import { createDb } from "@/lib/db"
import { emails, messages } from "@/lib/schema"
import { eq, and, lt, lte, or, sql, ne, isNull, desc } from "drizzle-orm"
import { encodeCursor, decodeCursor } from "@/lib/cursor"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { checkBasicSendPermission } from "@/lib/send-permissions"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { attachmentKeysOf, deleteAttachmentKeys, hasListedAttachments } from "@/lib/attachments"
import { likeContains, likePattern, normalizeNote, parseSearchQuery } from "@/lib/search"

export const runtime = "edge"

// 修改邮箱备注：请求体为 {"note": "字符串或 null"}，空串清空备注
export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error
  const { userId } = guard

  const rawBody: unknown = await request.json().catch(() => null)
  if (!rawBody || typeof rawBody !== "object" || Array.isArray(rawBody) || !("note" in rawBody)) {
    return NextResponse.json(
      { error: 'Body must include "note" (string or null)' },
      { status: 400 }
    )
  }
  const parsedNote = normalizeNote((rawBody as Record<string, unknown>).note)
  if (!parsedNote.ok) {
    return NextResponse.json(
      { error: parsedNote.error },
      { status: 400 }
    )
  }

  try {
    const db = createDb()
    const { id } = await params
    const updated = await db
      .update(emails)
      .set({ note: parsedNote.value })
      .where(and(eq(emails.id, id), eq(emails.userId, userId)))
      .returning({ id: emails.id })

    if (!updated[0]) {
      return NextResponse.json(
        { error: "邮箱不存在或无权限修改" },
        { status: 403 }
      )
    }

    return NextResponse.json({ id: updated[0].id, note: parsedNote.value })
  } catch (error) {
    console.error("Failed to update email note:", error)
    return NextResponse.json(
      { error: "修改备注失败" },
      { status: 500 }
    )
  }
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error
  const { userId } = guard

  try {
    const db = createDb()
    const { id } = await params
    const email = await db.query.emails.findFirst({
      where: and(
        eq(emails.id, id),
        eq(emails.userId, userId)
      )
    })

    if (!email) {
      return NextResponse.json(
        { error: "邮箱不存在或无权限删除" },
        { status: 403 }
      )
    }
    // 同一个事务里删邮件和邮箱，并拿回实际删掉的邮件（期间新到的信也算在内）
    const [deleted] = await db.batch([
      db.delete(messages)
        .where(eq(messages.emailId, id))
        .returning({ id: messages.id, attachments: messages.attachments }),
      db.delete(emails)
        .where(eq(emails.id, id)),
    ])

    // KV 里的附件在返回响应之后接着删，否则会一直占着免费额度
    const { env, ctx } = getRequestContext()
    ctx.waitUntil(deleteAttachmentKeys(env.ATTACHMENTS, attachmentKeysOf(deleted)))

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error('Failed to delete email:', error)
    return NextResponse.json(
      { error: "删除邮箱失败" },
      { status: 500 }
    )
  }
} 

const PAGE_SIZE = 20

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { searchParams } = new URL(request.url)
  const cursorStr = searchParams.get('cursor')
  const messageType = searchParams.get('type')
  const query = parseSearchQuery(searchParams.get('q'))

  try {
    const db = createDb()
    const { id } = await params

    const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
    if (guard.error) return guard.error
    const { userId, roles } = guard
    if (messageType === 'sent') {
      const permissionResult = await checkBasicSendPermission(userId, roles)
      if (!permissionResult.canSend) {
        return NextResponse.json(
          { error: permissionResult.error || "您没有查看发送邮件的权限" },
          { status: 403 }
        )
      }
    }

    let decodedCursor: ReturnType<typeof decodeCursor> = null
    if (cursorStr) {
      decodedCursor = decodeCursor(cursorStr)
      if (!decodedCursor) {
        const email = await db.query.emails.findFirst({
          columns: { id: true },
          where: and(eq(emails.id, id), eq(emails.userId, userId)),
        })
        if (!email) {
          return NextResponse.json({ error: "无权限查看" }, { status: 403 })
        }
        return NextResponse.json({ error: "Invalid cursor" }, { status: 400 })
      }
    }

    const ownedEmailExists = sql`EXISTS (SELECT 1 FROM ${emails} WHERE ${emails.id} = ${id} AND ${emails.userId} = ${userId})`
    const pattern = query ? likePattern(query) : null
    const baseConditions = and(
      eq(messages.emailId, id),
      ownedEmailExists,
      messageType === 'sent' 
        ? eq(messages.type, "sent") 
        : or(
            ne(messages.type, "sent"),
            isNull(messages.type)
          ),
      pattern
        ? or(
            likeContains(messages.subject, pattern),
            likeContains(messageType === 'sent' ? messages.toAddress : messages.fromAddress, pattern),
            likeContains(messageType === 'sent' ? messages.html : messages.content, pattern)
          )
        : undefined
    )

    const conditions = [baseConditions]
    const orderByTime = messageType === 'sent' ? messages.sentAt : messages.receivedAt

    if (decodedCursor) {
      const { timestamp, id: cursorId } = decodedCursor
      const time = new Date(timestamp)
      // 意思是 time < T 或者（time = T 且 id < I）。前面多写一个 time <= T，索引才能直接从游标的位置往下读；
      // 只写 OR 的话每一页都要从最新的邮件读起，越往后翻读的行数越多
      conditions.push(
        and(
          lte(orderByTime, time),
          or(lt(orderByTime, time), lt(messages.id, cursorId))
        )
      )
    }

    const emailCheck = db
      .select({ id: emails.id })
      .from(emails)
      .where(and(eq(emails.id, id), eq(emails.userId, userId)))
      .limit(1)

    const page = db
      .select({
        // 列表只取要显示的列：正文（尤其是 HTML）可能很大，读出来再序列化很费 CPU
        id: messages.id,
        fromAddress: messages.fromAddress,
        toAddress: messages.toAddress,
        subject: messages.subject,
        receivedAt: messages.receivedAt,
        sentAt: messages.sentAt,
        readAt: messages.readAt,
        attachments: messages.attachments,
      })
      .from(messages)
      .where(and(...conditions))
      .orderBy(desc(orderByTime), desc(messages.id))
      .limit(PAGE_SIZE + 1)
    // 总数要把这个邮箱里的邮件数一遍，读的行数和邮件数一样多，所以可以用 total=false 跳过：
    // 网页端每 10 秒的轮询和往下翻页都不数，总数在本地跟着加减。
    // 归属校验、列表查询和计数放进同一个 D1 batch：单次网络往返完成，且中间来了新邮件数字也对得上
    const [emailRows, results, totalResult] = searchParams.get('total') === 'false'
      ? [...(await db.batch([emailCheck, page])), null]
      : await db.batch([
          emailCheck,
          page,
          db.select({ count: sql<number>`count(*)` }).from(messages).where(baseConditions),
        ])

    if (!emailRows[0]) {
      return NextResponse.json(
        { error: "无权限查看" },
        { status: 403 }
      )
    }

    const hasMore = results.length > PAGE_SIZE
    const nextCursor = hasMore 
      ? encodeCursor(
          messageType === 'sent' 
            ? results[PAGE_SIZE - 1].sentAt!.getTime()
            : results[PAGE_SIZE - 1].receivedAt.getTime(),
          results[PAGE_SIZE - 1].id
        )
      : null
    const messageList = hasMore ? results.slice(0, PAGE_SIZE) : results

    return NextResponse.json({ 
      messages: messageList.map(msg => ({
        id: msg.id,
        from_address: msg?.fromAddress,
        to_address: msg?.toAddress,
        subject: msg.subject,
        sent_at: msg.sentAt?.getTime(),
        received_at: msg.receivedAt?.getTime(),
        // 读过的时间，null 是未读
        read_at: msg.readAt?.getTime() ?? null,
        has_attachments: hasListedAttachments(msg.attachments)
      })),
      nextCursor,
      // 传了 total=false 时没有这个字段
      total: totalResult ? Number(totalResult[0].count) : undefined
    })
  } catch (error) {
    console.error('Failed to fetch messages:', error)
    return NextResponse.json(
      { error: "Failed to fetch messages" },
      { status: 500 }
    )
  }
} 