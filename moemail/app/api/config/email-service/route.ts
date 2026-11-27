import { NextResponse } from "next/server"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { EMAIL_CONFIG } from "@/config"

export const runtime = "edge"

interface EmailServiceConfig {
  enabled: boolean
  apiKey: string
  roleLimits: {
    duke?: number
    knight?: number
  }
}

export async function GET() {
  const guard = await requireUser(PERMISSIONS.MANAGE_CONFIG)
  if (guard.error) return guard.error

  try {
    const env = getRequestContext().env
    const [enabled, apiKey, roleLimits] = await Promise.all([
      env.SITE_CONFIG.get("EMAIL_SERVICE_ENABLED"),
      env.SITE_CONFIG.get("RESEND_API_KEY"),
      env.SITE_CONFIG.get("EMAIL_ROLE_LIMITS")
    ])

    const customLimits = roleLimits ? JSON.parse(roleLimits) : {}
    
    const finalLimits = {
      duke: customLimits.duke !== undefined ? customLimits.duke : EMAIL_CONFIG.DEFAULT_DAILY_SEND_LIMITS.duke,
      knight: customLimits.knight !== undefined ? customLimits.knight : EMAIL_CONFIG.DEFAULT_DAILY_SEND_LIMITS.knight,
    }

    return NextResponse.json({
      enabled: enabled === "true",
      apiKey: apiKey || "",
      roleLimits: finalLimits
    })
  } catch (error) {
    console.error("Failed to get email service config:", error)
    return NextResponse.json(
      { error: "获取 Resend 发件服务配置失败" },
      { status: 500 }
    )
  }
}

export async function POST(request: Request) {
  const guard = await requireUser(PERMISSIONS.MANAGE_CONFIG)
  if (guard.error) return guard.error

  try {
    const config = await request.json() as EmailServiceConfig

    if (config.enabled && !config.apiKey) {
      return NextResponse.json(
        { error: "启用 Resend 时，API Key 为必填项" },
        { status: 400 }
      )
    }

    const env = getRequestContext().env
    
    const customLimits: { duke?: number; knight?: number } = {}
    if (config.roleLimits?.duke !== undefined) {
      customLimits.duke = config.roleLimits.duke
    }
    if (config.roleLimits?.knight !== undefined) {
      customLimits.knight = config.roleLimits.knight
    }

    await Promise.all([
      env.SITE_CONFIG.put("EMAIL_SERVICE_ENABLED", config.enabled.toString()),
      env.SITE_CONFIG.put("RESEND_API_KEY", config.apiKey),
      env.SITE_CONFIG.put("EMAIL_ROLE_LIMITS", JSON.stringify(customLimits))
    ])

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error("Failed to save email service config:", error)
    return NextResponse.json(
      { error: "保存 Resend 发件服务配置失败" },
      { status: 500 }
    )
  }
} 