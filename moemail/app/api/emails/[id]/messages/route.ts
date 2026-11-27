import { NextResponse } from "next/server"
import { and, eq, isNull, ne, or, sql } from "drizzle-orm"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { createDb } from "@/lib/db"
import { emails, messages } from "@/lib/schema"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { attachmentKeysOf, deleteAttachmentKeys } from "@/lib/attachments"

export const runtime = "edge"

// 清空邮箱里的邮件：默认清空收到的，?type=sent 清空发出的。
// 邮件的分享链接由外键级联删除；KV 里的附件在返回响应之后接着删
export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error

  try {
    const db = createDb()
    const { id } = await params
    const email = await db.query.emails.findFirst({
      where: and(eq(emails.id, id), eq(emails.userId, guard.userId)),
    })
    if (!email) {
      return NextResponse.json(
        { error: "Email not found or no permission to view" },
        { status: 403 }
      )
    }

    const sent = new URL(request.url).searchParams.get("type") === "sent"
    const deleted = await db
      .delete(messages)
      .where(
        and(
          eq(messages.emailId, id),
          sent ? eq(messages.type, "sent") : or(ne(messages.type, "sent"), isNull(messages.type))
        )
      )
      .returning({ id: messages.id, attachments: messages.attachments })

    const { env, ctx } = getRequestContext()
    ctx.waitUntil(deleteAttachmentKeys(env.ATTACHMENTS, attachmentKeysOf(deleted)))

    return NextResponse.json({ success: true, deleted: deleted.length })
  } catch (error) {
    console.error("Failed to clear messages:", error)
    return NextResponse.json({ error: "Failed to clear messages" }, { status: 500 })
  }
}

// 把邮箱里的邮件标成已读，请求体是 {"read": true}。发出的邮件写入时就是已读，所以实际改到的只有收到的。
// 再带上 "before"（毫秒时间戳）就只标这个时间和它之前收到的：网页端传列表里最新一封的时间，
// 免得把点按钮时还没显示出来的新邮件一起标掉
export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error

  const body = (await request.json().catch(() => null)) as { read?: unknown; before?: unknown } | null
  const before = body?.before
  if (body?.read !== true || (before !== undefined && !Number.isFinite(before))) {
    return NextResponse.json(
      { error: 'Body must be {"read": true}, optionally with a numeric "before"' },
      { status: 400 }
    )
  }

  try {
    const db = createDb()
    const { id } = await params
    const email = await db.query.emails.findFirst({
      where: and(eq(emails.id, id), eq(emails.userId, guard.userId)),
    })
    if (!email) {
      return NextResponse.json(
        { error: "Email not found or no permission to view" },
        { status: 403 }
      )
    }

    await db
      .update(messages)
      .set({ readAt: new Date() })
      .where(
        and(
          eq(messages.emailId, id),
          isNull(messages.readAt),
          // 直接拿数字比（列里存的就是毫秒）：转成 Date 的话，过大的数字会变成无效日期
          before === undefined ? undefined : sql`${messages.receivedAt} <= ${before}`
        )
      )

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error("Failed to mark messages as read:", error)
    return NextResponse.json({ error: "Failed to mark messages as read" }, { status: 500 })
  }
}
