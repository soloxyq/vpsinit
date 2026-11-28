import NextAuth, { CredentialsSignin, type Session } from "next-auth"
import GitHub from "next-auth/providers/github"
import Google from "next-auth/providers/google"
import { DrizzleAdapter } from "@auth/drizzle-adapter"
import { createDb, Db } from "./db"
import { accounts, apiKeys, users, roles, userRoles } from "./schema"
import { and, eq, gt } from "drizzle-orm"
import { getOptionalRequestContext, getRequestContext } from "@cloudflare/next-on-pages"
import { headers } from "next/headers"
import { Permission, hasPermission, ROLES, Role } from "./permissions"
import CredentialsProvider from "next-auth/providers/credentials"
import { hashPassword, comparePassword } from "@/lib/utils"
import { authSchema, AuthSchema } from "@/lib/validation"
import { generateAvatarUrl } from "./avatar"
import { verifyRegisterPassCookie, verifyTurnstileToken } from "./turnstile"
import { PublicError } from "./errors"

// next-on-pages 为每次 HTTP 请求单独创建 AsyncLocalStorage 存储对象，并在中间件与路由处理函数之间共享；
// 把当次请求的鉴权与角色快照挂在上面，同一请求内只查一次 D1，跨请求天然隔离（改密码、删号、降权下一请求立即生效）。
const JWT_SNAPSHOT_SYM = Symbol.for("moemail.jwtSnapshot")
const REQ_SESSION_SYM = Symbol.for("moemail.reqSession")
const REQ_AUTH_SYM = Symbol.for("moemail.reqAuth")

interface JwtUserSnapshot {
  userId: string
  roles: Role[]
  providers: string[]
}

export interface RequestAuthSnapshot {
  userId: string | null
  viaApiKey: boolean
  roles: Role[]
}

function getReqStore(): Record<symbol, unknown> | null {
  try {
    const reqCtx = getOptionalRequestContext()
    if (reqCtx) {
      return reqCtx as unknown as Record<symbol, unknown>
    }
  } catch {
    // 非 edge 请求上下文时不缓存
  }
  return null
}

const ROLE_DESCRIPTIONS: Record<Role, string> = {
  [ROLES.EMPEROR]: "皇帝（网站所有者）",
  [ROLES.DUKE]: "公爵（超级用户）",
  [ROLES.KNIGHT]: "骑士（高级用户）",
  [ROLES.CIVILIAN]: "平民（普通用户）",
}

const getDefaultRole = async (): Promise<Role> => {
  const defaultRole = await getRequestContext().env.SITE_CONFIG.get("DEFAULT_ROLE")

  if (
    defaultRole === ROLES.DUKE ||
    defaultRole === ROLES.KNIGHT ||
    defaultRole === ROLES.CIVILIAN
  ) {
    return defaultRole as Role
  }

  return ROLES.CIVILIAN
}

// 站点设置里可以关闭注册，没设置过时保持开放。
// 只管用户名密码注册：配置了 GitHub/Google 登录后，首次用第三方账号登录仍会建号。
export async function isRegistrationOpen() {
  const value = await getRequestContext().env.SITE_CONFIG.get("ALLOW_REGISTRATION")
  return value !== "false"
}

// 第三方登录只有填了 Client ID 和 Secret 才启用，登录页据此决定显示哪些按钮
export function oauthProviders() {
  return {
    github: !!(process.env.AUTH_GITHUB_ID && process.env.AUTH_GITHUB_SECRET),
    google: !!(process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET),
  }
}

async function findOrCreateRole(db: Db, roleName: Role) {
  let role = await db.query.roles.findFirst({
    where: eq(roles.name, roleName),
  })

  if (!role) {
    const [newRole] = await db.insert(roles)
      .values({
        name: roleName,
        description: ROLE_DESCRIPTIONS[roleName],
      })
      .returning()
    role = newRole
  }

  return role
}

export async function assignRoleToUser(db: Db, userId: string, roleId: string) {
  await db.delete(userRoles)
    .where(eq(userRoles.userId, userId))

  await db.insert(userRoles)
    .values({
      userId,
      roleId,
    })
}

export async function getUserRole(userId: string) {
  const store = getReqStore()
  if (store) {
    const snap = await resolveRequestAuth()
    if (snap.userId === userId && snap.roles[0]) {
      return snap.roles[0]
    }
  }
  const db = createDb()
  const userRoleRecords = await db.query.userRoles.findMany({
    where: eq(userRoles.userId, userId),
    with: { role: true },
  })
  return userRoleRecords[0]?.role.name
}

export async function checkPermission(permission: Permission) {
  const snap = await resolveRequestAuth()
  if (!snap.userId) return false
  return hasPermission(snap.roles, permission)
}

export async function userHasPermission(userId: string, permission: Permission) {
  const store = getReqStore()
  if (store) {
    const snap = await resolveRequestAuth()
    if (snap.userId === userId) {
      return hasPermission(snap.roles, permission)
    }
  }
  const db = createDb()
  const userRoleRecords = await db.query.userRoles.findMany({
    where: eq(userRoles.userId, userId),
    with: { role: true },
  })

  const userRoleNames = userRoleRecords.map(ur => ur.role.name)
  return hasPermission(userRoleNames as Role[], permission)
}

