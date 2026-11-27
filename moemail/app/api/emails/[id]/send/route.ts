import { NextResponse } from "next/server"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { createDb } from "@/lib/db"
import { emails, messages } from "@/lib/schema"
import { eq } from "drizzle-orm"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { checkSendPermission } from "@/lib/send-permissions"
import { PublicError } from "@/lib/errors"

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

    const { to, subject, content } = await request.json() as SendEmailRequest

    if (!to || !subject || !content) {
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

    const env = getRequestContext().env
    const apiKey = await env.SITE_CONFIG.get("RESEND_API_KEY")

    if (!apiKey) {
      return NextResponse.json(
        { error: "Resend 发件服务未配置，请联系管理员" },
        { status: 500 }
      )
    }

    await sendWithResend(to, subject, content, email.address, { apiKey })

    await db.insert(messages).values({
      emailId: email.id,
      fromAddress: email.address,
      toAddress: to,
      subject,
      content: '',
      type: "sent",
      html: content,
      // 自己发出的邮件不算未读
      readAt: new Date()
    })

    return NextResponse.json({ 
      success: true,
      message: "邮件发送成功",
      remainingEmails
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