"use client"

import { Paperclip } from "lucide-react"
import { useTranslations } from "next-intl"
import { formatSize, isRenderedInline, type AttachmentInfo } from "@/lib/attachments"

interface AttachmentListProps {
  attachments?: AttachmentInfo[]
  // 下载地址前缀，后面接附件序号
  baseUrl?: string
}

// 邮件头下方的附件栏。正文里用 cid: 引用的内嵌图片在正文中显示，不列在这里
export function AttachmentList({ attachments, baseUrl }: AttachmentListProps) {
  const t = useTranslations("emails.messageView")
  const listed = (attachments ?? []).filter((a) => !isRenderedInline(a))
  if (listed.length === 0) return null

  const chip =
    "inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-md border border-border/80 bg-card px-2 py-1 text-xs"

  return (
    <div className="flex flex-wrap gap-1.5" aria-label={t("attachments")}>
      {listed.map((a) =>
        a.stored && baseUrl ? (
          <a
            key={a.index}
            href={`${baseUrl}/${a.index}`}
            download={a.filename}
            title={a.filename}
            className={`${chip} text-foreground/85 transition-colors hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40`}
          >
            <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate">{a.filename}</span>
            <span className="shrink-0 tabular-nums text-muted-foreground">{formatSize(a.size)}</span>
          </a>
        ) : (
          <span
            key={a.index}
            title={t("attachmentNotSavedHint")}
            className={`${chip} text-muted-foreground`}
          >
            <Paperclip className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{a.filename}</span>
            <span className="shrink-0">{t("attachmentNotSaved")}</span>
          </span>
        )
      )}
    </div>
  )
}
