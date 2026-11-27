import { NextResponse } from "next/server"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { createDb } from "@/lib/db"
import { messages, emails } from "@/lib/schema"
import { and, eq } from "drizzle-orm"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { serveAttachment } from "@/lib/attachments"

export const runtime = "edge"

// 下载自己邮箱里一封邮件的附件
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string; messageId: string; index: string }> }
) {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error
  const { userId } = guard

  try {
    const { id, messageId, index } = await params
    const db = createDb()

    const email = await db.query.emails.findFirst({
      where: and(eq(emails.id, id), eq(emails.userId, userId))
    })
    if (!email) {
      return NextResponse.json({ error: "无权限查看" }, { status: 403 })
    }

    const message = await db.query.messages.findFirst({
      where: and(eq(messages.id, messageId), eq(messages.emailId, id))
    })
    if (!message) {
      return NextResponse.json({ error: "Message not found" }, { status: 404 })
    }

    return await serveAttachment(getRequestContext().env.ATTACHMENTS, message.id, message.attachments, index)
  } catch (error) {
    console.error("Failed to fetch attachment:", error)
    return NextResponse.json({ error: "Failed to fetch attachment" }, { status: 500 })
  }
}
