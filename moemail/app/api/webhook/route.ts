import { requireUser } from "@/lib/guard"
import { createDb } from "@/lib/db"
import { webhooks } from "@/lib/schema"
import { PERMISSIONS } from "@/lib/permissions"
import { eq } from "drizzle-orm"
import { z } from "zod"

export const runtime = "edge"

const webhookSchema = z.object({
  url: z.string().url(),
  enabled: z.boolean()
})

export async function GET() {
  const guard = await requireUser(PERMISSIONS.MANAGE_WEBHOOK)
  if (guard.error) return guard.error
  const { userId } = guard

  const db = createDb()
  const webhook = await db.query.webhooks.findFirst({
    where: eq(webhooks.userId, userId)
  })

  return Response.json(webhook || { enabled: false, url: "" })
}

export async function POST(request: Request) {
  const guard = await requireUser(PERMISSIONS.MANAGE_WEBHOOK)
  if (guard.error) return guard.error
  const { userId } = guard

  try {
    const body = await request.json()
    const { url, enabled } = webhookSchema.parse(body)
    
    const db = createDb()
    const now = new Date()

    const existingWebhook = await db.query.webhooks.findFirst({
      where: eq(webhooks.userId, userId)
    })

    if (existingWebhook) {
      await db
        .update(webhooks)
        .set({
          url,
          enabled,
          updatedAt: now
        })
        .where(eq(webhooks.userId, userId))
    } else {
      await db
        .insert(webhooks)
        .values({
          userId: userId,
          url,
          enabled,
        })
    }

    return Response.json({ success: true })
  } catch (error) {
    console.error("Failed to save webhook:", error)
    return Response.json(
      { error: "Invalid request" },
      { status: 400 }
    )
  }
} 