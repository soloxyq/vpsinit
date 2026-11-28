import { createDb } from "@/lib/db"
import { userRoles, roles, messages, emails, dailyUsage } from "@/lib/schema"
import { eq, and, gte, sql } from "drizzle-orm"
import { getRequestContext } from "@cloudflare/next-on-pages"
import { EMAIL_CONFIG } from "@/config"
import { utcDay } from "@/lib/attachments"

export interface SendPermissionResult {
  canSend: boolean
  error?: string
  remainingEmails?: number
}

export type SendLimitCheckResult =
  | { canSend: true; dailyLimit: number }
  | { canSend: false; error: string }

// 检查发件服务是否开启及用户的角色每日上限（0 表示不限额，>0 表示每日上限封数）
export async function getSendPermissionAndLimit(userId: string): Promise<SendLimitCheckResult> {
  const env = getRequestContext().env
  const enabled = await env.SITE_CONFIG.get("EMAIL_SERVICE_ENABLED")

  if (enabled !== "true") {
    return {
      canSend: false,
      error: "邮件发送服务未启用",
    }
  }

  const dailyLimit = await getUserDailyLimit(userId)
  if (dailyLimit === -1) {
    return {
      canSend: false,
      error: "您的角色没有发件权限",
    }
  }

  return {
    canSend: true,
    dailyLimit,
  }
}

// 在调用外部发信服务前，用单条 SQLite 条件 UPSERT 原子预占当天 1 封额度：
// - 尚无当日计数行时，以 message 表里当天已发封数 s.cnt 为基数（兼容旧数据），仅当 s.cnt < dailyLimit 时插入 s.cnt + 1；
// - 已有当日计数行时，仅当 MAX(daily_usage.count, s.cnt) < dailyLimit 时原子 + 1。
// 并发请求在同一条写语句下串行竞争，超额请求 0 行更新、RETURNING 为空，不会放行去调用 Resend。
export async function reserveDailySendQuota(
  d1: D1Database,
  userId: string,
  dailyLimit: number,
  nowMs = Date.now()
): Promise<{ reserved: true; day: string; remainingEmails?: number } | { reserved: false }> {
  const day = utcDay(nowMs)
  const scope = `sent:${userId}`

  if (dailyLimit === 0) {
    await d1
      .prepare(
        `INSERT INTO daily_usage (day, scope, count) VALUES (?1, ?2, 1)
         ON CONFLICT(day, scope) DO UPDATE SET count = daily_usage.count + 1`
      )
      .bind(day, scope)
      .run()
    return { reserved: true, day, remainingEmails: undefined }
  }

  const startOfDay = new Date(nowMs)
  startOfDay.setUTCHours(0, 0, 0, 0)
  const row = await d1
    .prepare(
      `INSERT INTO daily_usage (day, scope, count)
       SELECT ?1, ?2, s.cnt + 1
       FROM (
         SELECT COUNT(*) AS cnt
         FROM message m
         JOIN email e ON m.emailId = e.id
         WHERE e.userId = ?3 AND m.type = 'sent' AND m.received_at >= ?4
       ) AS s
       WHERE s.cnt < ?5
       ON CONFLICT(day, scope) DO UPDATE
         SET count = MAX(daily_usage.count, excluded.count - 1) + 1
         WHERE MAX(daily_usage.count, excluded.count - 1) < ?5
       RETURNING count`
    )
    .bind(day, scope, userId, startOfDay.getTime(), dailyLimit)
    .first<{ count: number }>()

  if (!row) {
    return { reserved: false }
  }
  return {
    reserved: true,
    day,
    remainingEmails: Math.max(0, dailyLimit - row.count),
  }
}

