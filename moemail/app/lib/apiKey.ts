import { createDb } from "./db"
import { apiKeys } from "./schema"
import { eq, and, gt } from "drizzle-orm"
import type { User } from "next-auth"
import { auth } from "./auth"
import { headers } from "next/headers"

async function getUserByApiKey(key: string): Promise<User | null> {
  const db = createDb()
  const apiKey = await db.query.apiKeys.findFirst({
    where: and(
      eq(apiKeys.key, key),
      eq(apiKeys.enabled, true),
      gt(apiKeys.expiresAt, new Date())
    ),
    with: {
      user: true
    }
  })

  if (!apiKey) return null

  return apiKey.user
}

// 当前请求是谁发的：带 X-API-Key 就以这把 Key 的主人为准，否则看登录会话。
// 身份只能来自这两种服务端验证得了的凭据，不要读取任何由客户端自报身份的请求头。
export const getUserId = async () => {
  const headersList = await headers()
  const apiKey = headersList.get("X-API-Key")

  if (apiKey) {
    const user = await getUserByApiKey(apiKey)
    return user?.id
  }

  const session = await auth()

  return session?.user?.id
}
