import { NextResponse } from "next/server"
import { headers } from "next/headers"
import { resolveRequestAuth } from "./auth"
import { hasPermission, type Permission, type Role } from "./permissions"

type GuardResult =
  | { userId: string; viaApiKey: boolean; roles: Role[]; error?: undefined }
  | { userId?: undefined; viaApiKey?: undefined; roles?: undefined; error: NextResponse }

// 每个接口在 handler 里自己确认身份和权限，不依赖中间件已经检查过：
// 中间件在某些情况下可能不执行（例如 next-on-pages 给预渲染请求留的跳过条件）。
// 经过中间件的常规请求直接复用当次请求上下文里的鉴权结果，不再重复查库。
//
//   permission  需要的权限，null 表示登录即可
//   apiKey      是否接受 X-API-Key。不接受的接口遇到 X-API-Key 直接拒绝，
//               保证整个 handler 只按一种身份（会话用户）读写数据
//
// 用法：
//   const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
//   if (guard.error) return guard.error
//   const { userId } = guard
export async function requireUser(
  permission: Permission | null,
  { apiKey = false }: { apiKey?: boolean } = {}
): Promise<GuardResult> {
  const hdrs = await headers()
  const hasApiKey = !!hdrs.get("X-API-Key")

  if (hasApiKey && !apiKey) {
    return { error: NextResponse.json({ error: "此接口不支持 API Key" }, { status: 403 }) }
  }

  // 带 X-API-Key 时只认 Key 的主人，否则只认会话用户
  const snap = await resolveRequestAuth(hdrs)
  if (!snap.userId) {
    return {
      error: NextResponse.json(
        { error: hasApiKey ? "无效的 API Key" : "未授权" },
        { status: 401 }
      ),
    }
  }

  if (permission && !hasPermission(snap.roles, permission)) {
    return { error: NextResponse.json({ error: "权限不足" }, { status: 403 }) }
  }

  return { userId: snap.userId, viaApiKey: snap.viaApiKey, roles: snap.roles }
}
