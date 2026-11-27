"use client"

import { useState, useEffect, useRef } from "react"
import { useTranslations } from "next-intl"
import { BrandHeader } from "@/components/ui/brand-header"
import { Button } from "@/components/ui/button"
import { FloatingLanguageSwitcher } from "@/components/layout/floating-language-switcher"
import { SharedMessageList } from "@/components/emails/shared-message-list"
import { SharedMessageDetail } from "@/components/emails/shared-message-detail"
import { EMAIL_CONFIG } from "@/config"
import { useMounted } from "@/hooks/use-mounted"
import { usePolling } from "@/hooks/use-polling"
import type { AttachmentInfo } from "@/lib/attachments"

interface Email {
  id: string
  address: string
  createdAt: Date
  expiresAt: Date
}

interface Message {
  id: string
  from_address?: string
  to_address?: string
  subject: string
  received_at?: Date
  sent_at?: Date
  has_attachments?: boolean
}

interface MessageDetail extends Message {
  content?: string
  html?: string
  attachments?: AttachmentInfo[]
}

interface SharedEmailPageClientProps {
  email: Email
  initialMessages: Message[]
  initialNextCursor: string | null
  initialTotal: number
  token: string
}

export function SharedEmailPageClient({
  email,
  initialMessages,
  initialNextCursor,
  initialTotal,
  token
}: SharedEmailPageClientProps) {
  const t = useTranslations("emails")
  const tShared = useTranslations("emails.shared")
  const mounted = useMounted()

  const [messages, setMessages] = useState<Message[]>(initialMessages)
  const [selectedMessage, setSelectedMessage] = useState<MessageDetail | null>(null)
  const [messageLoading, setMessageLoading] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(initialNextCursor)
  const [loadingMore, setLoadingMore] = useState(false)
  const [total, setTotal] = useState(initialTotal)
  const [refreshing, setRefreshing] = useState(false)
  const messagesRef = useRef<Message[]>(initialMessages)

  // 当 messages 改变时更新 ref
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const fetchMessages = async (cursor?: string) => {
    try {
      if (cursor) {
        setLoadingMore(true)
      }

      const url = new URL(`/api/shared/${token}/messages`, window.location.origin)
      if (cursor) {
        url.searchParams.set('cursor', cursor)
      }

      const messagesResponse = await fetch(url)
      if (messagesResponse.ok) {
        const messagesData = await messagesResponse.json() as {
          messages: Message[]
          nextCursor: string | null
          total: number
        }

        if (!cursor) {
          // 刷新时：合并新消息和旧消息，避免重复
          const newMessages = messagesData.messages
          const oldMessages = messagesRef.current

          // 找到第一个重复的消息
          const lastDuplicateIndex = newMessages.findIndex(
            newMsg => oldMessages.some(oldMsg => oldMsg.id === newMsg.id)
          )

          if (lastDuplicateIndex === -1) {
            // 没有重复，直接使用新消息
            setMessages(newMessages)
            setNextCursor(messagesData.nextCursor)
            setTotal(messagesData.total)
            return
          }
          // 有重复，只添加新的消息
          const uniqueNewMessages = newMessages.slice(0, lastDuplicateIndex)
          setMessages([...uniqueNewMessages, ...oldMessages])
          setTotal(messagesData.total)
          return
        }
        // 加载更多：追加到列表末尾
        setMessages(prev => [...prev, ...(messagesData.messages || [])])
        setNextCursor(messagesData.nextCursor)
        setTotal(messagesData.total)
      }
    } catch (err) {
      console.error("Failed to fetch messages:", err)
    } finally {
      setLoadingMore(false)
      setRefreshing(false)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    await fetchMessages()
  }

  // 定时刷新列表；标签页在后台时暂停
  usePolling(() => {
    if (!refreshing && !loadingMore) fetchMessages()
  }, EMAIL_CONFIG.POLL_INTERVAL)

  const handleLoadMore = () => {
    if (nextCursor && !loadingMore) {
      fetchMessages(nextCursor)
    }
  }

  const fetchMessageDetail = async (messageId: string) => {
    try {
      setMessageLoading(true)

      const response = await fetch(`/api/shared/${token}/messages/${messageId}`)

      if (!response.ok) {
        throw new Error("Failed to load message")
      }

      const data = await response.json() as { message: MessageDetail }
      setSelectedMessage(data.message)
    } catch (err) {
      console.error("Failed to fetch message:", err)
    } finally {
      setMessageLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-page">
      <div className="container mx-auto p-4 pb-20 lg:pb-6 max-w-7xl">
        <BrandHeader
          title={email.address}
          subtitle={(() => {
            try {
              const expiresDate = new Date(email.expiresAt)
              if (isNaN(expiresDate.getTime())) return tShared("sharedMailbox")
              // 永久邮箱存的是 9999-01-01T00:00:00Z，按 UTC 年份判断，服务器和浏览器结果一致
              if (expiresDate.getUTCFullYear() === 9999) return tShared("permanent")
              // 具体时间按访客本地时区显示，只能在浏览器里格式化；挂载前先占住这一行
              if (!mounted) return "\u00a0"
              return `${tShared("expiresAt")}: ${expiresDate.toLocaleDateString()} ${expiresDate.toLocaleTimeString()}`
            } catch {
              return tShared("sharedMailbox")
            }
          })()}
          ctaText={tShared("createOwnEmail")}
        />

        {/* 桌面端双栏布局 */}
        <div className="hidden lg:grid grid-cols-2 gap-4 h-[calc(100dvh-280px)] lg:min-h-[480px] mt-6">
          <div className="border border-border/80 bg-card rounded-xl shadow-sm overflow-hidden">
            <SharedMessageList
              messages={messages.map(msg => ({
                ...msg,
                received_at: (() => {
                  if (!msg.received_at) return undefined
                  try {
                    const date = new Date(msg.received_at)
                    return isNaN(date.getTime()) ? undefined : date.getTime()
                  } catch {
                    return undefined
                  }
                })(),
                sent_at: (() => {
                  if (!msg.sent_at) return undefined
                  try {
                    const date = new Date(msg.sent_at)
                    return isNaN(date.getTime()) ? undefined : date.getTime()
                  } catch {
                    return undefined
                  }
                })()
              }))}
              selectedMessageId={selectedMessage?.id}
              onMessageSelect={fetchMessageDetail}
              onLoadMore={handleLoadMore}
              onRefresh={handleRefresh}
              loading={false}
              loadingMore={loadingMore}
              refreshing={refreshing}
              hasMore={!!nextCursor}
              total={total}
              t={{
                received: t("messages.received"),
                noMessages: t("messages.noMessages"),
                messageCount: t("messages.messageCount"),
                loading: t("messageView.loading"),
                loadingMore: t("messages.loadingMore")
              }}
            />
          </div>

          <div className="border border-border/80 bg-card rounded-xl shadow-sm overflow-hidden">
            <SharedMessageDetail
              attachmentBaseUrl={selectedMessage ? `/api/shared/${token}/messages/${selectedMessage.id}/attachments` : undefined}
              message={selectedMessage ? {
                ...selectedMessage,
                received_at: (() => {
                  if (!selectedMessage.received_at) return undefined
                  try {
                    const date = new Date(selectedMessage.received_at)
                    return isNaN(date.getTime()) ? undefined : date.getTime()
                  } catch {
                    return undefined
                  }
                })(),
                sent_at: (() => {
                  if (!selectedMessage.sent_at) return undefined
                  try {
                    const date = new Date(selectedMessage.sent_at)
                    return isNaN(date.getTime()) ? undefined : date.getTime()
                  } catch {
                    return undefined
                  }
                })()
              } : null}
              loading={messageLoading}
              t={{
                messageContent: t("layout.messageContent"),
                selectMessage: t("layout.selectMessage"),
                loading: t("messageView.loading"),
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

        {/* 移动端单栏布局 */}
        <div className="lg:hidden h-[calc(100dvh-260px)] min-h-[420px] mt-6">
          <div className="border border-border/80 bg-card rounded-xl shadow-sm overflow-hidden h-full flex flex-col">
            {!selectedMessage ? (
              // 消息列表视图
              <SharedMessageList
                messages={messages.map(msg => ({
                  ...msg,
                  received_at: (() => {
                    if (!msg.received_at) return undefined
                    try {
                      const date = new Date(msg.received_at)
                      return isNaN(date.getTime()) ? undefined : date.getTime()
                    } catch {
                      return undefined
                    }
                  })(),
                  sent_at: (() => {
                    if (!msg.sent_at) return undefined
                    try {
                      const date = new Date(msg.sent_at)
                      return isNaN(date.getTime()) ? undefined : date.getTime()
                    } catch {
                      return undefined
                    }
                  })()
                }))}
                selectedMessageId={null}
                onMessageSelect={fetchMessageDetail}
                onLoadMore={handleLoadMore}
                onRefresh={handleRefresh}
                loading={false}
                loadingMore={loadingMore}
                refreshing={refreshing}
                hasMore={!!nextCursor}
                total={total}
                t={{
                  received: t("messages.received"),
                  noMessages: t("messages.noMessages"),
                  messageCount: t("messages.messageCount"),
                  loading: t("messageView.loading"),
                  loadingMore: t("messages.loadingMore")
                }}
              />
            ) : (
              // 消息详情视图
              <>
                <div className="px-3.5 py-2 border-b border-border/70 bg-muted/30 flex items-center justify-between gap-2 shrink-0">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedMessage(null)}
                    className="-ml-2 h-8 gap-1 text-primary hover:text-primary hover:bg-primary/10 shrink-0"
                  >
                    {t("layout.backToMessageList")}
                  </Button>
                  <span className="text-sm font-medium truncate">{t("layout.messageContent")}</span>
                </div>
                <div className="flex-1 overflow-auto">
                  <SharedMessageDetail
                    attachmentBaseUrl={`/api/shared/${token}/messages/${selectedMessage.id}/attachments`}
                    message={{
                      ...selectedMessage,
                      received_at: (() => {
                        if (!selectedMessage.received_at) return undefined
                        try {
                          const date = new Date(selectedMessage.received_at)
                          return isNaN(date.getTime()) ? undefined : date.getTime()
                        } catch {
                          return undefined
                        }
                      })(),
                      sent_at: (() => {
                        if (!selectedMessage.sent_at) return undefined
                        try {
                          const date = new Date(selectedMessage.sent_at)
                          return isNaN(date.getTime()) ? undefined : date.getTime()
                        } catch {
                          return undefined
                        }
                      })()
                    }}
                    loading={messageLoading}
                    t={{
                      messageContent: t("layout.messageContent"),
                      selectMessage: t("layout.selectMessage"),
                      loading: t("messageView.loading"),
                      from: t("messageView.from"),
                      to: t("messageView.to"),
                      subject: t("messages.subject"),
                      time: t("messageView.time"),
                      htmlFormat: t("messageView.htmlFormat"),
                      textFormat: t("messageView.textFormat")
                    }}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <FloatingLanguageSwitcher />
    </div>
  )
}
