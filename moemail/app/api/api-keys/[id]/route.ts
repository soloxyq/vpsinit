import { createDb } from "@/lib/db"
import { apiKeys } from "@/lib/schema"
import { NextResponse } from "next/server"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { eq, and } from "drizzle-orm"

export const runtime = "edge"

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const guard = await requireUser(PERMISSIONS.MANAGE_API_KEY)
  if (guard.error) return guard.error
  const { userId } = guard
  try {
    const db = createDb()
    const { id } = await params
    
    const result = await db.delete(apiKeys)
      .where(
        and(
          eq(apiKeys.id, id),
          eq(apiKeys.userId, userId)
        )
      )
      .returning()

    if (!result.length) {
      return NextResponse.json(
        { error: "API Key 不存在或无权删除" },
        { status: 404 }
      )
    }

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error("Failed to delete API key:", error)
    return NextResponse.json(
      { error: "删除 API Key 失败" },
      { status: 500 }
    )
  }
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const guard = await requireUser(PERMISSIONS.MANAGE_API_KEY)
  if (guard.error) return guard.error
  const { userId } = guard

  try {
    const { id } = await params

    const rawBody: unknown = await request.json().catch(() => null)
    if (
      !rawBody ||
      typeof rawBody !== "object" ||
      Array.isArray(rawBody) ||
      typeof (rawBody as { enabled?: unknown }).enabled !== "boolean"
    ) {
      return NextResponse.json(
        { error: "enabled 必须是布尔值" },
        { status: 400 }
      )
    }
    const { enabled } = rawBody as { enabled: boolean }
    const db = createDb()
    
    const result = await db.update(apiKeys)
      .set({ enabled })
      .where(
        and(
          eq(apiKeys.id, id),
          eq(apiKeys.userId, userId)
        )
      )
      .returning()

    if (!result.length) {
      return NextResponse.json(
        { error: "API Key 不存在或无权更新" },
        { status: 404 }
      )
    }

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error("Failed to update API key:", error)
    return NextResponse.json(
      { error: "更新 API Key 失败" },
      { status: 500 }
    )
  }
} 