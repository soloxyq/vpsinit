import { NextResponse } from "next/server"
import { register, isRegistrationOpen } from "@/lib/auth"
import { authSchema } from "@/lib/validation"
import { createRegisterPassCookie, verifyTurnstileToken } from "@/lib/turnstile"
import { PublicError } from "@/lib/errors"

export const runtime = "edge"

export async function POST(request: Request) {
  try {
    if (!await isRegistrationOpen()) {
      return NextResponse.json({ error: "注册已关闭" }, { status: 403 })
    }

    const rawJson: unknown = await request.json().catch(() => null)
    if (!rawJson || typeof rawJson !== "object" || Array.isArray(rawJson)) {
      return NextResponse.json({ error: "请求格式不正确" }, { status: 400 })
    }

    // 只回第一条校验提示（validation.ts 里写给用户看的那句）：ZodError 的 message 是整段 issues 的 JSON
    const parsed = authSchema.safeParse(rawJson)
    if (!parsed.success) {
      return NextResponse.json(
        { error: parsed.error.issues[0]?.message ?? "输入格式不正确" },
        { status: 400 }
      )
    }

    const { username, password, turnstileToken } = parsed.data

    const verification = await verifyTurnstileToken(turnstileToken)
    if (!verification.success) {
      const message = verification.reason === "missing-token"
        ? "请先完成安全验证"
        : "安全验证未通过"
      return NextResponse.json({ error: message }, { status: 400 })
    }

    const user = await register(username, password)
    const passCookie = await createRegisterPassCookie(user.username!)

    // 只回必要字段：整行数据里带着密码哈希
    const response = NextResponse.json({ user: { id: user.id, username: user.username } })
    response.cookies.set(passCookie.name, passCookie.value, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: passCookie.maxAge,
    })
    return response
  } catch (error) {
    // 用户名已存在
    if (error instanceof PublicError) {
      return NextResponse.json({ error: error.message }, { status: 409 })
    }
    // 其它错误（数据库、KV）的原文只进日志，不回给客户端
    console.error("Failed to register:", error)
    return NextResponse.json({ error: "注册失败" }, { status: 500 })
  }
}
