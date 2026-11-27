"use client"

import { useState } from "react"
import { useLocale, useTranslations } from "next-intl"
import { signOut } from "next-auth/react"
import { KeyRound, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useToast } from "@/components/ui/use-toast"

// 修改自己的密码：先输当前密码，新密码至少 8 位（和注册时的规则一样），再输一遍确认
export function PasswordPanel() {
  const t = useTranslations("profile.password")
  const locale = useLocale()
  const { toast } = useToast()
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (newPassword.length < 8) {
      toast({ title: t("tooShort"), variant: "destructive" })
      return
    }
    if (newPassword !== confirmPassword) {
      toast({ title: t("mismatch"), variant: "destructive" })
      return
    }

    setSaving(true)
    try {
      const response = await fetch("/api/account/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currentPassword, newPassword }),
      })
      if (!response.ok) {
        // 长度和两次输入是否一致已经在这里检查过，接口回 400 就是当前密码不对
        toast({
          title: t("failed"),
          description: response.status === 400 ? t("wrongCurrent") : undefined,
          variant: "destructive",
        })
        return
      }
      // 改密码后所有已登录的会话都会失效（见 app/lib/auth.ts 的 jwt 回调），这里直接退出，用新密码重新登录
      toast({ title: t("success") })
      setTimeout(() => signOut({ callbackUrl: `/${locale}/login` }), 1500)
    } catch {
      toast({ title: t("failed"), variant: "destructive" })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-card rounded-xl border border-border/80 shadow-sm p-4 sm:p-6">
      <div className="flex items-center gap-2 mb-5">
        <KeyRound className="w-4 h-4 text-primary" />
        <h2 className="text-base font-semibold tracking-tight">{t("title")}</h2>
      </div>
      <form onSubmit={handleSubmit} className="space-y-4 max-w-md">
        <div className="space-y-2">
          <Label htmlFor="current-password">{t("current")}</Label>
          <Input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-password">{t("new")}</Label>
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="confirm-password">{t("confirm")}</Label>
          <Input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
          />
        </div>
        <Button type="submit" disabled={saving} className="min-w-[6rem]">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : t("submit")}
        </Button>
      </form>
    </div>
  )
}
