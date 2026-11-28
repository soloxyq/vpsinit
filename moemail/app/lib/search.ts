import { sql, type SQL } from "drizzle-orm"
import type { AnySQLiteColumn } from "drizzle-orm/sqlite-core"
import { EMAIL_CONFIG } from "@/config/email"

// 规范化邮箱备注：去首尾空白，空串存为 null；非字符串或超过最大码点数则拒收并给出对应提示
export function normalizeNote(
  value: unknown
): { ok: true; value: string | null } | { ok: false; error: string } {
  if (value === undefined || value === null) return { ok: true, value: null }
  if (typeof value !== "string") {
    return { ok: false, error: "备注必须是字符串或 null" }
  }
  const trimmed = value.trim()
  if (!trimmed) return { ok: true, value: null }
  if (Array.from(trimmed).length > EMAIL_CONFIG.MAX_NOTE_LENGTH) {
    return { ok: false, error: `备注不能超过 ${EMAIL_CONFIG.MAX_NOTE_LENGTH} 个字符` }
  }
  return { ok: true, value: trimmed }
}

// 规范化搜索词：去首尾空白，超长按码点截断，空串返回 null
export function parseSearchQuery(raw: string | null): string | null {
  if (!raw) return null
  const trimmed = raw.trim()
  if (!trimmed) return null
  return Array.from(trimmed).slice(0, EMAIL_CONFIG.MAX_SEARCH_LENGTH).join("")
}

// 转义 SQLite LIKE 通配符（%、_、\），需配合 ESCAPE '\' 使用
export function likePattern(query: string): string {
  return `%${query.replace(/[\\%_]/g, "\\$&")}%`
}

// SQLite 默认没有 LIKE 转义符，必须显式带 ESCAPE '\' 才能按字面量匹配 %、_、\
export function likeContains(column: AnySQLiteColumn, pattern: string): SQL {
  return sql`${column} LIKE ${pattern} ESCAPE '\\'`
}
