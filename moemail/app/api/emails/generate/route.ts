import { NextResponse } from "next/server"
import { nanoid } from "nanoid"
import { createDb } from "@/lib/db"
import { emails } from "@/lib/schema"
import { eq, and, gt, sql } from "drizzle-orm"
import { EXPIRY_OPTIONS } from "@/types/email"
import { EMAIL_CONFIG } from "@/config"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { requireUser } from "@/lib/guard"
import { ROLES, PERMISSIONS } from "@/lib/permissions"
import { normalizeNote } from "@/lib/search"

export const runtime = "edge"

export async function POST(request: Request) {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error
  const { userId, roles } = guard

  const db = createDb()
  const env = getRequestContext().env

  try {
    if (!roles.includes(ROLES.EMPEROR)) {
      const maxEmails = await env.SITE_CONFIG.get("MAX_EMAILS") || EMAIL_CONFIG.MAX_ACTIVE_EMAILS.toString()
      const activeEmailsCount = await db
        .select({ count: sql<number>`count(*)` })
        .from(emails)
        .where(
          and(
            eq(emails.userId, userId),
            gt(emails.expiresAt, new Date())
          )
        )
      
      if (Number(activeEmailsCount[0].count) >= Number(maxEmails)) {
        return NextResponse.json(
          { error: `已达到最大邮箱数量限制 (${maxEmails})` },
          { status: 403 }
        )
      }
    }

    const rawBody: unknown = await request.json().catch(() => null)
    if (!rawBody || typeof rawBody !== "object" || Array.isArray(rawBody)) {
      return NextResponse.json(
        { error: "无效的请求体" },
        { status: 400 }
      )
    }
    const { name, expiryTime, domain, note } = rawBody as { 
      name?: unknown
      expiryTime?: unknown
      domain?: unknown
      note?: unknown
    }

    if (name !== undefined && typeof name !== "string") {
      return NextResponse.json({ error: "无效的邮箱前缀" }, { status: 400 })
    }

    const parsedNote = normalizeNote(note)
    if (!parsedNote.ok) {
      return NextResponse.json(
        { error: parsedNote.error },
        { status: 400 }
      )
    }

    if (typeof expiryTime !== "number" || !EXPIRY_OPTIONS.some(option => option.value === expiryTime)) {
      return NextResponse.json(
        { error: "无效的过期时间" },
        { status: 400 }
      )
    }

    const domainString = await env.SITE_CONFIG.get("EMAIL_DOMAINS")
    const rawDomains = domainString
      ? domainString.split(',').map(d => d.trim()).filter(Boolean)
      : []
    const domains = rawDomains.length > 0 ? rawDomains : ["moemail.app"]
    const trimmedDomain = typeof domain === "string" ? domain.trim() : ""

    if (!trimmedDomain || !domains.includes(trimmedDomain)) {
      return NextResponse.json(
        { error: "无效的域名" },
        { status: 400 }
      )
    }

    const trimmedName = typeof name === "string" ? name.trim() : ""
    const address = `${trimmedName || nanoid(8)}@${trimmedDomain}`
    const existingEmail = await db.query.emails.findFirst({
      where: eq(sql`LOWER(${emails.address})`, address.toLowerCase())
    })

    if (existingEmail) {
      return NextResponse.json(
        { error: "该邮箱地址已被使用" },
        { status: 409 }
      )
    }

    const now = new Date()
    const expires = expiryTime === 0 
      ? new Date('9999-01-01T00:00:00.000Z')
      : new Date(now.getTime() + expiryTime)
    
    const emailData: typeof emails.$inferInsert = {
      address,
      note: parsedNote.value,
      createdAt: now,
      expiresAt: expires,
      userId: userId
    }
    
    const result = await db.insert(emails)
      .values(emailData)
      .returning({ id: emails.id, address: emails.address, note: emails.note })
    
    return NextResponse.json({ 
      id: result[0].id,
      email: result[0].address,
      note: result[0].note,
    })
  } catch (error) {
    if (error instanceof Error && /UNIQUE constraint failed/i.test(error.message)) {
      return NextResponse.json(
        { error: "该邮箱地址已被使用" },
        { status: 409 }
      )
    }
    console.error('Failed to generate email:', error)
    return NextResponse.json(
      { error: "创建邮箱失败" },
      { status: 500 }
    )
  }
} 