// authorize 里抛普通 Error 会被 @auth/core 包装成 CallbackRouteError，前端只能收到 "Configuration"；
// 继承 CredentialsSignin 后错误码才会作为客户端安全错误传给前端。
class LoginError extends CredentialsSignin {
  code: string
  constructor(code: string) {
    super()
    this.code = code
  }
}

const {
  handlers: { GET, POST },
  auth: rawAuth,
  signIn,
  signOut
} = NextAuth(() => ({
  secret: process.env.AUTH_SECRET,
  adapter: DrizzleAdapter(createDb(), {
    usersTable: users,
    accountsTable: accounts,
  }),
  providers: [
    ...(oauthProviders().github ? [GitHub({
      clientId: process.env.AUTH_GITHUB_ID,
      clientSecret: process.env.AUTH_GITHUB_SECRET,
      allowDangerousEmailAccountLinking: true,
      issuer: "https://github.com/login/oauth",
    })] : []),
    ...(oauthProviders().google ? [Google({
      clientId: process.env.AUTH_GOOGLE_ID,
      clientSecret: process.env.AUTH_GOOGLE_SECRET,
      allowDangerousEmailAccountLinking: true,
    })] : []),
    CredentialsProvider({
      name: "Credentials",
      credentials: {
        username: { label: "用户名", type: "text", placeholder: "请输入用户名" },
        password: { label: "密码", type: "password", placeholder: "请输入密码" },
      },
      async authorize(credentials, request) {
        if (!credentials) {
          throw new LoginError("invalid_input")
        }

        const { username, password, turnstileToken } = credentials as Record<string, string | undefined>

        let parsedCredentials: AuthSchema
        try {
          parsedCredentials = authSchema.parse({ username, password, turnstileToken })
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
        } catch (error) {
          throw new LoginError("invalid_input")
        }

        const regPassed = await verifyRegisterPassCookie(
          request?.headers?.get("cookie"),
          parsedCredentials.username
        )
        if (!regPassed) {
          const verification = await verifyTurnstileToken(parsedCredentials.turnstileToken)
          if (!verification.success) {
            if (verification.reason === "missing-token") {
              throw new LoginError("turnstile_missing")
            }
            throw new LoginError("turnstile_failed")
          }
        }

        const db = createDb()

        const user = await db.query.users.findFirst({
          where: eq(users.username, parsedCredentials.username),
        })

        if (!user) {
          throw new LoginError("invalid_credentials")
        }

        const isValid = await comparePassword(parsedCredentials.password, user.password as string)
        if (!isValid) {
          throw new LoginError("invalid_credentials")
        }

        return {
          ...user,
          password: undefined,
        }
      },
    }),
  ],
  events: {
    async signIn({ user }) {
      if (!user.id) return

      try {
        const db = createDb()
        const existingRole = await db.query.userRoles.findFirst({
          where: eq(userRoles.userId, user.id),
        })

        if (existingRole) return

        const defaultRole = await getDefaultRole()
        const role = await findOrCreateRole(db, defaultRole)
        await assignRoleToUser(db, user.id, role.id)
      } catch (error) {
        console.error('Error assigning role:', error)
      }
    },
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id
        token.name = user.name || user.username
        token.username = user.username
        token.image = user.image || generateAvatarUrl(token.name as string)
      }
      // 登录时在会话里记下密码哈希的前 8 个字符，之后每次和数据库比对，对不上就让会话失效（返回 null 会清掉会话）：
      // 改密码之后，其它设备上已经登录的会话也跟着退出；账号被删后，它的会话也马上失效。
      // 只在登录时记：没记过的会话（这个功能上线前登录的）也算对不上，要重新登录一次。
      // 同时在单次 D1 batch 里一并取出角色与第三方账号，挂到当次请求上下文供 session() 直接复用。
      if (typeof token.id === "string") {
        const db = createDb()
        const [userRows, accountRows] = await db.batch([
          db
            .select({
              password: users.password,
              roleName: roles.name,
            })
            .from(users)
            .leftJoin(userRoles, eq(userRoles.userId, users.id))
            .leftJoin(roles, eq(roles.id, userRoles.roleId))
            .where(eq(users.id, token.id)),
          db
            .select({ provider: accounts.provider })
            .from(accounts)
            .where(eq(accounts.userId, token.id)),
        ])
        if (userRows.length === 0) return null
        const fingerprint = (userRows[0].password ?? "").slice(0, 8)
        if (user) token.pv = fingerprint
        else if (token.pv !== fingerprint) return null

        let roleNames = Array.from(
          new Set(userRows.map((r) => r.roleName).filter((n): n is string => Boolean(n)))
        ) as Role[]

        if (!user && roleNames.length === 0) {
          const defaultRole = await getDefaultRole()
          const role = await findOrCreateRole(db, defaultRole)
          await assignRoleToUser(db, token.id, role.id)
          roleNames = [role.name as Role]
        }

        const store = getReqStore()
        if (store) {
          store[JWT_SNAPSHOT_SYM] = {
            userId: token.id,
            roles: roleNames,
            providers: accountRows.map((a) => a.provider),
          } satisfies JwtUserSnapshot
        }
      }
      return token
    },
    async session({ session, token }) {
      if (token && session.user) {
        session.user.id = token.id as string
        session.user.name = token.name as string
        session.user.username = token.username as string
        session.user.image = token.image as string

        const store = getReqStore()
        const snap = store?.[JWT_SNAPSHOT_SYM] as JwtUserSnapshot | undefined
        if (snap && snap.userId === session.user.id && snap.roles.length > 0) {
          session.user.roles = snap.roles.map((name) => ({ name }))
          session.user.providers = snap.providers
          return session
        }

        const db = createDb()
        let userRoleRecords = await db.query.userRoles.findMany({
          where: eq(userRoles.userId, session.user.id),
          with: { role: true },
        })

        if (!userRoleRecords.length) {
          const defaultRole = await getDefaultRole()
          const role = await findOrCreateRole(db, defaultRole)
          await assignRoleToUser(db, session.user.id, role.id)
          userRoleRecords = [{
            userId: session.user.id,
            roleId: role.id,
            createdAt: new Date(),
            role: role
          }]
        }

        session.user.roles = userRoleRecords.map(ur => ({
          name: ur.role.name,
        }))

        const userAccounts = await db.query.accounts.findMany({
          where: eq(accounts.userId, session.user.id),
        })

        session.user.providers = userAccounts.map(account => account.provider)
      }

      return session
    },
  },
  session: {
    strategy: "jwt",
  },
}))

