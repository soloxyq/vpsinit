/* eslint-disable @typescript-eslint/no-unused-vars */
"use client"

import { useState, useEffect } from "react"
import { useTranslations } from "next-intl"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useToast } from "@/components/ui/use-toast"
import { Loader2, Send, ChevronDown, ChevronUp } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export function WebhookConfig() {
  const t = useTranslations("profile.webhook")
  const tCommon = useTranslations("common.actions")
  const tMessages = useTranslations("emails.messages")
  const tApiKey = useTranslations("profile.apiKey")
  const [enabled, setEnabled] = useState(false)
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(false)
  const [testing, setTesting] = useState(false)
  const [showDocs, setShowDocs] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const { toast } = useToast()

  useEffect(() => {
    fetch("/api/webhook")
      .then(res => res.json() as Promise<{ enabled: boolean; url: string }>)
      .then(data => {
        setEnabled(data.enabled)
        setUrl(data.url)
      })
      .catch(console.error)
      .finally(() => setInitialLoading(false))
  }, [])

  if (initialLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10 text-sm text-muted-foreground" role="status">
        <Loader2 className="w-5 h-5 animate-spin text-primary" />
        <p>{tMessages("loading")}</p>
      </div>
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (enabled && !url.trim()) return

    setLoading(true)
    try {
      const res = await fetch("/api/webhook", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), enabled })
      })

      if (!res.ok) throw new Error(t("saveFailed"))

      toast({
        title: t("saveSuccess"),
        description: t("saveSuccess")
      })
    } catch (_error) {
      toast({
        title: t("saveFailed"),
        description: t("saveFailed"),
        variant: "destructive"
      })
    } finally {
      setLoading(false)
    }
  }

  const handleTest = async () => {
    if (!url) return

    setTesting(true)
    try {
      const res = await fetch("/api/webhook/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url })
      })

      if (!res.ok) throw new Error(t("testFailed"))

      toast({
        title: t("testSuccess"),
        description: t("testSuccess")
      })
    } catch (_error) {
      toast({
        title: t("testFailed"),
        description: t("testFailed"),
        variant: "destructive"
      })
    } finally {
      setTesting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-0.5 min-w-0">
          <Label>{t("enable")}</Label>
          <div className="text-sm text-muted-foreground">
            {t("description")}
          </div>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={setEnabled}
        />
      </div>

      {enabled && (
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="webhook-url">{t("url")}</Label>
            <div className="flex flex-col sm:flex-row gap-2">
              <Input
                id="webhook-url"
                placeholder={t("urlPlaceholder")}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                type="url"
                required={enabled}
              />
              <div className="flex gap-2 sm:shrink-0">
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={handleTest}
                        disabled={testing || !url}
                        className="shrink-0"
                        aria-label={t("test")}
                      >
                        {testing ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Send className="w-4 h-4" />
                        )}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{t("test")}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              {t("description2")}
            </p>
          </div>

          <div className="space-y-2">
            <button
              type="button"
              className="flex items-center gap-1 rounded-md text-sm text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              onClick={() => setShowDocs(!showDocs)}
              aria-expanded={showDocs}
            >
              {showDocs ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              {t("description3")}
            </button>

            {showDocs && (
              <div className="rounded-lg border border-border/80 bg-card p-3 sm:p-4 text-sm space-y-4">
                <p className="text-muted-foreground">{t("docs.intro")}</p>
                <pre className="relative font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 overflow-x-auto">
                  Content-Type: application/json{'\n'}
                  X-Webhook-Event: new_message
                </pre>

                <p className="text-muted-foreground">{t("docs.exampleBody")}</p>
                <pre className="relative font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 overflow-x-auto">
                  {`{
  "emailId": "email-uuid",
  "messageId": "message-uuid",
  "fromAddress": "sender@example.com",
  "subject": "${t("docs.subject")}",
  "content": "${t("docs.content")}",
  "html": "${t("docs.html")}",
  "receivedAt": "2024-01-01T12:00:00.000Z",
  "toAddress": "your-email@${window.location.host}"
}`}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="flex justify-end border-t border-border/60 pt-4 mt-2">
        <Button type="submit" disabled={loading || (enabled && !url.trim())} className="w-full sm:w-auto sm:min-w-[7rem] gap-2">
          {loading && <Loader2 className="w-4 h-4 animate-spin" />}
          {tCommon("save")}
        </Button>
      </div>
    </form>
  )
} 