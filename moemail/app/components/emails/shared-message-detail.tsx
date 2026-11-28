"use client"

import { useState, useEffect, useMemo } from "react"
import { Loader2, Mail } from "lucide-react"
import { EmptyState } from "@/components/ui/empty-state"
import { Segmented, SegmentedItem } from "@/components/ui/segmented"
import { useMounted } from "@/hooks/use-mounted"
import { AttachmentList } from "./attachment-list"
import type { AttachmentInfo } from "@/lib/attachments"
import { EmailHtmlFrame } from "./email-html-frame"
import { VerificationCode } from "./verification-code"
import { findVerificationCode } from "@/lib/verification-code"

interface MessageDetail {
  id: string
  from_address?: string
  to_address?: string
  subject: string
  content?: string
  html?: string
  received_at?: number
  sent_at?: number
  attachments?: AttachmentInfo[]
}

interface SharedMessageDetailProps {
  message: MessageDetail | null
  loading?: boolean
  // 附件下载地址前缀（凭分享链接访问的接口），后面接附件序号
  attachmentBaseUrl?: string
  t: {
    messageContent: string
    selectMessage: string
    loading: string
    from: string
    to: string
    subject: string
    time: string
    htmlFormat: string
    textFormat: string
  }
}

type ViewMode = "html" | "text"

export function SharedMessageDetail({
  message,
  loading = false,
  attachmentBaseUrl,
  t,
}: SharedMessageDetailProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("html")
  const mounted = useMounted()

  // 切换邮件时才重置视图模式（依赖 id 与是否有 html/content，而非每次轮询都会重建的对象引用）
  const messageId = message?.id
  const hasHtml = Boolean(message?.html)
  const hasContent = Boolean(message?.content)
  useEffect(() => {
    if (!messageId) return
    setViewMode(!hasHtml && hasContent ? "text" : "html")
  }, [messageId, hasHtml, hasContent])

  // 挂载后再识别：单封分享页在服务端渲染，那里没有 DOMParser，结果会和浏览器里不一致。
  // 依赖字符串而不是 message 对象：父组件每次渲染都传一个新对象
  const subject = message?.subject
  const content = message?.content
  const html = message?.html
  const verificationCode = useMemo(
    () => (mounted && subject !== undefined ? findVerificationCode(subject, content, html) : null),
    [mounted, subject, content, html]
  )

  if (loading) {
    return (
      <div className="flex h-full min-h-[10rem] flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <span>{t.loading}</span>
      </div>
    )
  }

  if (!message) {
    return <EmptyState icon={Mail} title={t.selectMessage} />
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-5 py-4 space-y-2.5 border-b border-border/70 bg-muted/20">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-base font-semibold tracking-tight text-foreground flex-1">{message.subject}</h3>
        </div>
        <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
          {message.from_address && (
            <>
              <span className="text-muted-foreground">{t.from}:</span>
              <span className="truncate font-mono text-foreground/85">{message.from_address}</span>
            </>
          )}
          {message.to_address && (
            <>
              <span className="text-muted-foreground">{t.to}:</span>
              <span className="truncate font-mono text-foreground/85">{message.to_address}</span>
            </>
          )}
          <span className="text-muted-foreground">{t.time}:</span>
          <span className="truncate tabular-nums text-foreground/85">
            {mounted
              ? new Date(message.sent_at || message.received_at || 0).toLocaleString()
              : "\u00a0"}
          </span>
        </div>
        {verificationCode && <VerificationCode code={verificationCode} />}
        <AttachmentList attachments={message.attachments} baseUrl={attachmentBaseUrl} />
      </div>

      {message.html && message.content && (
        <div className="border-b border-border/70 px-5 py-2 bg-muted/10 flex justify-end">
          <Segmented
            value={viewMode}
            onValueChange={(value) => setViewMode(value as ViewMode)}
          >
            <SegmentedItem value="html">{t.htmlFormat}</SegmentedItem>
            <SegmentedItem value="text">{t.textFormat}</SegmentedItem>
          </Segmented>
        </div>
      )}

      <div className="flex-1 overflow-auto relative">
        {viewMode === "html" && message.html ? (
          <EmailHtmlFrame
            key={message.id}
            html={message.html}
            attachments={message.attachments}
            attachmentBaseUrl={attachmentBaseUrl}
          />
        ) : message.content ? (
          <div className="p-5 text-sm leading-relaxed whitespace-pre-wrap text-foreground">
            {message.content}
          </div>
        ) : (
          <EmptyState icon={Mail} title={t.selectMessage} />
        )}
      </div>
    </div>
  )
}
