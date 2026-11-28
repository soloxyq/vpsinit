"use client"

import { useTranslations } from "next-intl"
import { Button } from "@/components/ui/button"
import { SlidersHorizontal, Loader2, Eye, EyeOff } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"
import { useState, useEffect } from "react"
import { Role, ROLES } from "@/lib/permissions"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { EMAIL_CONFIG } from "@/config"
import { refreshCachedConfig } from "@/hooks/use-config"

export function WebsiteConfigPanel() {
  const t = useTranslations("profile.website")
  const tCard = useTranslations("profile.card")
  const [defaultRole, setDefaultRole] = useState<string>("")
  const [emailDomains, setEmailDomains] = useState<string>("")
  const [adminContact, setAdminContact] = useState<string>("")
  const [maxEmails, setMaxEmails] = useState<string>(EMAIL_CONFIG.MAX_ACTIVE_EMAILS.toString())
  const [allowRegistration, setAllowRegistration] = useState(true)
  const [turnstileEnabled, setTurnstileEnabled] = useState(false)
  const [turnstileSiteKey, setTurnstileSiteKey] = useState("")
  const [turnstileSecretKey, setTurnstileSecretKey] = useState("")
  const [showSecretKey, setShowSecretKey] = useState(false)
  const [loading, setLoading] = useState(false)
  const { toast } = useToast()


  useEffect(() => {
    fetchConfig()
  }, [])

  const fetchConfig = async () => {
    const res = await fetch("/api/config")
    if (res.ok) {
      const data = await res.json() as { 
        defaultRole: Exclude<Role, typeof ROLES.EMPEROR>,
        emailDomains: string,
        adminContact: string,
        maxEmails: string,
        allowRegistration?: boolean,
        turnstile?: {
          enabled: boolean,
          siteKey: string,
          secretKey?: string
        }
      }
      setDefaultRole(data.defaultRole)
      setEmailDomains(data.emailDomains)
      setAdminContact(data.adminContact)
      setMaxEmails(data.maxEmails || EMAIL_CONFIG.MAX_ACTIVE_EMAILS.toString())
      setAllowRegistration(data.allowRegistration ?? true)
      setTurnstileEnabled(Boolean(data.turnstile?.enabled))
      setTurnstileSiteKey(data.turnstile?.siteKey ?? "")
      setTurnstileSecretKey(data.turnstile?.secretKey ?? "")
    }
  }

  const handleSave = async () => {
    setLoading(true)
    try {
      const normalizedDomains = emailDomains
        .split(",")
        .map((d) => d.trim())
        .filter(Boolean)
        .join(",")
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          defaultRole, 
          emailDomains: normalizedDomains,
          adminContact,
          maxEmails: maxEmails || EMAIL_CONFIG.MAX_ACTIVE_EMAILS.toString(),
          allowRegistration,
          turnstile: {
            enabled: turnstileEnabled,
            siteKey: turnstileSiteKey,
            secretKey: turnstileSecretKey
          }
        }),
      })

      if (!res.ok) {
        const errData = (await res.json().catch(() => ({}))) as { error?: string }
        throw new Error(errData.error || t("saveFailed"))
      }

      setEmailDomains(normalizedDomains)
      await refreshCachedConfig()

      toast({
        title: t("saveSuccess"),
        description: t("saveSuccess"),
      })
    } catch (error) {
      toast({
        title: t("saveFailed"),
        description: error instanceof Error ? error.message : t("saveFailed"),
        variant: "destructive",
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-card rounded-xl border border-border/80 shadow-sm p-4 sm:p-6">
      <div className="flex items-center gap-2 mb-5">
        <SlidersHorizontal className="w-4 h-4 text-primary" />
        <h2 className="text-base font-semibold tracking-tight">{t("title")}</h2>
      </div>

      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="cfg-default-role" className="text-sm font-medium">
            {t("defaultRole")}
          </Label>
          <Select value={defaultRole} onValueChange={setDefaultRole}>
            <SelectTrigger id="cfg-default-role" className="w-full sm:w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ROLES.DUKE}>{tCard("roles.DUKE")}</SelectItem>
              <SelectItem value={ROLES.KNIGHT}>{tCard("roles.KNIGHT")}</SelectItem>
              <SelectItem value={ROLES.CIVILIAN}>{tCard("roles.CIVILIAN")}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="cfg-email-domains" className="text-sm font-medium">
            {t("emailDomains")}
          </Label>
          <Input
            id="cfg-email-domains"
            value={emailDomains}
            onChange={(e) => setEmailDomains(e.target.value)}
            placeholder={t("emailDomainsPlaceholder")}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="cfg-admin-contact" className="text-sm font-medium">
            {t("adminContact")}
          </Label>
          <Input
            id="cfg-admin-contact"
            value={adminContact}
            onChange={(e) => setAdminContact(e.target.value)}
            placeholder={t("adminContactPlaceholder")}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="cfg-max-emails" className="text-sm font-medium">
            {t("maxEmails")}
          </Label>
          <Input
            id="cfg-max-emails"
            type="number"
            min="1"
            max="100"
            value={maxEmails}
            onChange={(e) => setMaxEmails(e.target.value)}
            placeholder={`${EMAIL_CONFIG.MAX_ACTIVE_EMAILS}`}
            className="tabular-nums sm:max-w-[10rem]"
          />
        </div>

        <div className="flex items-center justify-between gap-4">
          <div className="space-y-1 min-w-0">
            <Label htmlFor="allow-registration" className="text-sm font-medium">
              {t("allowRegistration")}
            </Label>
            <p className="text-xs text-muted-foreground">
              {t("allowRegistrationDescription")}
            </p>
          </div>
          <Switch
            id="allow-registration"
            checked={allowRegistration}
            onCheckedChange={setAllowRegistration}
          />
        </div>

        <div className="space-y-4 rounded-xl border border-dashed border-border bg-muted/20 p-3 sm:p-4">
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-1 min-w-0">
              <Label htmlFor="turnstile-enabled" className="text-sm font-medium">
                {t("turnstile.enable")}
              </Label>
              <p className="text-xs text-muted-foreground">
                {t("turnstile.enableDescription")}
              </p>
            </div>
            <Switch
              id="turnstile-enabled"
              checked={turnstileEnabled}
              onCheckedChange={setTurnstileEnabled}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="turnstile-site-key" className="text-sm font-medium">
              {t("turnstile.siteKey")}
            </Label>
            <Input
              id="turnstile-site-key"
              value={turnstileSiteKey}
              onChange={(e) => setTurnstileSiteKey(e.target.value)}
              placeholder={t("turnstile.siteKeyPlaceholder")}
              className="font-mono"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="turnstile-secret-key" className="text-sm font-medium">
              {t("turnstile.secretKey")}
            </Label>
            <div className="relative">
              <Input
                id="turnstile-secret-key"
                type={showSecretKey ? "text" : "password"}
                value={turnstileSecretKey}
                onChange={(e) => setTurnstileSecretKey(e.target.value)}
                placeholder={t("turnstile.secretKeyPlaceholder")}
                className="pr-10 font-mono"
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="absolute right-0 top-0 h-full w-10 px-0 text-muted-foreground hover:text-foreground hover:bg-transparent"
                onClick={() => setShowSecretKey((prev) => !prev)}
              >
                {showSecretKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {t("turnstile.secretKeyDescription")}
            </p>
          </div>
        </div>

        <div className="flex justify-end border-t border-border/60 pt-4 mt-2">
          <Button
            onClick={handleSave}
            disabled={loading}
            className="w-full sm:w-auto sm:min-w-[7rem] gap-2"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {t("save")}
          </Button>
        </div>
      </div>
    </div>
  )
} 
