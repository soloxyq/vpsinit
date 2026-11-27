"use client"

import { useState, useEffect, useRef } from "react"
import { useTranslations } from "next-intl"
import { Mail, RefreshCw, Trash2, Share2, Paperclip } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { EmptyState, ListSkeleton } from "@/components/ui/empty-state"
import { useThrottle } from "@/hooks/use-throttle"
import { usePolling } from "@/hooks/use-polling"
import { EMAIL_CONFIG } from "@/config"
import { useToast } from "@/components/ui/use-toast"
import { ShareMessageDialog } from "./share-message-dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";

interface Message {
  id: string
  from_address?: string
  to_address?: string
  subject: string
  received_at?: number
  sent_at?: number
  has_attachments?: boolean
}

interface MessageListProps {
  email: {
    id: string
    address: string
  }
  messageType: 'received' | 'sent'
  onMessageSelect: (messageId: string | null, messageType?: 'received' | 'sent') => void
  selectedMessageId?: string | null
  refreshTrigger?: number
}

interface MessageResponse {
  messages: Message[]
  nextCursor: string | null
  total: number
}

export function MessageList({ email, messageType, onMessageSelect, selectedMessageId, refreshTrigger }: MessageListProps) {
  const t = useTranslations("emails.messages")
  const tList = useTranslations("emails.list")
  const tCommon = useTranslations("common.actions")
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const messagesRef = useRef<Message[]>([]) // 添加 ref 来追踪最新的消息列表
  const [total, setTotal] = useState(0)
  const [messageToDelete, setMessageToDelete] = useState<Message | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  // 清空或删除之后加一：之前发出、还没返回的列表请求作废，免得把删掉的邮件又放回列表
  const listVersionRef = useRef(0)
  const { toast } = useToast()

  // 当 messages 改变时更新 ref
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const fetchMessages = async (cursor?: string) => {
    const version = listVersionRef.current
    try {
      const url = new URL(`/api/emails/${email.id}`, window.location.origin)
      if (messageType === 'sent') {
        url.searchParams.set('type', 'sent')
      }
      if (cursor) {
        url.searchParams.set('cursor', cursor)
      }
      const response = await fetch(url)
      const data = await response.json() as MessageResponse
      if (version !== listVersionRef.current) return
      
      if (!cursor) {
        const newMessages = data.messages
        const oldMessages = messagesRef.current

        const lastDuplicateIndex = newMessages.findIndex(
          newMsg => oldMessages.some(oldMsg => oldMsg.id === newMsg.id)
        )

        if (lastDuplicateIndex === -1) {
          setMessages(newMessages)
          setNextCursor(data.nextCursor)
          setTotal(data.total)
          return
        }
        const uniqueNewMessages = newMessages.slice(0, lastDuplicateIndex)
        setMessages([...uniqueNewMessages, ...oldMessages])
        setTotal(data.total)
        return
      }
      setMessages(prev => [...prev, ...data.messages])
      setNextCursor(data.nextCursor)
      setTotal(data.total)
    } catch (error) {
      console.error("Failed to fetch messages:", error)
    } finally {
      setLoading(false)
      setRefreshing(false)
      setLoadingMore(false)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    await fetchMessages()
  }

  const handleScroll = useThrottle((e: React.UIEvent<HTMLDivElement>) => {
    if (loadingMore) return

    const { scrollHeight, scrollTop, clientHeight } = e.currentTarget
    const threshold = clientHeight * 1.5
    const remainingScroll = scrollHeight - scrollTop

    if (remainingScroll <= threshold && nextCursor) {
      setLoadingMore(true)
      fetchMessages(nextCursor)
    }
  }, 200)

  const handleDelete = async (message: Message) => {
    try {
      const response = await fetch(`/api/emails/${email.id}/${message.id}${messageType === 'sent' ? '?type=sent' : ''}`, {
        method: "DELETE"
      })

      if (!response.ok) {
        const data = await response.json()
        toast({
          title: tList("error"),
          description: (data as { error: string }).error,
          variant: "destructive"
        })
        return
      }

      listVersionRef.current++
      setMessages(prev => prev.filter(e => e.id !== message.id))
      setTotal(prev => prev - 1)

      toast({
        title: tList("success"),
        description: tList("deleteSuccess")
      })

      if (selectedMessageId === message.id) {
        onMessageSelect(null)
      }
    } catch {
      toast({
        title: tList("error"),
        description: tList("deleteFailed"),
        variant: "destructive"
      })
    } finally {
      setMessageToDelete(null)
    }
  }

  useEffect(() => {
    if (!email.id) {
      return
    }
    setLoading(true)
    setNextCursor(null)
    fetchMessages()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email.id])

  // 定时刷新列表；标签页在后台时暂停
  usePolling(() => {
    if (!refreshing && !loadingMore) fetchMessages()
  }, EMAIL_CONFIG.POLL_INTERVAL, !!email.id)

  useEffect(() => {
    if (refreshTrigger && refreshTrigger > 0) {
      setRefreshing(true)
      fetchMessages()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTrigger])

  // 清空当前列表（收到的或发出的）里的全部邮件，附件由接口一起删掉
  const handleClear = async () => {
    try {
      const response = await fetch(
        `/api/emails/${email.id}/messages${messageType === 'sent' ? '?type=sent' : ''}`,
        { method: "DELETE" }
      )
      if (!response.ok) {
        const data = await response.json().catch(() => ({})) as { error?: string }
        toast({ title: tList("error"), description: data.error || tList("deleteFailed"), variant: "destructive" })
        return
      }
      listVersionRef.current++
      setMessages([])
      setTotal(0)
      setNextCursor(null)
      onMessageSelect(null)
      toast({ title: tList("success"), description: t("clearSuccess") })
    } catch {
      toast({ title: tList("error"), description: tList("deleteFailed"), variant: "destructive" })
    } finally {
      setConfirmClear(false)
    }
  }

  const currentYear = new Date().getFullYear()

  return (
  <>
    <div className="h-full flex flex-col">
      <div className="h-9 px-2.5 flex items-center gap-2 border-b border-border/70">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleRefresh}
          disabled={refreshing}
          className="h-8 w-8 text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
        </Button>
        {loading ? (
          <span className="inline-block h-3 w-14 rounded bg-muted animate-pulse" aria-hidden="true" />
        ) : total > 0 ? (
          <span className="text-xs text-muted-foreground tabular-nums">
            {`${total} ${t("messageCount")}`}
          </span>
        ) : null}
        {!loading && total > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setConfirmClear(true)}
            className="ml-auto h-7 px-2 text-xs text-muted-foreground hover:text-destructive"
          >
            {t("clearAll")}
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-auto" onScroll={handleScroll}>
        {loading ? (
          <ListSkeleton rows={4} label={t("loading")} />
        ) : messages.length > 0 ? (
          <div className="divide-y divide-border/60">
            {messages.map(message => {
              const isSelected = selectedMessageId === message.id
              const timestamp = message.received_at || message.sent_at || 0
              const date = new Date(timestamp)
              const fullTime = date.toLocaleString()
              const shortTime = date.toLocaleString(
                undefined,
                date.getFullYear() === currentYear
                  ? { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }
                  : { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }
              )
              return (
                <div
                  key={message.id}
                  onClick={() => onMessageSelect(message.id, messageType)}
                  className={cn(
                    "relative px-3.5 py-3 cursor-pointer group transition-colors duration-150",
                    isSelected
                      ? "bg-primary/[0.08] dark:bg-primary/[0.12] before:absolute before:left-0 before:inset-y-2 before:w-0.5 before:rounded-full before:bg-primary"
                      : "hover:bg-accent/60"
                  )}
                >
                  <div className="flex items-start gap-2.5">
                    <Mail
                      className={cn(
                        "w-4 h-4 mt-0.5 shrink-0 transition-colors",
                        isSelected ? "text-primary" : "text-muted-foreground/60"
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <p className="font-medium text-sm text-foreground truncate flex-1">{message.subject}</p>
                        {message.has_attachments && (
                          <Paperclip className="h-3 w-3 shrink-0 self-center text-muted-foreground" />
                        )}
                        <span
                          className="shrink-0 text-[11px] tabular-nums text-muted-foreground transition-opacity [@media(hover:hover)]:group-hover:opacity-0 [@media(hover:hover)]:group-focus-within:opacity-0"
                          title={fullTime}
                        >
                          {shortTime}
                        </span>
                      </div>
                      <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                        {message.from_address || message.to_address || ''}
                      </p>
                    </div>
                    <div
                      className="flex shrink-0 self-center transition-opacity opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto [@media(hover:none)]:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:hover)]:absolute [@media(hover:hover)]:right-2 [@media(hover:hover)]:top-1/2 [@media(hover:hover)]:-translate-y-1/2 [@media(hover:hover)]:rounded-md [@media(hover:hover)]:bg-card"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div
                        className={cn(
                          "flex items-center gap-0.5 [@media(hover:hover)]:rounded-md [@media(hover:hover)]:pl-1.5",
                          isSelected
                            ? "[@media(hover:hover)]:bg-primary/[0.08] dark:[@media(hover:hover)]:bg-primary/[0.12]"
                            : "[@media(hover:hover)]:group-hover:bg-accent/60"
                        )}
                      >
                        <ShareMessageDialog
                          emailId={email.id}
                          messageId={message.id}
                          messageSubject={message.subject}
                          trigger={
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground hover:text-foreground"
                            >
                              <Share2 className="h-3.5 w-3.5" />
                            </Button>
                          }
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation()
                            setMessageToDelete(message)
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
            {loadingMore && (
              <div className="text-center text-xs text-muted-foreground py-2">
                {t("loadingMore")}
              </div>
            )}
          </div>
        ) : (
          <EmptyState icon={Mail} title={t("noMessages")} />
        )}
      </div>
    </div>
    <AlertDialog open={!!messageToDelete} onOpenChange={() => setMessageToDelete(null)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{tList("deleteConfirm")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("deleteMessageDescription", { subject: messageToDelete?.subject || "" })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{tCommon("cancel")}</AlertDialogCancel>
          <AlertDialogAction
              className="bg-destructive hover:bg-destructive/90"
              onClick={() => messageToDelete && handleDelete(messageToDelete)}
          >
            {tCommon("delete")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    <AlertDialog open={confirmClear} onOpenChange={setConfirmClear}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("clearConfirm")}</AlertDialogTitle>
          <AlertDialogDescription>
            {t("clearDescription", { count: total })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{tCommon("cancel")}</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive hover:bg-destructive/90"
            onClick={handleClear}
          >
            {t("clearAll")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </>
  )
} 