// 仅在发信服务商明确拒收（HTTP 4xx）时退回刚预占的 1 封额度；按预占时的日期退回，跨 UTC 零点也不错位
export async function refundDailySendQuota(
  d1: D1Database,
  userId: string,
  day: string
): Promise<void> {
  await d1
    .prepare(
      `UPDATE daily_usage
       SET count = CASE WHEN count > 0 THEN count - 1 ELSE 0 END
       WHERE day = ?1 AND scope = ?2`
    )
    .bind(day, `sent:${userId}`)
    .run()
}

export async function checkSendPermission(
  userId: string,
  skipDailyLimitCheck = false
): Promise<SendPermissionResult> {
  try {
    const base = await getSendPermissionAndLimit(userId)
    if (!base.canSend) {
      return base
    }

    const userDailyLimit = base.dailyLimit
    if (skipDailyLimitCheck || userDailyLimit === 0) {
      return {
        canSend: true
      }
    }
    
    const db = createDb()
    const now = Date.now()
    const today = new Date(now)
    today.setUTCHours(0, 0, 0, 0)
    const [usageRows, sentRows] = await db.batch([
      db
        .select({ count: dailyUsage.count })
        .from(dailyUsage)
        .where(and(eq(dailyUsage.day, utcDay(now)), eq(dailyUsage.scope, `sent:${userId}`))),
      db
        .select({ count: sql<number>`count(*)` })
        .from(messages)
        .innerJoin(emails, eq(messages.emailId, emails.id))
        .where(
          and(
            eq(emails.userId, userId),
            eq(messages.type, "sent"),
            gte(messages.receivedAt, today)
          )
        ),
    ])

    const usedToday = Math.max(usageRows[0]?.count ?? 0, Number(sentRows[0]?.count ?? 0))
    const remainingEmails = Math.max(0, userDailyLimit - usedToday)
    
    if (usedToday >= userDailyLimit) {
      return {
        canSend: false,
        error: `您今天已达到发件限制 (${userDailyLimit} 封)，请明天再试`,
        remainingEmails: 0
      }
    }

    return {
      canSend: true,
      remainingEmails
    }
  } catch (error) {
    console.error('Failed to check send permission:', error)
    return {
      canSend: false,
      error: "权限检查失败"
    }
  }
}

async function getUserDailyLimit(userId: string): Promise<number> {
  const db = createDb()

  const userRoleData = await db
    .select({ roleName: roles.name })
    .from(userRoles)
    .innerJoin(roles, eq(userRoles.roleId, roles.id))
    .where(eq(userRoles.userId, userId))

  const userRoleNames = userRoleData.map(r => r.roleName)

  const env = getRequestContext().env
  const roleLimitsStr = await env.SITE_CONFIG.get("EMAIL_ROLE_LIMITS")

  let customLimits: { duke?: number; knight?: number } = {}
  if (roleLimitsStr) {
    try {
      customLimits = JSON.parse(roleLimitsStr) as { duke?: number; knight?: number }
    } catch {
      customLimits = {}
    }
  }

  const finalLimits = {
    emperor: EMAIL_CONFIG.DEFAULT_DAILY_SEND_LIMITS.emperor,
    duke: customLimits.duke !== undefined ? customLimits.duke : EMAIL_CONFIG.DEFAULT_DAILY_SEND_LIMITS.duke,
    knight: customLimits.knight !== undefined ? customLimits.knight : EMAIL_CONFIG.DEFAULT_DAILY_SEND_LIMITS.knight,
    civilian: EMAIL_CONFIG.DEFAULT_DAILY_SEND_LIMITS.civilian,
  }

  if (userRoleNames.includes("emperor")) {
    return finalLimits.emperor
  } else if (userRoleNames.includes("duke")) {
    return finalLimits.duke
  } else if (userRoleNames.includes("knight")) {
    return finalLimits.knight
  } else if (userRoleNames.includes("civilian")) {
    return finalLimits.civilian
  }

  return -1
}

export async function checkBasicSendPermission(userId: string): Promise<SendPermissionResult> {
  return checkSendPermission(userId, true)
} 