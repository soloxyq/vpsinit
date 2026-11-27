import { NextResponse } from "next/server"
import { eq } from "drizzle-orm"
import { createDb } from "@/lib/db"
import { users } from "@/lib/schema"
import { requireUser } from "@/lib/guard"
import { comparePassword, hashPassword } from "@/lib/utils"
import { authSchema } from "@/lib/validation"

export const runtime = "edge"

// 修改自己的密码：先核对当前密码，新密码的规则和注册时一样。只认登录会话，不接受 API Key
export async function POST(request: Request) {
  const guard = await requireUser(null)
  if (guard.error) return guard.error

  const body = (await request.json().catch(() => null)) as {
    currentPassword?: unknown
    newPassword?: unknown
  } | null
  const currentPassword = body?.currentPassword
  const newPassword = body?.newPassword
  if (typeof currentPassword !== "string" || typeof newPassword !== "string") {
    return NextResponse.json({ error: "参数不正确" }, { status: 400 })
  }

  const rule = authSchema.shape.password.safeParse(newPassword)
  if (!rule.success) {
    return NextResponse.json({ error: rule.error.issues[0].message }, { status: 400 })
  }

  try {
    const db = createDb()
    const user = await db.query.users.findFirst({
      where: eq(users.id, guard.userId),
      columns: { password: true },
    })
    if (!user?.password) {
      return NextResponse.json({ error: "这个账号用第三方登录，没有设置密码" }, { status: 400 })
    }
    if (!(await comparePassword(currentPassword, user.password))) {
      return NextResponse.json({ error: "当前密码不正确" }, { status: 400 })
    }

    await db
      .update(users)
      .set({ password: await hashPassword(newPassword) })
      .where(eq(users.id, guard.userId))

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error("Failed to change password:", error)
    return NextResponse.json({ error: "修改密码失败" }, { status: 500 })
  }
}
