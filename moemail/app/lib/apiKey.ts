import { resolveRequestAuth } from "./auth"

// 当前请求是谁发的：带 X-API-Key 就以这把 Key 的主人为准，否则看登录会话。
// 身份只能来自这两种服务端验证得了的凭据，不要读取任何由客户端自报身份的请求头。
export const getUserId = async () => {
  const snap = await resolveRequestAuth()
  return snap.userId ?? undefined
}
