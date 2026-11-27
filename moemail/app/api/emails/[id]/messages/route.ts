import { NextResponse } from "next/server"
import { and, eq, isNull, ne, or } from "drizzle-orm"
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
