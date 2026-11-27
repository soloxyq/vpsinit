"use client"

import { useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { useTranslations } from "next-intl"
import { CreateDialog } from "./create-dialog"
import { ShareDialog } from "./share-dialog"
import { Mail, RefreshCw, Share2, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { EmptyState, ListSkeleton } from "@/components/ui/empty-state"
import { useThrottle } from "@/hooks/use-throttle"
import { EMAIL_CONFIG } from "@/config"
import { useToast } from "@/components/ui/use-toast"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { ROLES } from "@/lib/permissions"
import { useUserRole } from "@/hooks/use-user-role"
import { useConfig } from "@/hooks/use-config"

interface Email {
  id: string
  address: string
  createdAt: number
  expiresAt: number
}

interface EmailListProps {
  onEmailSelect: (email: Email | null) => void
  selectedEmailId?: string
  // 每个邮箱的未读邮件数（邮箱 ID → 数量），没有未读的邮箱不在里面
  unreadCounts?: Record<string, number>
}

interface EmailResponse {
  emails: Email[]
  nextCursor: string | null
  total: number
}

export function EmailList({ onEmailSelect, selectedEmailId, unreadCounts }: EmailListProps) {
  const { data: session } = useSession()
  const { config } = useConfig()
  const { role } = useUserRole()
  const t = useTranslations("emails.list")
  const tCommon = useTranslations("common.actions")
  const [emails, setEmails] = useState<Email[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [total, setTotal] = useState(0)
  const [emailToDelete, setEmailToDelete] = useState<Email | null>(null)
  const { toast } = useToast()

  const fetchEmails = async (cursor?: string) => {
    try {
      const url = new URL("/api/emails", window.location.origin)
      if (cursor) {
        url.searchParams.set('cursor', cursor)
      }
      const response = await fetch(url)
      const data = await response.json() as EmailResponse
      
      if (!cursor) {
        const newEmails = data.emails
        const oldEmails = emails

        const lastDuplicateIndex = newEmails.findIndex(
          newEmail => oldEmails.some(oldEmail => oldEmail.id === newEmail.id)
        )

        if (lastDuplicateIndex === -1) {
          setEmails(newEmails)
          setNextCursor(data.nextCursor)
          setTotal(data.total)
          return
        }
        const uniqueNewEmails = newEmails.slice(0, lastDuplicateIndex)
        setEmails([...uniqueNewEmails, ...oldEmails])
        setTotal(data.total)
        return
      }
      setEmails(prev => [...prev, ...data.emails])
      setNextCursor(data.nextCursor)
      setTotal(data.total)
    } catch (error) {
      console.error("Failed to fetch emails:", error)
    } finally {
      setLoading(false)
      setRefreshing(false)
      setLoadingMore(false)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    await fetchEmails()
  }

  const handleScroll = useThrottle((e: React.UIEvent<HTMLDivElement>) => {
    if (loadingMore) return

    const { scrollHeight, scrollTop, clientHeight } = e.currentTarget
    const threshold = clientHeight * 1.5
    const remainingScroll = scrollHeight - scrollTop

    if (remainingScroll <= threshold && nextCursor) {
      setLoadingMore(true)
      fetchEmails(nextCursor)
    }
  }, 200)

  useEffect(() => {
    if (session) fetchEmails()
  }, [session])

  const handleDelete = async (email: Email) => {
    try {
      const response = await fetch(`/api/emails/${email.id}`, {
        method: "DELETE"
      })

      if (!response.ok) {
        const data = await response.json()
        toast({
          title: t("error"),
          description: (data as { error: string }).error,
          variant: "destructive"
        })
        return
      }

      setEmails(prev => prev.filter(e => e.id !== email.id))
      setTotal(prev => prev - 1)

      toast({
        title: t("success"),
        description: t("deleteSuccess")
      })
      
      if (selectedEmailId === email.id) {
        onEmailSelect(null)
      }
    } catch {
      toast({
        title: t("error"),
        description: t("deleteFailed"),
        variant: "destructive"
      })
    } finally {
      setEmailToDelete(null)
    }
  }

  if (!session) return null

  return (
    <>
      <div className="flex flex-col h-full">
        <div className="px-2.5 py-2 flex justify-between items-center border-b border-border/70">
          <div className="flex items-center gap-2">
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
            ) : (
              <span className="text-xs text-muted-foreground tabular-nums">
                {role === ROLES.EMPEROR ? (
                  t("emailCountUnlimited", { count: total })
                ) : (
                  t("emailCount", { count: total, max: config?.maxEmails || EMAIL_CONFIG.MAX_ACTIVE_EMAILS })
                )}
              </span>
            )}
          </div>
          <CreateDialog onEmailCreated={handleRefresh} />
        </div>
        
        <div className="flex-1 overflow-auto" onScroll={handleScroll}>
          {loading ? (
            <ListSkeleton rows={4} label={t("loading")} />
          ) : emails.length > 0 ? (
            <div className="p-2 space-y-1">
              {emails.map(email => {
                const isSelected = selectedEmailId === email.id
                // 接口每个邮箱最多数到 UNREAD_COUNT_CAP：到了上限，实际可能更多
                const unread = unreadCounts?.[email.id] ?? 0
                const unreadText = unread >= EMAIL_CONFIG.UNREAD_COUNT_CAP ? `${EMAIL_CONFIG.UNREAD_COUNT_CAP - 1}+` : `${unread}`
                return (
                  <div
                    key={email.id}
                    className={cn(
                      "relative flex items-center gap-2.5 px-2.5 py-2 rounded-lg cursor-pointer text-sm group transition-colors duration-150",
                      isSelected
                        ? "bg-primary/[0.08] ring-1 ring-inset ring-primary/20"
                        : "hover:bg-accent/70"
                    )}
                    onClick={() => onEmailSelect(email)}
                  >
                    <Mail
                      className={cn(
                        "h-4 w-4 shrink-0 transition-colors",
                        isSelected ? "text-primary" : "text-muted-foreground/70"
                      )}
                    />
                    <div className="truncate flex-1 min-w-0">
                      <div className="font-mono text-[13px] font-medium truncate text-foreground">{email.address}</div>
                      <div className="text-[11px] text-muted-foreground tabular-nums mt-0.5 truncate">
                        {new Date(email.expiresAt).getFullYear() === 9999 ? (
                          t("permanent")
                        ) : (
                          `${t("expiresAt")}: ${new Date(email.expiresAt).toLocaleString()}`
                        )}
                      </div>
                    </div>
                    {unread > 0 && (
                      <span
                        role="img"
                        aria-label={t("unreadCount", { count: unreadText })}
                        className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-medium leading-none tabular-nums text-primary-foreground"
                      >
                        {unreadText}
                      </span>
                    )}
                    <div
                      className="flex shrink-0 transition-opacity opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto [@media(hover:none)]:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:hover)]:absolute [@media(hover:hover)]:right-2 [@media(hover:hover)]:top-1/2 [@media(hover:hover)]:-translate-y-1/2 [@media(hover:hover)]:rounded-md [@media(hover:hover)]:bg-card"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div
                        className={cn(
                          "flex items-center gap-0.5 [@media(hover:hover)]:rounded-md [@media(hover:hover)]:pl-1",
                          isSelected
                            ? "[@media(hover:hover)]:bg-primary/[0.08]"
                            : "[@media(hover:hover)]:group-hover:bg-accent/70"
                        )}
                      >
                        <ShareDialog
                          emailId={email.id}
                          emailAddress={email.address}
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
                            setEmailToDelete(email)
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
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
            <EmptyState icon={Mail} title={t("noEmails")} />
          )}
        </div>
      </div>

      <AlertDialog open={!!emailToDelete} onOpenChange={() => setEmailToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteConfirm")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("deleteDescription", { email: emailToDelete?.address || "" })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tCommon("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive hover:bg-destructive/90"
              onClick={() => emailToDelete && handleDelete(emailToDelete)}
            >
              {tCommon("delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
} 