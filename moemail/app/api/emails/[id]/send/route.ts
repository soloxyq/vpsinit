import { NextResponse } from "next/server"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { createDb } from "@/lib/db"
import { emails, messages, dailyUsage } from "@/lib/schema"
import { eq, sql } from "drizzle-orm"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { checkSendPermission } from "@/lib/send-permissions"
import { PublicError } from "@/lib/errors"
import { utcDay } from "@/lib/attachments"

export const runtime = "edge"

interface SendEmailRequest {
  to: string
  subject: string
  content: string
}

async function sendWithResend(
  to: string,
  subject: string,
  content: string,
  fromEmail: string,
  config: { apiKey: string }
) {
  const response = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({
      from: fromEmail,
      to: [to],
      subject: subject,
      html: content,
    }),
  })

  if (!response.ok) {
    const errorData = await response.json() as { message?: string }
    console.error('Resend API error:', errorData)
    // Resend 给的失败原因（域名没验证、收件人受限等）是写给调用方看的，发信的人要靠它排查，原样返回
    throw new PublicError(errorData.message || "Resend发送失败，请稍后重试")
  }

  return { success: true }
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
    if (guard.error) return guard.error
    const { userId } = guard

    const { id } = await params
    const db = createDb()

    const permissionResult = await checkSendPermission(userId)
    if (!permissionResult.canSend) {
      return NextResponse.json(
        { error: permissionResult.error },
        { status: 403 }
      )
    }
    
    const remainingEmails = permissionResult.remainingEmails

    const rawBody: unknown = await request.json().catch(() => null)
    if (!rawBody || typeof rawBody !== "object" || Array.isArray(rawBody)) {
      return NextResponse.json(
        { error: "无效的请求体" },
        { status: 400 }
      )
    }
    const { to, subject, content } = rawBody as Partial<SendEmailRequest>

    if (
      typeof to !== "string" ||
      typeof subject !== "string" ||
      typeof content !== "string" ||
      !to.trim() ||
      !subject.trim() ||
      !content.trim()
    ) {
      return NextResponse.json(
        { error: "收件人、主题和内容都是必填项" },
        { status: 400 }
      )
    }

    const email = await db.query.emails.findFirst({
      where: eq(emails.id, id)
    })

    if (!email) {
      return NextResponse.json(
        { error: "邮箱不存在" },
        { status: 404 }
      )
    }

    if (email.userId !== userId) {
      return NextResponse.json(
        { error: "无权访问此邮箱" },
        { status: 403 }
      )
    }

    if (email.expiresAt < new Date()) {
      return NextResponse.json(
        { error: "邮箱已过期" },
        { status: 403 }
      )
    }

    const env = getRequestContext().env
    const apiKey = await env.SITE_CONFIG.get("RESEND_API_KEY")

    if (!apiKey) {
      return NextResponse.json(
        { error: "Resend 发件服务未配置，请联系管理员" },
        { status: 500 }
      )
    }

    await sendWithResend(to.trim(), subject, content, email.address, { apiKey })

    const now = new Date()
    await db.batch([
      db.insert(messages).values({
        emailId: email.id,
        fromAddress: email.address,
        toAddress: to.trim(),
        subject,
        content: '',
        type: "sent",
        html: content,
        // 自己发出的邮件不算未读
        readAt: now,
      }),
      db
        .insert(dailyUsage)
        .values({ day: utcDay(now.getTime()), scope: `sent:${userId}`, count: 1 })
        .onConflictDoUpdate({
          target: [dailyUsage.day, dailyUsage.scope],
          set: { count: sql`${dailyUsage.count} + 1` },
        }),
    ])

    return NextResponse.json({ 
      success: true,
      message: "邮件发送成功",
      remainingEmails: remainingEmails !== undefined ? Math.max(0, remainingEmails - 1) : undefined
    })
  } catch (error) {
    console.error('Failed to send email:', error)
    // 其它错误（数据库、KV、网络）的原文只进日志，不回给客户端
    return NextResponse.json(
      { error: error instanceof PublicError ? error.message : "发送邮件失败" },
      { status: 500 }
    )
  }
} 