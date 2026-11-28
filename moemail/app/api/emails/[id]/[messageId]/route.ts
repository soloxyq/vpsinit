import { NextResponse } from "next/server"
import { createDb } from "@/lib/db"
import { messages, emails } from "@/lib/schema"
import { and, eq, isNull, sql } from "drizzle-orm"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { attachmentKeysOf, deleteAttachmentKeys, publicAttachments } from "@/lib/attachments"
export const runtime = "edge"

export async function DELETE(
    request: Request,
    { params }: { params: Promise<{ id: string; messageId: string }> }
) {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error
  const { userId } = guard

  try {
    const db = createDb()
    const { id, messageId } = await params
    const ownedEmailExists = sql`EXISTS (SELECT 1 FROM ${emails} WHERE ${emails.id} = ${id} AND ${emails.userId} = ${userId})`
    const [emailRows, deletedMessages] = await db.batch([
      db
        .select({ id: emails.id })
        .from(emails)
        .where(and(eq(emails.id, id), eq(emails.userId, userId)))
        .limit(1),
      db
        .delete(messages)
        .where(and(eq(messages.id, messageId), eq(messages.emailId, id), ownedEmailExists))
        .returning({ id: messages.id, attachments: messages.attachments }),
    ])

    if (!emailRows[0]) {
      return NextResponse.json(
          { error: "Email not found or no permission to view" },
          { status: 403 }
      )
    }

    if (!deletedMessages[0]) {
      return NextResponse.json(
          { error: "Message not found or already deleted" },
          { status: 404 }
      )
    }

    // 附件在 KV 里，邮件删了要一起删，否则会一直占着免费额度。返回响应之后接着删
    const { env, ctx } = getRequestContext()
    ctx.waitUntil(deleteAttachmentKeys(env.ATTACHMENTS, attachmentKeysOf(deletedMessages)))

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error('Failed to delete email:', error)
    return NextResponse.json(
        { error: "Failed to delete message" },
        { status: 500 }
    )
  }
}

export async function GET(_request: Request, { params }: { params: Promise<{ id: string; messageId: string }> }) {
  try {
    const { id, messageId } = await params
    const db = createDb()
    const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
    if (guard.error) return guard.error
    const { userId } = guard

    // 邮箱归属校验、读取邮件内容（拿读取前的 read_at）与标记已读放在同一次 D1 batch 往返内顺序执行：
    // 既把 3 次跨区串行查询压成 1 次，又保证邮件不属于当前用户时 EXISTS 为假、不会误读或误标已读。
    const ownedEmailExists = sql`EXISTS (SELECT 1 FROM ${emails} WHERE ${emails.id} = ${id} AND ${emails.userId} = ${userId})`
    const [emailRows, messageRows] = await db.batch([
      db
        .select({ id: emails.id })
        .from(emails)
        .where(and(eq(emails.id, id), eq(emails.userId, userId)))
        .limit(1),
      db
        .select()
        .from(messages)
        .where(and(eq(messages.id, messageId), eq(messages.emailId, id), ownedEmailExists))
        .limit(1),
      db
        .update(messages)
        .set({ readAt: new Date() })
        .where(
          and(
            eq(messages.id, messageId),
            eq(messages.emailId, id),
            isNull(messages.readAt),
            ownedEmailExists
          )
        ),
    ])

    if (!emailRows[0]) {
      return NextResponse.json(
        { error: "无权限查看" },
        { status: 403 }
      )
    }

    const message = messageRows[0]
    if (!message) {
      return NextResponse.json(
        { error: "Message not found" },
        { status: 404 }
      )
    }

    return NextResponse.json({
      message: {
        id: message.id,
        from_address: message.fromAddress,
        to_address: message.toAddress,
        subject: message.subject,
        content: message.content,
        html: message.html,
        received_at: message.receivedAt.getTime(),
        sent_at: message.receivedAt.getTime(),
        type: message.type as 'received' | 'sent',
        // 这次读取之前的值：null 表示原来是未读，刚被这次读取记成已读
        read_at: message.readAt?.getTime() ?? null,
        attachments: publicAttachments(message.attachments)
      }
    })
  } catch (error) {
    console.error('Failed to fetch message:', error)
    return NextResponse.json(
      { error: "Failed to fetch message" },
      { status: 500 }
    )
  }
} 