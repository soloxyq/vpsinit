import { createDb } from "@/lib/db"
import { users, userRoles, roles } from "@/lib/schema"
import { eq, or, sql } from "drizzle-orm"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS, ROLES } from "@/lib/permissions"
import { likeContains, likePattern, parseSearchQuery } from "@/lib/search"

export const runtime = "edge"

export async function GET(request: Request) {
  const guard = await requireUser(PERMISSIONS.PROMOTE_USER)
  if (guard.error) return guard.error

  const { searchParams } = new URL(request.url)
  const rawPage = Number(searchParams.get("page") || "1")
  const rawPageSize = Number(searchParams.get("pageSize") || "20")
  if (!Number.isFinite(rawPage) || !Number.isFinite(rawPageSize)) {
    return Response.json({ error: "分页参数不正确" }, { status: 400 })
  }
  const page = Math.max(1, Math.floor(rawPage))
  const pageSize = Math.min(50, Math.max(1, Math.floor(rawPageSize)))
  const search = parseSearchQuery(searchParams.get("search"))

  const db = createDb()

  try {
    const pattern = search ? likePattern(search) : null
    const searchCondition = pattern
      ? or(
          likeContains(users.username, pattern),
          likeContains(users.email, pattern),
          likeContains(users.name, pattern)
        )
      : undefined

    const totalResult = await db
      .select({ count: sql<number>`count(*)` })
      .from(users)
      .where(searchCondition)
    const total = Number(totalResult[0].count)

    const roleRank = sql`CASE COALESCE(${roles.name}, ${ROLES.CIVILIAN})
      WHEN ${ROLES.EMPEROR} THEN 0
      WHEN ${ROLES.DUKE} THEN 1
      WHEN ${ROLES.KNIGHT} THEN 2
      WHEN ${ROLES.CIVILIAN} THEN 3
      ELSE 4
    END`

    const userList = await db
      .select({
        id: users.id,
        name: users.name,
        username: users.username,
        email: users.email,
        image: users.image,
        role: roles.name,
      })
      .from(users)
      .leftJoin(userRoles, eq(userRoles.userId, users.id))
      .leftJoin(roles, eq(roles.id, userRoles.roleId))
      .where(searchCondition)
      .orderBy(roleRank, sql`LENGTH(COALESCE(${users.username}, ${users.name}))`, sql`LOWER(COALESCE(${users.username}, ${users.name}))`)
      .limit(pageSize)
      .offset((page - 1) * pageSize)

    return Response.json({
      users: userList.map((u) => ({
        id: u.id,
        name: u.name,
        username: u.username,
        email: u.email,
        image: u.image,
        role: u.role || null,
      })),
      total,
      page,
      pageSize,
    })
  } catch (error) {
    console.error("Failed to list users:", error)
    return Response.json({ error: "获取用户列表失败" }, { status: 500 })
  }
}

export async function POST(request: Request) {
  const guard = await requireUser(PERMISSIONS.PROMOTE_USER)
  if (guard.error) return guard.error

  try {
    const rawJson: unknown = await request.json().catch(() => null)
    if (!rawJson || typeof rawJson !== "object" || Array.isArray(rawJson)) {
      return Response.json({ error: "无效的请求体" }, { status: 400 })
    }
    const { searchText } = rawJson as { searchText?: unknown }

    if (typeof searchText !== "string" || !searchText.trim()) {
      return Response.json({ error: "请提供用户名或邮箱地址" }, { status: 400 })
    }

    const db = createDb()

    const user = await db.query.users.findFirst({
      where: searchText.includes('@') ? eq(users.email, searchText) : eq(users.username, searchText),
      with: {
        userRoles: {
          with: {
            role: true
          }
        }
      }
    });

    if (!user) {
      return Response.json({ error: "未找到用户" }, { status: 404 })
    }

    return Response.json({
      user: {
        id: user.id,
        name: user.name,
        username: user.username,
        email: user.email,
        role: user.userRoles[0]?.role.name
      }
    })
  } catch (error) {
    console.error("Failed to find user:", error)
    return Response.json(
      { error: "查询用户失败" },
      { status: 500 }
    )
  }
}
