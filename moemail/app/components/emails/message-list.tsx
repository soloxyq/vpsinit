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
  // 读过的时间，null 是未读。发出的邮件一直算已读
  read_at?: number | null
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
  // 这个邮箱的未读数，和邮箱列表上的角标是同一个数字。列表只加载了一部分邮件，要不要显示“全部已读”得看它
  unreadCount?: number
  // 未读数可能变了（来了新邮件、标了已读、删了未读的邮件）：让上层重新取一次
  onUnreadChange?: () => void
}

interface MessageResponse {
  messages: Message[]
  nextCursor: string | null
  total: number
}

export function MessageList({ email, messageType, onMessageSelect, selectedMessageId, refreshTrigger, unreadCount = 0, onUnreadChange }: MessageListProps) {
  const t = useTranslations("emails.messages")
  const tList = useTranslations("emails.list")
  const tCommon = useTranslations("common.actions")
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  // 列表的最新内容，和 state 同步更新（见 updateMessages）。请求返回时拿它来合并：
  // 那时闭包里的 messages 还是发请求时的旧列表，等渲染后再同步又会漏掉刚做的本地修改（比如刚标的已读）
  const messagesRef = useRef<Message[]>([])
  const updateMessages = (next: Message[] | ((prev: Message[]) => Message[])) => {
    const value = typeof next === "function" ? next(messagesRef.current) : next
    messagesRef.current = value
    setMessages(value)
  }
  const [total, setTotal] = useState(0)
  const [messageToDelete, setMessageToDelete] = useState<Message | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  // 清空、删除或换邮箱之后加一：之前发出、还没返回的列表请求作废，免得把删掉的邮件或上一个邮箱的邮件放回列表
  const listVersionRef = useRef(0)
  // 当前邮箱的列表是否已经加载过一次：之后轮询再多出来的才是新到的邮件
  const loadedRef = useRef(false)
  const { toast } = useToast()

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
        // 加载过之后又多出邮件：来了新邮件，未读数跟着变了
        const added = lastDuplicateIndex === -1 ? newMessages.length : lastDuplicateIndex
        if (loadedRef.current && added > 0) onUnreadChange?.()
        loadedRef.current = true

        if (lastDuplicateIndex === -1) {
          updateMessages(newMessages)
          setNextCursor(data.nextCursor)
          setTotal(data.total)
          return
        }
        const uniqueNewMessages = newMessages.slice(0, lastDuplicateIndex)
        // 已经在列表里的邮件沿用本地这份，只同步“已读”：在别处（另一台设备、API）读过的，这里也变成已读。
        // 反过来不同步：这次响应可能是在刚点开的邮件被记成已读之前算出来的
        const readAt = new Map(newMessages.map(m => [m.id, m.read_at]))
        updateMessages([
          ...uniqueNewMessages,
          ...oldMessages.map(m => {
            const serverReadAt = readAt.get(m.id)
            return m.read_at === null && serverReadAt ? { ...m, read_at: serverReadAt } : m
          }),
        ])
        setTotal(data.total)
        return
      }
      updateMessages(prev => [...prev, ...data.messages])
      setNextCursor(data.nextCursor)
      setTotal(data.total)
    } catch (error) {
      console.error("Failed to fetch messages:", error)
    } finally {
      // 作废的请求不结束“加载中”：换邮箱以后，新邮箱自己的请求回来才算加载完
      if (version === listVersionRef.current) setLoading(false)
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
      updateMessages(prev => prev.filter(e => e.id !== message.id))
      setTotal(prev => prev - 1)
      if (message.read_at === null) onUnreadChange?.()

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
    listVersionRef.current++
    loadedRef.current = false
    // 上一个邮箱的列表不留着：新邮箱的请求要是失败了，留着的列表会顶着新邮箱的地址显示出来
    updateMessages([])
    setTotal(0)
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
      updateMessages([])
      setTotal(0)
      setNextCursor(null)
      onMessageSelect(null)
      onUnreadChange?.()
      toast({ title: tList("success"), description: t("clearSuccess") })
    } catch {
      toast({ title: tList("error"), description: tList("deleteFailed"), variant: "destructive" })
    } finally {
      setConfirmClear(false)
    }
  }

  // 点开一封未读的邮件：先在本地去掉未读样式。接口那边由读取这封邮件的请求记成已读
  const markRead = (id: string) => {
    updateMessages(prev => prev.map(m => (m.id === id && m.read_at === null ? { ...m, read_at: Date.now() } : m)))
  }

  // 把这个邮箱里收到的邮件标成已读，包括往下翻才会加载出来的旧邮件。
  // 只标到点按钮时列表里最新的那封为止：这之后才到、还没显示出来的新邮件留着未读
  const handleMarkAllRead = async () => {
    const shown = messagesRef.current
    try {
      const response = await fetch(`/api/emails/${email.id}/messages`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ read: true, before: shown[0]?.received_at })
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      // 本地只改点按钮时显示着的那些：请求期间列表可能多了新邮件，也可能已经换成另一个邮箱的了
      const ids = new Set(shown.map(m => m.id))
      const now = Date.now()
      updateMessages(prev => prev.map(m => (m.read_at === null && ids.has(m.id) ? { ...m, read_at: now } : m)))
      onUnreadChange?.()
    } catch {
      toast({ title: tList("error"), description: t("markAllReadFailed"), variant: "destructive" })
    }
  }

  // 发出的邮件没有未读一说
  const isUnread = (message: Message) => messageType === 'received' && message.read_at === null
  const hasUnread = messageType === 'received' && (unreadCount > 0 || messages.some(isUnread))

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
          <div className="ml-auto flex items-center">
            {hasUnread && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleMarkAllRead}
                className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
              >
                {t("markAllRead")}
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmClear(true)}
              className="h-7 px-2 text-xs text-muted-foreground hover:text-destructive"
            >
              {t("clearAll")}
            </Button>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-auto" onScroll={handleScroll}>
        {loading ? (
          <ListSkeleton rows={4} label={t("loading")} />
        ) : messages.length > 0 ? (
          <div className="divide-y divide-border/60">
            {messages.map(message => {
              const isSelected = selectedMessageId === message.id
              const unread = isUnread(message)
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
                  onClick={() => {
                    if (unread) markRead(message.id)
                    onMessageSelect(message.id, messageType)
                  }}
                  className={cn(
                    "relative px-3.5 py-3 cursor-pointer group transition-colors duration-150",
                    isSelected
                      ? "bg-primary/[0.08] dark:bg-primary/[0.12] before:absolute before:left-0 before:inset-y-2 before:w-0.5 before:rounded-full before:bg-primary"
                      : "hover:bg-accent/60"
                  )}
                >
                  <div className="flex items-start gap-2.5">
                    <div className="relative mt-0.5 shrink-0">
                      {/* 未读圆点放在图标左边的留白里，不占标题的位置：读过以后标题不会跟着挪动 */}
                      {unread && (
                        <span
                          role="img"
                          aria-label={t("unread")}
                          className="absolute right-full top-1/2 mr-1 size-1.5 -translate-y-1/2 rounded-full bg-primary"
                        />
                      )}
                      <Mail
                        className={cn(
                          "w-4 h-4 transition-colors",
                          isSelected ? "text-primary" : "text-muted-foreground/60"
                        )}
                      />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <p className={cn("text-sm text-foreground truncate flex-1", unread ? "font-semibold" : "font-normal")}>
                          {message.subject}
                        </p>
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