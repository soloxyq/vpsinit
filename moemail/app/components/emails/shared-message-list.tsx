"use client"

import { Mail, Calendar, RefreshCw } from "lucide-react"
import { cn } from "@/lib/utils"
import { useThrottle } from "@/hooks/use-throttle"
import { Button } from "@/components/ui/button"

interface Message {
  id: string
  from_address?: string
  to_address?: string
  subject: string
  received_at?: number
  sent_at?: number
}

interface SharedMessageListProps {
  messages: Message[]
  selectedMessageId?: string | null
  onMessageSelect: (messageId: string) => void
  onLoadMore?: () => void
  onRefresh?: () => void
  loading?: boolean
  loadingMore?: boolean
  refreshing?: boolean
  hasMore?: boolean
  total?: number
  t: {
    received: string
    noMessages: string
    messageCount: string
    loading: string
    loadingMore: string
  }
}

export function SharedMessageList({
  messages,
  selectedMessageId,
  onMessageSelect,
  onLoadMore,
  onRefresh,
  loading = false,
  loadingMore = false,
  refreshing = false,
  hasMore = false,
  total = 0,
  t,
}: SharedMessageListProps) {
  const handleScroll = useThrottle((e: React.UIEvent<HTMLDivElement>) => {
    if (loadingMore || !hasMore || !onLoadMore) return

    const { scrollHeight, scrollTop, clientHeight } = e.currentTarget
    const threshold = clientHeight * 1.5
    const remainingScroll = scrollHeight - scrollTop

    if (remainingScroll <= threshold) {
      onLoadMore()
    }
  }, 200)

  return (
    <div className="h-full flex flex-col">
      <div className="px-2.5 py-2 flex justify-between items-center border-b border-border/70">
        <Button
          variant="ghost"
          size="icon"
          onClick={onRefresh}
          disabled={refreshing || loading}
          className={cn("h-8 w-8 text-muted-foreground hover:text-foreground", refreshing && "animate-spin")}
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
        <span className="text-xs text-muted-foreground tabular-nums">
          {total > 0 ? `${total} ${t.messageCount}` : t.noMessages}
        </span>
      </div>

      <div className="flex-1 overflow-auto" onScroll={handleScroll}>
        {loading ? (
          <div className="p-6 text-center text-sm text-muted-foreground">
            <RefreshCw className="h-5 w-5 animate-spin mx-auto text-primary mb-2" />
            {t.loading}
          </div>
        ) : messages.length > 0 ? (
          <div className="divide-y divide-border/60">
            {messages.map((message) => (
              <div
                key={message.id}
                onClick={() => onMessageSelect(message.id)}
                className={cn(
                  "px-3.5 py-3 cursor-pointer transition-colors duration-150",
                  selectedMessageId === message.id
                    ? "bg-primary/[0.08]"
                    : "hover:bg-accent/60"
                )}
              >
                <div className="flex items-start gap-2.5">
                  <Mail
                    className={cn(
                      "w-4 h-4 mt-0.5 shrink-0 transition-colors",
                      selectedMessageId === message.id ? "text-primary" : "text-muted-foreground/60"
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm text-foreground truncate">
                      {message.subject}
                    </p>
                    <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="truncate font-mono text-[11px]">
                        {message.from_address || message.to_address || ""}
                      </span>
                      <span className="flex items-center gap-1 shrink-0 text-[11px] tabular-nums">
                        <Calendar className="w-3 h-3 opacity-70" />
                        {new Date(
                          message.received_at || message.sent_at || 0
                        ).toLocaleString()}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
            {loadingMore && (
              <div className="text-center text-xs text-muted-foreground py-2">
                {t.loadingMore}
              </div>
            )}
          </div>
        ) : (
          <div className="p-6 text-center text-sm text-muted-foreground">
            {t.noMessages}
          </div>
        )}
      </div>
    </div>
  )
}