export { GET, POST, signIn, signOut }

export async function auth(hdrs?: Headers): Promise<Session | null> {
  const resolvedHeaders = hdrs ?? (await headers())
  const cookieHeader = resolvedHeaders.get("cookie") ?? ""
  if (!cookieHeader.includes("session-token")) {
    return null
  }

  const store = getReqStore()
  if (store) {
    const cache =
      (store[REQ_SESSION_SYM] as Map<string, Promise<Session | null>> | undefined) ??
      new Map<string, Promise<Session | null>>()
    store[REQ_SESSION_SYM] = cache
    const existing = cache.get(cookieHeader)
    if (existing) return existing
    const pending = rawAuth()
    cache.set(cookieHeader, pending)
    return pending
  }

  return rawAuth()
}

async function computeRequestAuth(
  apiKey: string | null,
  resolvedHeaders: Headers
): Promise<RequestAuthSnapshot> {
  if (apiKey !== null) {
    const rows = await createDb()
      .select({
        userId: users.id,
        roleName: roles.name,
      })
      .from(apiKeys)
      .innerJoin(users, eq(apiKeys.userId, users.id))
      .leftJoin(userRoles, eq(userRoles.userId, users.id))
      .leftJoin(roles, eq(roles.id, userRoles.roleId))
      .where(
        and(
          eq(apiKeys.key, apiKey),
          eq(apiKeys.enabled, true),
          gt(apiKeys.expiresAt, new Date())
        )
      )

    if (rows.length === 0) {
      return { userId: null, viaApiKey: true, roles: [] }
    }

    const roleNames = Array.from(
      new Set(rows.map((r) => r.roleName).filter((n): n is string => Boolean(n)))
    ) as Role[]

    return {
      userId: rows[0].userId,
      viaApiKey: true,
      roles: roleNames,
    }
  }

  const session = await auth(resolvedHeaders)
  const userId = session?.user?.id ?? null
  if (!userId) {
    return { userId: null, viaApiKey: false, roles: [] }
  }

  const roleNames = (session?.user?.roles?.map((r) => r.name as Role) ?? [])
  return {
    userId,
    viaApiKey: false,
    roles: roleNames,
  }
}

export async function resolveRequestAuth(hdrs?: Headers): Promise<RequestAuthSnapshot> {
  const resolvedHeaders = hdrs ?? (await headers())
  const rawApiKey = resolvedHeaders.get("X-API-Key")
  const apiKey = rawApiKey ? rawApiKey : null
  const cacheKey = apiKey !== null ? `k:${apiKey}` : `c:${resolvedHeaders.get("cookie") ?? ""}`

  const store = getReqStore()
  if (store) {
    const cache =
      (store[REQ_AUTH_SYM] as Map<string, Promise<RequestAuthSnapshot>> | undefined) ??
      new Map<string, Promise<RequestAuthSnapshot>>()
    store[REQ_AUTH_SYM] = cache
    const existing = cache.get(cacheKey)
    if (existing) return existing
    const pending = computeRequestAuth(apiKey, resolvedHeaders)
    cache.set(cacheKey, pending)
    return pending
  }

  return computeRequestAuth(apiKey, resolvedHeaders)
}

export async function register(username: string, password: string) {
  const db = createDb()

  const existing = await db.query.users.findFirst({
    where: eq(users.username, username)
  })

  if (existing) {
    throw new PublicError("用户名已存在")
  }

  const hashedPassword = await hashPassword(password)

  const [user] = await db.insert(users)
    .values({
      username,
      password: hashedPassword,
    })
    .returning()

  return user
}
