import { NextResponse } from "next/server"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { createDb } from "@/lib/db"
import { emails, messages } from "@/lib/schema"
import { eq } from "drizzle-orm"
import { getRequestContext } from "@cloudflare/next-on-pages"
import {
  getSendPermissionAndLimit,
  refundDailySendQuota,
  reserveDailySendQuota,
} from "@/lib/send-permissions"
import { PublicError } from "@/lib/errors"

export const runtime = "edge"

const RESEND_DEFAULT_URL = "https://api.resend.com/emails"
const RESEND_TIMEOUT_MS = 15_000

// Resend 返回 HTTP 4xx 明确拒收（未入队），可退回预占额度；5xx 或网络超时结果未知，保留预占
class ResendRejectedError extends PublicError {}

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
  config: { apiKey: string; apiUrl?: string }
) {
  const response = await fetch(config.apiUrl || RESEND_DEFAULT_URL, {
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
    signal: AbortSignal.timeout(RESEND_TIMEOUT_MS),
  })

  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { message?: string }
    console.error('Resend API error:', response.status, errorData)
    // Resend 给的失败原因（域名没验证、收件人受限等）是写给调用方看的，发信的人要靠它排查，原样返回
    const message = errorData.message || "Resend发送失败，请稍后重试"
    if (response.status >= 400 && response.status < 500) {
      throw new ResendRejectedError(message)
    }
    throw new PublicError(message)
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

    const permission = await getSendPermissionAndLimit(userId, guard.roles)
    if (!permission.canSend) {
      return NextResponse.json(
        { error: permission.error },
        { status: 403 }
      )
    }

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

    // 所有本地校验通过后，先在 D1 用单条条件写语句预占当天 1 封额度，预占成功才调 Resend
    const reservation = await reserveDailySendQuota(env.DB, userId, permission.dailyLimit)
    if (!reservation.reserved) {
      return NextResponse.json(
        { error: `您今天已达到发件限制 (${permission.dailyLimit} 封)，请明天再试` },
        { status: 403 }
      )
    }

    try {
      await sendWithResend(to.trim(), subject, content, email.address, {
        apiKey,
        apiUrl: env.RESEND_API_URL,
      })
    } catch (sendError) {
      if (sendError instanceof ResendRejectedError) {
        await refundDailySendQuota(env.DB, userId, reservation.day).catch((refundErr) => {
          console.error("Failed to refund daily send quota:", refundErr)
        })
      }
      throw sendError
    }

    const now = new Date()
    await db.insert(messages).values({
      emailId: email.id,
      fromAddress: email.address,
      toAddress: to.trim(),
      subject,
      content: '',
      type: "sent",
      html: content,
      // 自己发出的邮件不算未读
      readAt: now,
    })

    return NextResponse.json({ 
      success: true,
      message: "邮件发送成功",
      remainingEmails: reservation.remainingEmails
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