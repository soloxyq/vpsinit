"use client"

import { useTranslations } from "next-intl"
import { Button } from "@/components/ui/button"
import { Crown, Gem, Sword, User2, Loader2, Search, ChevronLeft, ChevronRight, Users, Trash2 } from "lucide-react"
import { Input } from "@/components/ui/input"
import { useState, useEffect, useCallback, useRef } from "react"
import { useToast } from "@/components/ui/use-toast"
import { ROLES, Role } from "@/lib/permissions"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
import { EmptyState } from "@/components/ui/empty-state"

type RoleWithoutEmperor = Exclude<Role, typeof ROLES.EMPEROR>

interface UserItem {
  id: string
  name: string | null
  username: string | null
  email: string | null
  image: string | null
  role: string | null
}

const PAGE_SIZE = 10

export function PromotePanel() {
  const t = useTranslations("profile.promote")
  const tCard = useTranslations("profile.card")
  const [users, setUsers] = useState<UserItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [loading, setLoading] = useState(true)
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null)
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null)
  const [userToDelete, setUserToDelete] = useState<UserItem | null>(null)
  const reqSeqRef = useRef(0)
  const { toast } = useToast()

  const roleNames = {
    [ROLES.EMPEROR]: tCard("roles.EMPEROR"),
    [ROLES.DUKE]: tCard("roles.DUKE"),
    [ROLES.KNIGHT]: tCard("roles.KNIGHT"),
    [ROLES.CIVILIAN]: tCard("roles.CIVILIAN"),
  } as const

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  useEffect(() => {
    const trimmed = search.trim()
    const timer = setTimeout(() => {
      setDebouncedSearch((prev) => {
        if (prev !== trimmed) setPage(1)
        return trimmed
      })
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const fetchUsers = useCallback(async () => {
    const seq = ++reqSeqRef.current
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        pageSize: PAGE_SIZE.toString(),
      })
      if (debouncedSearch) {
        params.set("search", debouncedSearch)
      }
      const res = await fetch(`/api/roles/users?${params}`)
      if (!res.ok) throw new Error("Failed to fetch")
      const data = await res.json() as {
        users: UserItem[]
        total: number
        page: number
        pageSize: number
      }
      if (seq !== reqSeqRef.current) return
      setUsers(data.users)
      setTotal(data.total)
    } catch {
      if (seq !== reqSeqRef.current) return
      toast({
        title: t("updateFailed"),
        variant: "destructive",
      })
    } finally {
      if (seq === reqSeqRef.current) setLoading(false)
    }
  }, [page, debouncedSearch, t, toast])

  useEffect(() => {
    fetchUsers()
  }, [fetchUsers])

  const handleRoleChange = async (userId: string, newRole: RoleWithoutEmperor) => {
    setUpdatingUserId(userId)
    try {
      const res = await fetch("/api/roles/promote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId, roleName: newRole }),
      })
      if (!res.ok) {
        const error = await res.json() as { error: string }
        throw new Error(error.error)
      }
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u))
      )
      toast({ title: t("updateSuccess") })
    } catch (error) {
      toast({
        title: t("updateFailed"),
        description: error instanceof Error ? error.message : undefined,
        variant: "destructive",
      })
    } finally {
      setUpdatingUserId(null)
    }
  }

  const handleDelete = async (user: UserItem) => {
    setDeletingUserId(user.id)
    try {
      const res = await fetch(`/api/users/${user.id}`, {
        method: "DELETE",
      })
      if (!res.ok) {
        const error = await res.json() as { error: string }
        throw new Error(error.error)
      }
      toast({ title: t("deleteSuccess") })
      setUserToDelete(null)
      // 若删除的是当前页最后一条，且不在首页，则退回上一页（useEffect 会重新拉取）
      if (users.length === 1 && page > 1) {
        setPage((p) => p - 1)
      } else {
        await fetchUsers()
      }
    } catch (error) {
      toast({
        title: t("deleteFailed"),
        description: error instanceof Error ? error.message : undefined,
        variant: "destructive",
      })
    } finally {
      setDeletingUserId(null)
    }
  }

  return (
    <div className="bg-card rounded-xl border border-border/80 shadow-sm p-4 sm:p-6">
      <div className="flex items-center gap-2 mb-5">
        <Users className="w-4 h-4 text-primary" />
        <h2 className="text-base font-semibold tracking-tight">{t("title")}</h2>
        {!loading && (
          <span className="text-xs text-muted-foreground ml-auto tabular-nums">
            {t("totalUsers", { count: total })}
          </span>
        )}
      </div>

      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("searchPlaceholder")}
          className="pl-9"
        />
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center gap-2 py-10 text-sm text-muted-foreground" role="status">
          <Loader2 className="w-5 h-5 animate-spin text-primary" />
          <span>{t("loading")}</span>
        </div>
      ) : users.length === 0 ? (
        <EmptyState icon={Users} title={t("noUsers")} className="min-h-0" />
      ) : (
        <>
          <div className="rounded-lg border border-border/80 divide-y divide-border/60 overflow-hidden">
            {users.map((user) => {
              const isEmperor = user.role === ROLES.EMPEROR
              const isUpdating = updatingUserId === user.id

              return (
                <div
                  key={user.id}
                  className="flex items-center gap-3 px-3 py-2.5 hover:bg-accent/50 transition-colors"
                >
                  {user.image ? (
                    <img
                      src={user.image}
                      alt=""
                      className="w-8 h-8 rounded-full shrink-0 ring-1 ring-border"
                    />
                  ) : (
                    <div className="w-8 h-8 shrink-0 rounded-full bg-primary/10 flex items-center justify-center">
                      <User2 className="w-4 h-4 text-primary" />
                    </div>
                  )}

                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">
                      {user.name || user.username || "—"}
                    </div>
                    <div className="text-xs text-muted-foreground truncate">
                      {user.email || user.username || "—"}
                    </div>
                  </div>

                  {isEmperor ? (
                    <div className="flex items-center gap-2 shrink-0">
                      <div className="flex w-[7.5rem] items-center">
                        <span className="inline-flex max-w-full items-center gap-1 text-xs font-medium bg-primary/10 text-primary ring-1 ring-inset ring-primary/15 px-2.5 py-0.5 rounded-full">
                          <Crown className="w-3 h-3 shrink-0" />
                          <span className="truncate">{roleNames[ROLES.EMPEROR]}</span>
                        </span>
                      </div>
                      <div className="h-9 w-9 sm:h-8 sm:w-8" aria-hidden="true" />
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 shrink-0">
                      <div className="relative">
                        {isUpdating && (
                          <div className="absolute inset-0 flex items-center justify-center bg-background/80 rounded-md z-10">
                            <Loader2 className="w-4 h-4 animate-spin" />
                          </div>
                        )}
                        <Select
                          value={user.role || ROLES.CIVILIAN}
                          onValueChange={(v) => handleRoleChange(user.id, v as RoleWithoutEmperor)}
                          disabled={isUpdating}
                        >
                          <SelectTrigger className="w-[7.5rem] h-9 sm:h-8 text-sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={ROLES.DUKE}>
                              <div className="flex items-center gap-1.5">
                                <Gem className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                                {roleNames[ROLES.DUKE]}
                              </div>
                            </SelectItem>
                            <SelectItem value={ROLES.KNIGHT}>
                              <div className="flex items-center gap-1.5">
                                <Sword className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                                {roleNames[ROLES.KNIGHT]}
                              </div>
                            </SelectItem>
                            <SelectItem value={ROLES.CIVILIAN}>
                              <div className="flex items-center gap-1.5">
                                <User2 className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                                {roleNames[ROLES.CIVILIAN]}
                              </div>
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9 sm:h-8 sm:w-8 text-muted-foreground hover:text-destructive"
                        onClick={() => setUserToDelete(user)}
                        title={t("deleteUser")}
                        aria-label={t("deleteUser")}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between gap-2 mt-4 pt-4 border-t border-border/60">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
              >
                <ChevronLeft className="w-4 h-4 mr-1" />
                {t("prevPage")}
              </Button>
              <span className="text-sm text-muted-foreground tabular-nums">
                {t("pageInfo", { current: page, total: totalPages })}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
              >
                {t("nextPage")}
                <ChevronRight className="w-4 h-4 ml-1" />
              </Button>
            </div>
          )}
        </>
      )}

      <AlertDialog
        open={!!userToDelete}
        onOpenChange={(open) => {
          if (!open && !deletingUserId) setUserToDelete(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("deleteConfirm", {
                name:
                  userToDelete?.name ||
                  userToDelete?.username ||
                  userToDelete?.email ||
                  "",
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={!!deletingUserId}>
              {t("cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={!!deletingUserId}
              onClick={(e) => {
                e.preventDefault()
                if (userToDelete) handleDelete(userToDelete)
              }}
            >
              {deletingUserId ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                t("deleteConfirmButton")
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
