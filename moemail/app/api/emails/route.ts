import { createDb } from "@/lib/db"
import { and, eq, gt, lt, or, sql } from "drizzle-orm"
import { NextResponse } from "next/server"
import { emails } from "@/lib/schema"
import { encodeCursor, decodeCursor } from "@/lib/cursor"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { likeContains, likePattern, parseSearchQuery } from "@/lib/search"

export const runtime = "edge"

const PAGE_SIZE = 20

export async function GET(request: Request) {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error
  const { userId } = guard

  const { searchParams } = new URL(request.url)
  const cursor = searchParams.get('cursor')
  const query = parseSearchQuery(searchParams.get('q'))
  
  const db = createDb()

  try {
    const pattern = query ? likePattern(query) : null
    const baseConditions = and(
      eq(emails.userId, userId),
      gt(emails.expiresAt, new Date()),
      pattern
        ? or(likeContains(emails.address, pattern), likeContains(emails.note, pattern))
        : undefined
    )

    const totalResult = await db.select({ count: sql<number>`count(*)` })
      .from(emails)
      .where(baseConditions)
    const totalCount = Number(totalResult[0].count)

    const conditions = [baseConditions]

    if (cursor) {
      const decoded = decodeCursor(cursor)
      if (!decoded) {
        return NextResponse.json({ error: "Invalid cursor" }, { status: 400 })
      }
      const { timestamp, id } = decoded
      conditions.push(
        or(
          lt(emails.createdAt, new Date(timestamp)),
          and(
            eq(emails.createdAt, new Date(timestamp)),
            lt(emails.id, id)
          )
        )
      )
    }

    const results = await db.query.emails.findMany({
      where: and(...conditions),
      orderBy: (emails, { desc }) => [
        desc(emails.createdAt),
        desc(emails.id)
      ],
      limit: PAGE_SIZE + 1
    })
    
    const hasMore = results.length > PAGE_SIZE
    const nextCursor = hasMore 
      ? encodeCursor(
          results[PAGE_SIZE - 1].createdAt.getTime(),
          results[PAGE_SIZE - 1].id
        )
      : null
    const emailList = hasMore ? results.slice(0, PAGE_SIZE) : results

    return NextResponse.json({ 
      emails: emailList,
      nextCursor,
      total: totalCount
    })
  } catch (error) {
    console.error('Failed to fetch user emails:', error)
    return NextResponse.json(
      { error: "Failed to fetch emails" },
      { status: 500 }
    )
  }
} 