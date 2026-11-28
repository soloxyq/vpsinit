import { NextResponse } from "next/server"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { createDb } from "@/lib/db"
import { emails, messageShares, messages } from "@/lib/schema"
import { eq } from "drizzle-orm"
import { serveAttachment } from "@/lib/attachments"

export const runtime = "edge"

// 凭单封邮件的分享链接下载附件，检查和 ../../route.ts（读邮件）一致
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ token: string; index: string }> }
) {
  try {
    const { token, index } = await params
    const db = createDb()

    const share = await db.query.messageShares.findFirst({
      where: eq(messageShares.token, token)
    })
    if (!share) {
      return NextResponse.json({ error: "Share link not found or disabled" }, { status: 404 })
    }
    if (share.expiresAt && share.expiresAt < new Date()) {
      return NextResponse.json({ error: "Share link has expired" }, { status: 410 })
    }

    const message = await db.query.messages.findFirst({
      where: eq(messages.id, share.messageId)
    })
    if (!message) {
      return NextResponse.json({ error: "Message not found" }, { status: 404 })
    }

    const email = await db.query.emails.findFirst({
      where: eq(emails.id, message.emailId),
      columns: { expiresAt: true },
    })
    if (!email || email.expiresAt < new Date()) {
      return NextResponse.json({ error: "Email has expired" }, { status: 410 })
    }

    return await serveAttachment(getRequestContext().env.ATTACHMENTS, message.id, message.attachments, index)
  } catch (error) {
    console.error("Failed to fetch shared attachment:", error)
    return NextResponse.json({ error: "Failed to fetch attachment" }, { status: 500 })
  }
}
