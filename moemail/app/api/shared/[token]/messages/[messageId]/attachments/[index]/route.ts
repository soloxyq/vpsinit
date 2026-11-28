import { NextResponse } from "next/server"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { createDb } from "@/lib/db"
import { emailShares, messages } from "@/lib/schema"
import { and, eq, isNull, ne, or } from "drizzle-orm"
import { serveAttachment } from "@/lib/attachments"

export const runtime = "edge"

// 凭邮箱分享链接下载其中一封邮件的附件，检查和 ../../route.ts（读邮件）一致
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ token: string; messageId: string; index: string }> }
) {
  try {
    const { token, messageId, index } = await params
    const db = createDb()

    const share = await db.query.emailShares.findFirst({
      where: eq(emailShares.token, token),
      with: { email: true }
    })
    if (!share) {
      return NextResponse.json({ error: "Share link not found or expired" }, { status: 404 })
    }
    if (share.expiresAt && share.expiresAt < new Date()) {
      return NextResponse.json({ error: "Share link has expired" }, { status: 410 })
    }
    if (share.email.expiresAt < new Date()) {
      return NextResponse.json({ error: "Email has expired" }, { status: 410 })
    }

    const message = await db.query.messages.findFirst({
      where: and(
        eq(messages.id, messageId),
        eq(messages.emailId, share.email.id),
        or(ne(messages.type, "sent"), isNull(messages.type))
      )
    })
    if (!message) {
      return NextResponse.json({ error: "Message not found" }, { status: 404 })
    }

    return await serveAttachment(getRequestContext().env.ATTACHMENTS, message.id, message.attachments, index)
  } catch (error) {
    console.error("Failed to fetch shared attachment:", error)
    return NextResponse.json({ error: "Failed to fetch attachment" }, { status: 500 })
  }
}
