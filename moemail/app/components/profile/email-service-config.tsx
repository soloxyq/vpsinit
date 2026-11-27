"use client"

import React, { useState, useEffect } from "react"
import { useTranslations } from "next-intl"
import { Button } from "@/components/ui/button"
import { Zap, Eye, EyeOff, Gem, Sword, Loader2 } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"

interface EmailServiceConfig {
  enabled: boolean
  apiKey: string
  roleLimits: {
    duke: number
    knight: number
  }
}

export function EmailServiceConfig() {
  const t = useTranslations("profile.emailService")
  const tCard = useTranslations("profile.card")
  const tSend = useTranslations("emails.send")
  const [config, setConfig] = useState<EmailServiceConfig>({
    enabled: false,
    apiKey: "",
    roleLimits: {
      duke: -1,
      knight: -1,
    }
  })
  const [loading, setLoading] = useState(false)
  const [showToken, setShowToken] = useState(false)
  const { toast } = useToast()

  useEffect(() => {
    fetchConfig()
  }, [])

  const fetchConfig = async () => {
    try {
      const res = await fetch("/api/config/email-service")
      if (res.ok) {
        const data = await res.json() as EmailServiceConfig
        setConfig(data)
      }
    } catch (error) {
      console.error("Failed to fetch email service config:", error)
    }
  }

  const handleSave = async () => {
    setLoading(true)
    try {
      const saveData = {
        enabled: config.enabled,
        apiKey: config.apiKey,
        roleLimits: config.roleLimits
      }

      const res = await fetch("/api/config/email-service", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(saveData),
      })

      if (!res.ok) {
        const error = await res.json() as { error: string }
        throw new Error(error.error || t("saveFailed"))
      }

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
        <Zap className="w-4 h-4 text-primary" />
        <h2 className="text-base font-semibold tracking-tight">{t("title")}</h2>
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-0.5 min-w-0">
            <Label htmlFor="enabled" className="text-sm font-medium">
              {t("enable")}
            </Label>
            <p className="text-xs text-muted-foreground">
              {t("enableDescription")}
            </p>
          </div>
          <Switch
            id="enabled"
            checked={config.enabled}
            onCheckedChange={(checked: boolean) =>
              setConfig((prev: EmailServiceConfig) => ({ ...prev, enabled: checked }))
            }
          />
        </div>

        {config.enabled && (
          <>
            <div className="space-y-2">
              <Label htmlFor="apiKey" className="text-sm font-medium">
                {t("apiKey")}
              </Label>
              <div className="relative">
                <Input
                  id="apiKey"
                  type={showToken ? "text" : "password"}
                  value={config.apiKey}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setConfig((prev: EmailServiceConfig) => ({ ...prev, apiKey: e.target.value }))}
                  placeholder={t("apiKeyPlaceholder")}
                  className="pr-10 font-mono"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="absolute right-0 top-0 h-full w-10 px-0 text-muted-foreground hover:text-foreground hover:bg-transparent"
                  onClick={() => setShowToken(!showToken)}
                >
                  {showToken ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-medium">
                {t("roleLimits")}
              </Label>
              <div className="space-y-4">
                <div className="p-3 sm:p-4 bg-primary/[0.04] border border-primary/15 rounded-xl text-sm">
                  <div className="font-medium text-foreground mb-2.5 flex items-center gap-2">
                    <div className="w-1.5 h-1.5 shrink-0 bg-primary/60 rounded-full"></div>
                    {t("fixedRoleLimits")}
                  </div>
                  <div className="space-y-1.5 text-muted-foreground text-xs">
                    <div className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 shrink-0 bg-muted-foreground/50 rounded-full"></div>
                      <span><strong className="text-foreground">{tCard("roles.EMPEROR")}</strong> - {t("emperorLimit")}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 shrink-0 bg-muted-foreground/50 rounded-full"></div>
                      <span><strong className="text-foreground">{tCard("roles.CIVILIAN")}</strong> - {t("civilianLimit")}</span>
                    </div>
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <div className="w-1.5 h-1.5 shrink-0 bg-primary/60 rounded-full"></div>
                    <p className="text-sm font-medium text-foreground">{t("configRoleLabel")}</p>
                  </div>
                  {[
                    { value: "duke", label: tCard("roles.DUKE"), key: "duke" as const },
                    { value: "knight", label: tCard("roles.KNIGHT"), key: "knight" as const }
                  ].map((role) => {
                    const isDisabled = config.roleLimits[role.key] === -1
                    const isEnabled = !isDisabled

                    return (
                      <div
                        key={role.value}
                        className={`group relative p-3 sm:p-4 border rounded-xl transition-colors duration-150 ${
                          isEnabled
                            ? 'border-primary/30 bg-primary/[0.04]'
                            : 'border-border/80 hover:border-border bg-muted/20'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-3 min-w-0">
                            <div className="relative shrink-0">
                              <Checkbox
                                id={`role-${role.value}`}
                                checked={isEnabled}
                                onChange={(checked: boolean) => {
                                  setConfig((prev: EmailServiceConfig) => ({
                                    ...prev,
                                    roleLimits: {
                                      ...prev.roleLimits,
                                      [role.key]: checked ? 0 : -1
                                    }
                                  }))
                                }}
                              />
                            </div>
                            <div className="min-w-0">
                              <Label 
                                htmlFor={`role-${role.value}`} 
                                className="text-sm font-medium cursor-pointer select-none flex items-center gap-1.5"
                              >
                                {role.value === 'duke' ? (
                                  <Gem className="w-4 h-4 shrink-0 text-primary" />
                                ) : (
                                  <Sword className="w-4 h-4 shrink-0 text-primary" />
                                )}
                                <span className="truncate">{role.label}</span>
                              </Label>
                              <p className="text-xs text-muted-foreground mt-1">
                                {isEnabled ? t("enabled") : t("disabled")}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center shrink-0">
                            <div className="text-right">
                              <Label className="text-xs font-medium text-muted-foreground block mb-1">{t("dailyLimit")}</Label>
                              <div className="flex items-center gap-2">
                                <Input
                                  type="number"
                                  min="-1"
                                  value={config.roleLimits[role.key]}
                                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => 
                                    setConfig((prev: EmailServiceConfig) => ({
                                      ...prev,
                                      roleLimits: {
                                        ...prev.roleLimits,
                                        [role.key]: parseInt(e.target.value) || 0
                                      }
                                    }))
                                  }
                                  className="w-20 h-9 text-center font-medium tabular-nums"
                                  placeholder="0"
                                  disabled={isDisabled}
                                />
                                <span className="text-xs text-muted-foreground whitespace-nowrap">{tSend("dailyLimitUnit")}</span>
                              </div>
                              <p className="text-xs text-muted-foreground mt-1">0 = {t("unlimited")}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </>
        )}

        <div className="flex justify-end border-t border-border/60 pt-4 mt-2">
          <Button
            onClick={handleSave}
            disabled={loading}
            className="w-full sm:w-auto sm:min-w-[7rem] gap-2"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {loading ? t("saving") : t("save")}
          </Button>
        </div>
      </div>
    </div>
  )
} 