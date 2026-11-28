/// <reference types="@cloudflare/workers-types" />


declare global {
  interface CloudflareEnv {
    DB: D1Database;
    SITE_CONFIG: KVNamespace;
    // 收到的附件，见 app/lib/attachments.ts。没绑定时附件只记信息、不保存
    ATTACHMENTS?: KVNamespace;
    // 收信 Worker：没在 MoeMail 里建过的地址，来信原样转发到这里（须是 Email Routing 里验证过的地址）
    FORWARD_TO?: string;
    // 仅本机回归测试绑定：指向本机模拟 Resend 服务；线上不设，固定走 https://api.resend.com/emails
    RESEND_API_URL?: string;
  }

  interface Window {
    turnstile?: {
      render: (element: HTMLElement | string, options: Record<string, unknown>) => string
      reset: (widgetId?: string) => void
      remove: (widgetId: string) => void
    }
  }

  type Env = CloudflareEnv
}

declare module "next-auth" {
  interface User {
    roles?: { name: string }[]
    username?: string | null
    providers?: string[]
  }

  interface Session {
    user: User
  }
}

export type { Env }
