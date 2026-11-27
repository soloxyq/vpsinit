export const EMAIL_CONFIG = {
  MAX_ACTIVE_EMAILS: 30, // Maximum number of active emails
  POLL_INTERVAL: 10_000, // Polling interval in milliseconds
  UNREAD_POLL_INTERVAL: 30_000, // 各邮箱未读数的刷新间隔
  UNREAD_COUNT_CAP: 10, // 每个邮箱的未读数最多数到这么多，角标上显示成“9+”
  DEFAULT_DAILY_SEND_LIMITS: {
    emperor: 0,   // 皇帝无限制
    duke: 5,      // 公爵每日5封
    knight: 2,    // 骑士每日2封
    civilian: -1, // 平民禁止发件
  },
} as const

export type EmailConfig = typeof EMAIL_CONFIG 