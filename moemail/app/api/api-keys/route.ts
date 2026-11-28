import { createDb } from "@/lib/db"
import { apiKeys } from "@/lib/schema"
import { nanoid } from "nanoid"
import { NextResponse } from "next/server"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { and, desc, eq } from "drizzle-orm"

export const runtime = "edge"

export async function GET() {
  const guard = await requireUser(PERMISSIONS.MANAGE_API_KEY)
  if (guard.error) return guard.error
  const { userId } = guard
  try {
    const db = createDb()
    const keys = await db.query.apiKeys.findMany({
      where: eq(apiKeys.userId, userId),
      orderBy: desc(apiKeys.createdAt),
    })

    return NextResponse.json({
      apiKeys: keys.map(key => ({
        ...key,
        key: undefined
      }))
    })
  } catch (error) {
    console.error("Failed to fetch API keys:", error)
    return NextResponse.json(
      { error: "获取 API Keys 失败" },
      { status: 500 }
    )
  }
}

export async function POST(request: Request) {
  const guard = await requireUser(PERMISSIONS.MANAGE_API_KEY)
  if (guard.error) return guard.error
  const { userId } = guard
  try {
    const rawBody: unknown = await request.json().catch(() => null)
    if (!rawBody || typeof rawBody !== "object" || Array.isArray(rawBody)) {
      return NextResponse.json({ error: "无效的请求体" }, { status: 400 })
    }
    const rawName = (rawBody as { name?: unknown }).name
    const trimmedName = typeof rawName === "string" ? rawName.trim() : ""
    if (!trimmedName) {
      return NextResponse.json(
        { error: "名称不能为空" },
        { status: 400 }
      )
    }

    const db = createDb()
    const existing = await db.query.apiKeys.findFirst({
      where: and(eq(apiKeys.userId, userId), eq(apiKeys.name, trimmedName)),
    })
    if (existing) {
      return NextResponse.json(
        { error: "该名称的 API Key 已存在" },
        { status: 409 }
      )
    }

    const key = `mk_${nanoid(32)}`
    await db.insert(apiKeys).values({
      name: trimmedName,
      key,
      userId: userId,
      expiresAt: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000), // 1 year
    })

    return NextResponse.json({ key })
  } catch (error) {
    if (error instanceof Error && /UNIQUE constraint failed/i.test(error.message)) {
      return NextResponse.json(
        { error: "该名称的 API Key 已存在" },
        { status: 409 }
      )
    }
    console.error("Failed to create API key:", error)
    return NextResponse.json(
      { error: "创建 API Key 失败" },
      { status: 500 }
    )
  }
} 