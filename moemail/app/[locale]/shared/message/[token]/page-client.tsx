"use client"

import { useTranslations } from "next-intl"
import { BrandHeader } from "@/components/ui/brand-header"
import { FloatingLanguageSwitcher } from "@/components/layout/floating-language-switcher"
import { SharedMessageDetail } from "@/components/emails/shared-message-detail"
import { useMounted } from "@/hooks/use-mounted"
import type { AttachmentInfo } from "@/lib/attachments"

interface MessageDetail {
  id: string
  from_address?: string
  to_address?: string
  subject: string
  content?: string
  html?: string
  received_at?: Date
  sent_at?: Date
  expiresAt?: Date
  emailAddress?: string
  emailExpiresAt?: Date
  attachments?: AttachmentInfo[]
}

interface SharedMessagePageClientProps {
  message: MessageDetail
  token: string
}

export function SharedMessagePageClient({ message, token }: SharedMessagePageClientProps) {
  const t = useTranslations("emails")
  const tShared = useTranslations("emails.shared")
  const mounted = useMounted()

  return (
    <div className="min-h-screen bg-page">
      <div className="container mx-auto p-4 pb-20 lg:pb-6 max-w-7xl">
        <BrandHeader
          title={message.emailAddress || message.to_address || message.subject}
          subtitle={message.emailExpiresAt && new Date(message.emailExpiresAt).getUTCFullYear() === 9999
            ? tShared("permanent")
            : message.emailExpiresAt
              ? mounted
                ? `${tShared("expiresAt")}: ${new Date(message.emailExpiresAt).toLocaleString()}`
                : "\u00a0"
              : tShared("sharedMessage")}
          ctaText={tShared("createOwnEmail")}
        />

        <div className="mt-6 mx-auto max-w-4xl">
          <div className="border border-border/80 bg-card rounded-xl shadow-sm overflow-hidden h-[calc(100dvh-260px)] min-h-[420px] lg:h-[calc(100dvh-280px)] lg:min-h-[480px]">
            <SharedMessageDetail
              attachmentBaseUrl={`/api/shared/message/${token}/attachments`}
              message={{
                ...message,
                received_at: message.received_at ? new Date(message.received_at).getTime() : undefined,
                sent_at: message.sent_at ? new Date(message.sent_at).getTime() : undefined
              }}
              loading={false}
              t={{
                messageContent: t("layout.messageContent"),
                selectMessage: t("layout.selectMessage"),
                loading: tShared("loading"),
                from: t("messageView.from"),
                to: t("messageView.to"),
                subject: t("messages.subject"),
                time: t("messageView.time"),
                htmlFormat: t("messageView.htmlFormat"),
                textFormat: t("messageView.textFormat")
              }}
            />
          </div>
        </div>
      </div>
      
      <FloatingLanguageSwitcher />
    </div>
  )
}
