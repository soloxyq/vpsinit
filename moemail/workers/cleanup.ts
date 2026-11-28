import { ATTACHMENT_KEY_PREFIX, sweepOrphanAttachments, utcDay } from '../app/lib/attachments'

interface Env {
  DB: D1Database
  ATTACHMENTS?: KVNamespace
}

const CLEANUP_CONFIG = {
  // Whether to delete expired emails
  DELETE_EXPIRED_EMAILS: true,

  // Batch processing size
  BATCH_SIZE: 100,
} as const

const main = {
  async scheduled(_: ScheduledEvent, env: Env) {
    const now = Date.now()
    // 两件事互不依赖：一件出错，另一件照做，最后再把错误抛出去
    let failure: unknown = null

    if (!CLEANUP_CONFIG.DELETE_EXPIRED_EMAILS) {
      console.log('Expired email deletion is disabled')
    } else {
      try {
        // 不用 DELETE … LIMIT（要 SQLite 打开特定编译选项才支持），改成子查询
        const result = await env.DB
          .prepare(`
            DELETE FROM email
            WHERE id IN (SELECT id FROM email WHERE expires_at < ? LIMIT ?)
          `)
          .bind(now, CLEANUP_CONFIG.BATCH_SIZE)
          .run()
        console.log(`Deleted ${result?.meta?.changes ?? 0} expired emails and their associated messages`)
      } catch (error) {
        console.error('Failed to delete expired emails:', error)
        failure = error
      }
    }

    // 附件扫描：每小时扫一片（按邮件 ID 的首个十六进制字符分 16 片），16 小时扫完一轮，见 app/lib/attachments.ts
    if (env.ATTACHMENTS) {
      const shard = (new Date(now).getUTCHours() % 16).toString(16)
      try {
        const deleted = await sweepOrphanAttachments(env.DB, env.ATTACHMENTS, {
          prefix: `${ATTACHMENT_KEY_PREFIX}${shard}`
        })
        if (deleted > 0) console.log(`Deleted ${deleted} orphaned attachments (shard ${shard})`)
      } catch (error) {
        console.error('Failed to sweep attachments:', error)
        failure ??= error
      }
    }

    // 清理两天以前的每日计数（如附件写入次数、每日发件数）
    try {
      const yesterday = utcDay(now - 86_400_000)
      await env.DB.prepare('DELETE FROM daily_usage WHERE day < ?').bind(yesterday).run()
    } catch (error) {
      console.error('Failed to clean up daily_usage:', error)
      failure ??= error
    }

    if (failure) throw failure
  }
}

export default main
