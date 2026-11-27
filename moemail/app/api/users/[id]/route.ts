import { createDb } from "@/lib/db";
import { users, userRoles, apiKeys, emails, messages } from "@/lib/schema";
import { eq, inArray } from "drizzle-orm";
import { getRequestContext } from "@cloudflare/next-on-pages";
import { attachmentKeysOf, deleteAttachmentKeys } from "@/lib/attachments";
import { ROLES, PERMISSIONS } from "@/lib/permissions";
import { requireUser } from "@/lib/guard";

export const runtime = "edge";

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const guard = await requireUser(PERMISSIONS.PROMOTE_USER);
  if (guard.error) return guard.error;

  try {
    const { id: userId } = await params;
    if (!userId) {
      return Response.json({ error: "缺少必要参数" }, { status: 400 });
    }

    if (userId === guard.userId) {
      return Response.json({ error: "不能删除自己" }, { status: 400 });
    }

    const db = createDb();

    const targetUserRole = await db.query.userRoles.findFirst({
      where: eq(userRoles.userId, userId),
      with: {
        role: true,
      },
    });

    if (targetUserRole?.role.name === ROLES.EMPEROR) {
      return Response.json({ error: "不能删除皇帝" }, { status: 400 });
    }

    // 同一个事务里删：先删这个用户所有邮箱里的邮件并拿回删掉的行（要据此删 KV 里的附件），
    // 再删 apiKeys（未配置级联删除）和用户本身（accounts / emails / webhooks / userRoles 由外键级联处理）
    const [deleted] = await db.batch([
      db.delete(messages)
        .where(inArray(messages.emailId, db.select({ id: emails.id }).from(emails).where(eq(emails.userId, userId))))
        .returning({ id: messages.id, attachments: messages.attachments }),
      db.delete(apiKeys).where(eq(apiKeys.userId, userId)),
      db.delete(users).where(eq(users.id, userId)),
    ]);

    // KV 里的附件在返回响应之后接着删
    const { env, ctx } = getRequestContext();
    ctx.waitUntil(deleteAttachmentKeys(env.ATTACHMENTS, attachmentKeysOf(deleted)));

    return Response.json({ success: true });
  } catch (error) {
    console.error("Failed to delete user:", error);
    return Response.json({ error: "操作失败" }, { status: 500 });
  }
}
