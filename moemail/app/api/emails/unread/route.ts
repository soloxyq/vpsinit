import { NextResponse } from "next/server"
import { sql } from "drizzle-orm"
import { createDb } from "@/lib/db"
import { emails, messages } from "@/lib/schema"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { EMAIL_CONFIG } from "@/config"

export const runtime = "edge"

// 当前用户各邮箱的未读邮件数：{ counts: { 邮箱 ID: 数量 } }，没有未读的邮箱不在里面。
// 网页端每 30 秒问一次，所以读到的行数要有上限：
// - 每个邮箱最多数到 UNREAD_COUNT_CAP 封就停（LIMIT），返回的数字等于上限时意思是“这么多或更多”。
//   永久邮箱里没人点开的邮件会一直是未读，不设上限的话，未读攒到几千封以后，
//   一个开着的标签页一天就能读超 D1 的免费额度。
// - 子查询只走索引 message_email_id_read_at_idx，不读邮件本身，所以不按 type 排除发出的邮件：
//   发信接口写入时就带着 read_at。只有这个功能上线前的旧版本发出的邮件会被数进来，打开一次就消掉。
// 一次查询读到的行数不超过“邮箱数 ×（2 + 上限）”，和邮件总数无关。
// 整句手写：用查询构造器的话，drizzle 会把单表查询 select 字段里的列名前缀去掉，
// 子查询里的 "id" 就成了 message 自己的 id
export async function GET() {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error

  try {
    const rows = await createDb().all<{ emailId: string; count: number }>(sql`
      SELECT ${emails.id} AS emailId, (
        SELECT count(*) FROM (
          SELECT 1 FROM ${messages}
          WHERE ${messages.emailId} = ${emails.id} AND ${messages.readAt} IS NULL
          LIMIT ${EMAIL_CONFIG.UNREAD_COUNT_CAP}
        )
      ) AS count
      FROM ${emails}
      WHERE ${emails.userId} = ${guard.userId}
    `)

    return NextResponse.json({
      counts: Object.fromEntries(rows.filter((row) => row.count > 0).map((row) => [row.emailId, row.count])),
    })
  } catch (error) {
    console.error("Failed to count unread messages:", error)
    return NextResponse.json({ error: "Failed to count unread messages" }, { status: 500 })
  }
}
