import { requireUser } from "@/lib/guard"
import { createDb } from "@/lib/db"
import { webhooks } from "@/lib/schema"
import { PERMISSIONS } from "@/lib/permissions"
import { isHttpsUrl } from "@/config/webhook"
import { eq } from "drizzle-orm"
import { z } from "zod"

export const runtime = "edge"

const httpsUrlSchema = z.string().url().refine(isHttpsUrl, "Webhook URL must use https://")
const webhookSchema = z
  .object({
    url: z.string(),
    enabled: z.boolean(),
  })
  .superRefine((val, ctx) => {
    // 关闭 Webhook 时允许 URL 为空；只要填了 URL 或处于开启状态，就必须是合法 https:// 地址
    if (!val.enabled && val.url.trim() === "") return
    const check = httpsUrlSchema.safeParse(val.url.trim())
    if (!check.success) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: check.error.issues[0]?.message || "Invalid Webhook URL",
        path: ["url"],
      })
    }
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