"use client"

import { useState } from "react"
import { useTranslations } from "next-intl"
import { Check, Copy } from "lucide-react"

// 阅读页头部的验证码：点一下复制，图标变成对勾
export function VerificationCode({ code }: { code: string }) {
  const t = useTranslations("emails.messageView")
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // 浏览器不让写剪贴板时什么也不做，验证码就在按钮上，可以手动选中
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      title={t("copyCode")}
      className="inline-flex max-w-full items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-2.5 py-1 text-left transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
    >
      <span className="shrink-0 text-xs text-muted-foreground">{t("verificationCode")}</span>
      <span className="truncate font-mono text-sm font-semibold tracking-wider text-foreground select-all">{code}</span>
      {copied ? (
        <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
      ) : (
        <Copy className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      )}
    </button>
  )
}
