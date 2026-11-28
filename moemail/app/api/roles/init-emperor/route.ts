import { requireUser } from "@/lib/guard";
import { createDb } from "@/lib/db";
import { roles, userRoles } from "@/lib/schema";
import { ROLES } from "@/lib/permissions";
import { eq } from "drizzle-orm";
import { getRequestContext } from "@cloudflare/next-on-pages";

export const runtime = "edge";

export async function GET() {
  const guard = await requireUser(null);
  if (guard.error) return guard.error;
  const { userId } = guard;

  const db = createDb();
  const d1 = getRequestContext().env.DB;

  try {
    let emperorRole = await db.query.roles.findFirst({
      where: eq(roles.name, ROLES.EMPEROR),
    });

    if (!emperorRole) {
      const nowSec = Math.floor(Date.now() / 1000);
      await d1
        .prepare(
          `INSERT INTO role (id, name, description, created_at, updated_at)
           SELECT ?1, ?2, ?3, ?4, ?4
           WHERE NOT EXISTS (SELECT 1 FROM role WHERE name = ?2)`
        )
        .bind(crypto.randomUUID(), ROLES.EMPEROR, "皇帝（网站所有者）", nowSec)
        .run();
      emperorRole = await db.query.roles.findFirst({
        where: eq(roles.name, ROLES.EMPEROR),
      });
    }

    if (!emperorRole) {
      throw new Error("Emperor role missing");
    }

    // 原子条件写入：只有全站尚无任何皇帝时才插入，避免并发请求同时封出两个皇帝
    const nowSec = Math.floor(Date.now() / 1000);
    const inserted = await d1
      .prepare(
        `INSERT INTO user_role (user_id, role_id, created_at)
         SELECT ?1, ?2, ?3
         WHERE NOT EXISTS (
           SELECT 1 FROM user_role ur JOIN role r ON r.id = ur.role_id WHERE r.name = ?4
         )`
      )
      .bind(userId, emperorRole.id, nowSec, ROLES.EMPEROR)
      .run();

    if ((inserted.meta?.changes ?? 0) === 0) {
      const currentUserRole = await db.query.userRoles.findFirst({
        where: eq(userRoles.userId, userId),
        with: { role: true },
      });
      if (currentUserRole?.role.name === ROLES.EMPEROR) {
        return Response.json({ message: "你已经是皇帝了" });
      }
      return Response.json({ error: "已存在皇帝, 谋反将被处死" }, { status: 400 });
    }

    await d1
      .prepare("DELETE FROM user_role WHERE user_id = ?1 AND role_id != ?2")
      .bind(userId, emperorRole.id)
      .run();

    return Response.json({ message: "登基成功，你已成为皇帝" });
  } catch (error) {
    console.error("Failed to initialize emperor:", error);
    return Response.json(
      { error: "登基称帝失败" },
      { status: 500 }
    );
  }
}