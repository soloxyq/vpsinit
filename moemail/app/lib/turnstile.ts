import { getRequestContext } from "@cloudflare/next-on-pages"

interface TurnstileConfig {
  enabled: boolean
  siteKey: string
  secretKey: string
}

export async function getTurnstileConfig(): Promise<TurnstileConfig> {
  const env = getRequestContext().env
  const [enabled, siteKey, secretKey] = await Promise.all([
    env.SITE_CONFIG.get("TURNSTILE_ENABLED"),
    env.SITE_CONFIG.get("TURNSTILE_SITE_KEY"),
    env.SITE_CONFIG.get("TURNSTILE_SECRET_KEY"),
  ])

  return {
    enabled: enabled === "true",
    siteKey: siteKey || "",
    secretKey: secretKey || "",
  }
}

export interface TurnstileVerificationResult {
  success: boolean
  reason?: "missing-token" | "verification-failed"
}

export async function verifyTurnstileToken(token?: string | null): Promise<TurnstileVerificationResult> {
  const config = await getTurnstileConfig()

  if (!config.enabled || !config.siteKey || !config.secretKey) {
    return { success: true }
  }

  const trimmedToken = token?.trim()
  if (!trimmedToken) {
    return { success: false, reason: "missing-token" }
  }

  try {
    const response = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: `secret=${encodeURIComponent(config.secretKey)}&response=${encodeURIComponent(trimmedToken)}`,
    })

    if (!response.ok) {
      return { success: false, reason: "verification-failed" }
    }

    const data = await response.json() as { success: boolean }

    if (!data.success) {
      return { success: false, reason: "verification-failed" }
    }

    return { success: true }
  } catch (error) {
    console.error("Turnstile verification error:", error)
    return { success: false, reason: "verification-failed" }
  }
}

const REG_PASS_COOKIE = "__moemail_reg_pass"
const REG_PASS_TTL_MS = 60_000

async function hmacKey() {
  const secret = process.env.AUTH_SECRET || ""
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  )
}

function toHex(buf: ArrayBuffer) {
  return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("")
}

function fromHex(hex: string): Uint8Array | null {
  if (!/^[0-9a-f]{64}$/i.test(hex)) return null
  const out = new Uint8Array(32)
  for (let i = 0; i < 32; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16)
  return out
}

// 注册接口已消费单次 Turnstile token 后，种一个 60 秒有效的签名 Cookie，
// 供紧随其后的自动登录免于重复校验同一个 token
export async function createRegisterPassCookie(username: string) {
  const exp = Date.now() + REG_PASS_TTL_MS
  const key = await hmacKey()
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`reg:${exp}:${username}`))
  return {
    name: REG_PASS_COOKIE,
    value: `${exp}.${toHex(sig)}`,
    maxAge: Math.floor(REG_PASS_TTL_MS / 1000),
  }
}

export async function verifyRegisterPassCookie(
  cookieHeader: string | null | undefined,
  username: string
): Promise<boolean> {
  if (!cookieHeader || !process.env.AUTH_SECRET) return false
  const pair = cookieHeader
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith(`${REG_PASS_COOKIE}=`))
  if (!pair) return false
  const raw = decodeURIComponent(pair.slice(REG_PASS_COOKIE.length + 1))
  const dot = raw.indexOf(".")
  if (dot <= 0) return false
  const exp = Number(raw.slice(0, dot))
  if (!Number.isFinite(exp) || exp < Date.now()) return false
  const sigBytes = fromHex(raw.slice(dot + 1))
  if (!sigBytes) return false
  try {
    const key = await hmacKey()
    return await crypto.subtle.verify(
      "HMAC",
      key,
      sigBytes as BufferSource,
      new TextEncoder().encode(`reg:${exp}:${username}`)
    )
  } catch {
    return false
  }
}
