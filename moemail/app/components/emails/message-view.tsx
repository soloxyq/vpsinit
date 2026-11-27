"use client"

import { useState, useEffect, useMemo } from "react"
import { useTranslations } from "next-intl"
import { Loader2, Share2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Segmented, SegmentedItem } from "@/components/ui/segmented"
import { useToast } from "@/components/ui/use-toast"
import { ShareMessageDialog } from "./share-message-dialog"
import { AttachmentList } from "./attachment-list"
import type { AttachmentInfo } from "@/lib/attachments"
import { EmailHtmlFrame } from "./email-html-frame"
import { VerificationCode } from "./verification-code"
import { findVerificationCode } from "@/lib/verification-code"

interface Message {
  id: string
  from_address?: string
  to_address?: string
  subject: string
  content: string
  html?: string
  received_at?: number
  sent_at?: number
  attachments?: AttachmentInfo[]
}

interface MessageViewProps {
  emailId: string
  messageId: string
  messageType?: 'received' | 'sent'
  onClose: () => void
}

type ViewMode = "html" | "text"

export function MessageView({ emailId, messageId, messageType = 'received' }: MessageViewProps) {
  const t = useTranslations("emails.messageView")
  const tList = useTranslations("emails.list")
  const [message, setMessage] = useState<Message | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>("html")
  const { toast } = useToast()
  const attachmentBaseUrl = `/api/emails/${emailId}/${messageId}/attachments`

  useEffect(() => {
    const fetchMessage = async () => {
      try {
        setLoading(true)
        setError(null)
        
        const url = `/api/emails/${emailId}/${messageId}${messageType === 'sent' ? '?type=sent' : ''}`;
        
        const response = await fetch(url)
        
        if (!response.ok) {
          const errorData = await response.json()
          const errorMessage = (errorData as { error?: string }).error || t("loadError")
          setError(errorMessage)
          toast({
            title: tList("error"),
            description: errorMessage,
            variant: "destructive"
          })
          return
        }
        
        const data = await response.json() as { message: Message }
        setMessage(data.message)
        if (!data.message.html) {
          setViewMode("text")
        }
      } catch (error) {
        const errorMessage = t("networkError")
        setError(errorMessage)
        toast({
          title: tList("error"), 
          description: errorMessage,
          variant: "destructive"
        })
        console.error("Failed to fetch message:", error)
      } finally {
        setLoading(false)
      }
    }

    fetchMessage()
  }, [emailId, messageId, messageType, toast, t, tList])

  const verificationCode = useMemo(
    () => (message ? findVerificationCode(message.subject, message.content, message.html) : null),
    [message]
  )

  if (loading) {
    return (
      <div className="flex h-full min-h-[10rem] flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <span>{t("loading")}</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full min-h-[10rem] flex-col items-center justify-center gap-2 p-6 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-md px-2 py-1 text-xs text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        >
          {t("retry")}
        </button>
      </div>
    )
  }

  if (!message) return null

  return (
    <div className="h-full flex flex-col">
      <div className="px-5 py-4 space-y-2.5 border-b border-border/70 bg-muted/20">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-base font-semibold tracking-tight text-foreground flex-1">{message.subject}</h3>
          <ShareMessageDialog
            emailId={emailId}
            messageId={message.id}
            messageSubject={message.subject}
            trigger={
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
              >
                <Share2 className="h-4 w-4" />
              </Button>
            }
          />
        </div>
        <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
          {message.from_address && (
            <>
              <span className="text-muted-foreground">{t("from")}:</span>
              <span className="truncate font-mono text-foreground/85">{message.from_address}</span>
            </>
          )}
          {message.to_address && (
            <>
              <span className="text-muted-foreground">{t("to")}:</span>
              <span className="truncate font-mono text-foreground/85">{message.to_address}</span>
            </>
          )}
          <span className="text-muted-foreground">{t("time")}:</span>
          <span className="truncate tabular-nums text-foreground/85">
            {new Date(message.sent_at || message.received_at || 0).toLocaleString()}
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
            <SegmentedItem value="html">{t("htmlFormat")}</SegmentedItem>
            <SegmentedItem value="text">{t("textFormat")}</SegmentedItem>
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
        ) : (
          <div className="p-5 text-sm leading-relaxed whitespace-pre-wrap text-foreground">
            {message.content}
          </div>
        )}
      </div>
    </div>
  )
} 