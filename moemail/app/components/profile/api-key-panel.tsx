"use client"

import { useState, useEffect } from "react"
import { useTranslations } from "next-intl"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Key, Plus, Loader2, Copy, Trash2, ChevronDown, ChevronUp, Lock } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { useCopy } from "@/hooks/use-copy"
import { useRolePermission } from "@/hooks/use-role-permission"
import { PERMISSIONS } from "@/lib/permissions"
import { useConfig } from "@/hooks/use-config"

type ApiKey = {
  id: string
  name: string
  key: string
  createdAt: string
  expiresAt: string | null
  enabled: boolean
}

export function ApiKeyPanel() {
  const t = useTranslations("profile.apiKey")
  const tCommon = useTranslations("common.actions")
  const tNoPermission = useTranslations("emails.noPermission")
  const tMessages = useTranslations("emails.messages")
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([])
  const [loading, setLoading] = useState(false)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [newKeyName, setNewKeyName] = useState("")
  const [newKey, setNewKey] = useState<string | null>(null)
  const { toast } = useToast()
  const { copyToClipboard } = useCopy()
  const [showExamples, setShowExamples] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const { checkPermission } = useRolePermission()
  const canManageApiKey = checkPermission(PERMISSIONS.MANAGE_API_KEY)

  const fetchApiKeys = async () => {
    try {
      const res = await fetch("/api/api-keys")
      if (!res.ok) throw new Error(t("createFailed"))
      const data = await res.json() as { apiKeys: ApiKey[] }
      setApiKeys(data.apiKeys)
    } catch (error) {
      console.error(error)
      toast({
        title: t("createFailed"),
        description: t("createFailed"),
        variant: "destructive"
      })
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    if (canManageApiKey) {
      fetchApiKeys()
    }
  }, [canManageApiKey])

  const { config } = useConfig()

  const createApiKey = async () => {
    if (!newKeyName.trim()) return

    setLoading(true)
    try {
      const res = await fetch("/api/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newKeyName })
      })

      if (!res.ok) throw new Error(t("createFailed"))

      const data = await res.json() as { key: string }
      setNewKey(data.key)
      fetchApiKeys()
    } catch (error) {
      toast({
        title: t("createFailed"),
        description: error instanceof Error ? error.message : t("createFailed"),
        variant: "destructive"
      })
      setCreateDialogOpen(false)
    } finally {
      setLoading(false)
    }
  }

  const handleDialogClose = () => {
    setCreateDialogOpen(false)
    setNewKeyName("")
    setNewKey(null)
  }

  const toggleApiKey = async (id: string, enabled: boolean) => {
    try {
      const res = await fetch(`/api/api-keys/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled })
      })

      if (!res.ok) throw new Error(t("createFailed"))

      setApiKeys(keys =>
        keys.map(key =>
          key.id === id ? { ...key, enabled } : key
        )
      )
    } catch (error) {
      console.error(error)
      toast({
        title: t("createFailed"),
        description: t("createFailed"),
        variant: "destructive"
      })
    }
  }

  const deleteApiKey = async (id: string) => {
    try {
      const res = await fetch(`/api/api-keys/${id}`, {
        method: "DELETE"
      })

      if (!res.ok) throw new Error(t("deleteFailed"))

      setApiKeys(keys => keys.filter(key => key.id !== id))
      toast({
        title: t("deleteSuccess"),
        description: t("deleteSuccess")
      })
    } catch (error) {
      console.error(error)
      toast({
        title: t("deleteFailed"),
        description: t("deleteFailed"),
        variant: "destructive"
      })
    }
  }

  return (
    <div className="bg-card rounded-xl border border-border/80 shadow-sm p-4 sm:p-6 space-y-5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Key className="w-4 h-4 shrink-0 text-primary" />
          <h2 className="text-base font-semibold tracking-tight truncate">{t("title")}</h2>
        </div>
        {
          canManageApiKey && (
            <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
              <DialogTrigger asChild>
                <Button className="gap-2 shrink-0" onClick={() => setCreateDialogOpen(true)}>
                  <Plus className="w-4 h-4" />
                  {t("create")}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>
                    {newKey ? t("createSuccess") : t("create")}
                  </DialogTitle>
                  {newKey && (
                    <DialogDescription>
                      {t("description")}
                    </DialogDescription>
                  )}
                </DialogHeader>

                {!newKey ? (
                  <div className="space-y-4 py-2">
                    <div className="space-y-2">
                      <Label>{t("name")}</Label>
                      <Input
                        value={newKeyName}
                        onChange={(e) => setNewKeyName(e.target.value)}
                        placeholder={t("namePlaceholder")}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4 py-2">
                    <div className="space-y-2">
                      <Label>{t("key")}</Label>
                      <div className="flex gap-2">
                        <Input
                          value={newKey}
                          readOnly
                          className="font-mono text-sm"
                        />
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          className="shrink-0"
                          onClick={() => copyToClipboard(newKey)}
                        >
                          <Copy className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                )}

                <DialogFooter>
                  <DialogClose asChild>
                    <Button
                      variant={newKey ? "default" : "outline"}
                      onClick={handleDialogClose}
                      disabled={loading}
                    >
                      {newKey ? tCommon("ok") : tCommon("cancel")}
                    </Button>
                  </DialogClose>
                  {!newKey && (
                    <Button
                      onClick={createApiKey}
                      disabled={loading || !newKeyName.trim()}
                    >
                      {loading ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        t("create")
                      )}
                    </Button>
                  )}
                </DialogFooter>
              </DialogContent>
            </Dialog>
          )
        }
      </div>

      {
        !canManageApiKey ? (
          <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Lock className="h-5 w-5" aria-hidden="true" />
            </div>
            <div className="space-y-1 text-sm">
              <p className="font-medium text-foreground">{tNoPermission("needPermission")}</p>
              <p className="text-muted-foreground">{tNoPermission("contactAdmin")}</p>
              {
                config?.adminContact && (
                  <p className="pt-1 text-muted-foreground">
                    {tNoPermission("adminContact")}:{" "}
                    <span className="font-mono text-foreground break-all">{config.adminContact}</span>
                  </p>
                )
              }
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {isLoading ? (
              <div className="flex flex-col items-center justify-center gap-2 py-10 text-sm text-muted-foreground" role="status">
                <Loader2 className="w-5 h-5 animate-spin text-primary" />
                <p>{tMessages("loading")}</p>
              </div>
            ) : apiKeys.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-muted/70 text-muted-foreground/70 ring-1 ring-inset ring-border/70">
                  <Key className="h-5 w-5" strokeWidth={1.75} aria-hidden="true" />
                </div>
                <div className="space-y-1">
                  <h3 className="text-sm font-medium text-foreground">{t("noKeys")}</h3>
                  <p className="max-w-sm text-sm text-muted-foreground">
                    {t("description")}
                  </p>
                </div>
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  {apiKeys.map((key) => (
                    <div
                      key={key.id}
                      className="flex items-center gap-3 p-3 rounded-lg border border-border/80 hover:bg-accent/50 transition-colors"
                    >
                      <div className="min-w-0 flex-1 space-y-0.5">
                        <div className="text-sm font-medium truncate">{key.name}</div>
                        <div className="text-xs text-muted-foreground tabular-nums truncate">
                          {t("createdAt")}: {new Date(key.createdAt).toLocaleString()}
                        </div>
                      </div>
                      <div className="shrink-0 flex items-center gap-1">
                        <Switch
                          checked={key.enabled}
                          onCheckedChange={(checked) => toggleApiKey(key.id, checked)}
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive"
                          onClick={() => deleteApiKey(key.id)}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="pt-2 space-y-2">
                  <button
                    type="button"
                    className="flex items-center gap-1 rounded-md text-sm text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                    onClick={() => setShowExamples(!showExamples)}
                    aria-expanded={showExamples}
                  >
                    {showExamples ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    {t("viewDocs")}
                  </button>

                  {showExamples && (
                    <div className="rounded-lg border border-border/80 bg-card p-3 sm:p-4 space-y-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.getConfig")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl ${window.location.protocol}//${window.location.host}/api/config \\
  -H "X-API-Key: YOUR_API_KEY"`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl ${window.location.protocol}//${window.location.host}/api/config \\
  -H "X-API-Key: YOUR_API_KEY"`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.generateEmail")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl -X POST ${window.location.protocol}//${window.location.host}/api/emails/generate \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "test",
    "expiryTime": 3600000,
    "domain": "moemail.app"
  }'`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl -X POST ${window.location.protocol}//${window.location.host}/api/emails/generate \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "test",
    "expiryTime": 3600000,
    "domain": "moemail.app"
  }'`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.getEmails")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl ${window.location.protocol}//${window.location.host}/api/emails?cursor=CURSOR \\
  -H "X-API-Key: YOUR_API_KEY"`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl ${window.location.protocol}//${window.location.host}/api/emails?cursor=CURSOR \\
  -H "X-API-Key: YOUR_API_KEY"`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.getMessages")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl ${window.location.protocol}//${window.location.host}/api/emails/{emailId}?cursor=CURSOR \\
  -H "X-API-Key: YOUR_API_KEY"`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl ${window.location.protocol}//${window.location.host}/api/emails/{emailId}?cursor=CURSOR \\
  -H "X-API-Key: YOUR_API_KEY"`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.getMessage")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/{messageId} \\
  -H "X-API-Key: YOUR_API_KEY"`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/{messageId} \\
  -H "X-API-Key: YOUR_API_KEY"`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.createEmailShare")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl -X POST ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/share \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"expiresIn": 86400000}'`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl -X POST ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/share \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"expiresIn": 86400000}'`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.getEmailShares")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/share \\
  -H "X-API-Key: YOUR_API_KEY"`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/share \\
  -H "X-API-Key: YOUR_API_KEY"`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.deleteEmailShare")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl -X DELETE ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/share/{shareId} \\
  -H "X-API-Key: YOUR_API_KEY"`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl -X DELETE ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/share/{shareId} \\
  -H "X-API-Key: YOUR_API_KEY"`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.createMessageShare")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl -X POST ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/messages/{messageId}/share \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"expiresIn": 0}'`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl -X POST ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/messages/{messageId}/share \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"expiresIn": 0}'`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.getMessageShares")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/messages/{messageId}/share \\
  -H "X-API-Key: YOUR_API_KEY"`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/messages/{messageId}/share \\
  -H "X-API-Key: YOUR_API_KEY"`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm font-medium">{t("docs.deleteMessageShare")}</div>
                        <div className="relative">
                          <pre className="font-mono text-xs bg-muted/60 border border-border/60 rounded-lg p-3.5 pr-10 overflow-x-auto">
                            {`curl -X DELETE ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/messages/{messageId}/share/{shareId} \\
  -H "X-API-Key: YOUR_API_KEY"`}
                          </pre>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => copyToClipboard(
                              `curl -X DELETE ${window.location.protocol}//${window.location.host}/api/emails/{emailId}/messages/{messageId}/share/{shareId} \\
  -H "X-API-Key: YOUR_API_KEY"`
                            )}
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="text-xs text-muted-foreground mt-4">
                        <p>{t("docs.notes")}</p>
                        <ul className="list-disc list-inside space-y-1 mt-2">
                          <li>{t("docs.note1")}</li>
                          <li>{t("docs.note2")}</li>
                          <li>{t("docs.note3")}</li>
                          <li>{t("docs.note4")}</li>
                          <li>{t("docs.note5")}</li>
                          <li>{t("docs.note6")}</li>
                          <li>{t("docs.note7")}</li>
                          <li>{t("docs.note8")}</li>
                          <li>{t("docs.note9")}</li>
                          <li>{t("docs.note10")}</li>
                        </ul>
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        )
      }
    </div>
  )
} 