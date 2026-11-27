"use client"

import { Mail, RefreshCw } from "lucide-react"
import { cn } from "@/lib/utils"
import { useThrottle } from "@/hooks/use-throttle"
import { Button } from "@/components/ui/button"
import { EmptyState, ListSkeleton } from "@/components/ui/empty-state"

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
      <div className="h-9 px-2.5 flex items-center gap-2 border-b border-border/70">
        <Button
          variant="ghost"
          size="icon"
          onClick={onRefresh}
          disabled={refreshing || loading}
          className="h-8 w-8 text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
        </Button>
        {loading ? (
          <span className="inline-block h-3 w-14 rounded bg-muted animate-pulse" aria-hidden="true" />
        ) : total > 0 ? (
          <span className="text-xs text-muted-foreground tabular-nums">
            {`${total} ${t.messageCount}`}
          </span>
        ) : null}
      </div>

      <div className="flex-1 overflow-auto" onScroll={handleScroll}>
        {loading ? (
          <ListSkeleton rows={4} label={t.loading} />
        ) : messages.length > 0 ? (
          <div className="divide-y divide-border/60">
            {messages.map((message) => {
              const isSelected = selectedMessageId === message.id
              return (
                <div
                  key={message.id}
                  onClick={() => onMessageSelect(message.id)}
                  className={cn(
                    "relative px-3.5 py-3 cursor-pointer transition-colors duration-150",
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
                        <p className="font-medium text-sm text-foreground truncate flex-1">
                          {message.subject}
                        </p>
                        <span
                          className="shrink-0 text-[11px] tabular-nums text-muted-foreground"
                          suppressHydrationWarning
                        >
                          {new Date(
                            message.received_at || message.sent_at || 0
                          ).toLocaleString()}
                        </span>
                      </div>
                      <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                        {message.from_address || message.to_address || ""}
                      </p>
                    </div>
                  </div>
                </div>
              )
            })}
            {loadingMore && (
              <div className="text-center text-xs text-muted-foreground py-2">
                {t.loadingMore}
              </div>
            )}
          </div>
        ) : (
          <EmptyState icon={Mail} title={t.noMessages} />
        )}
      </div>
    </div>
  )
}
