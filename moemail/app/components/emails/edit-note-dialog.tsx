"use client"

import { useEffect, useState } from "react"
import { useTranslations } from "next-intl"
import { Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { useToast } from "@/components/ui/use-toast"
import { EMAIL_CONFIG } from "@/config"

interface EditNoteDialogProps {
  emailId: string
  emailAddress: string
  initialNote?: string | null
  triggerClassName?: string
  onNoteUpdated: (emailId: string, note: string | null) => void
}

export function EditNoteDialog({
  emailId,
  emailAddress,
  initialNote,
  triggerClassName,
  onNoteUpdated,
}: EditNoteDialogProps) {
  const tList = useTranslations("emails.list")
  const tCommon = useTranslations("common.actions")
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState(initialNote ?? "")
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  useEffect(() => {
    if (open) {
      setNote(initialNote ?? "")
    }
  }, [open, initialNote, emailId])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      const response = await fetch(`/api/emails/${emailId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: note.trim() || null }),
      })

      if (!response.ok) {
        const data = (await response.json().catch(() => ({}))) as { error?: string }
        toast({
          title: tList("error"),
          description: data.error || tList("noteSaveFailed"),
          variant: "destructive",
        })
        return
      }

      const data = (await response.json()) as { note: string | null }
      onNoteUpdated(emailId, data.note)
      toast({
        title: tList("success"),
        description: tList("noteSaveSuccess"),
      })
      setOpen(false)
    } catch {
      toast({
        title: tList("error"),
        description: tList("noteSaveFailed"),
        variant: "destructive",
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          className={triggerClassName}
          title={tList("editNote")}
          aria-label={tList("editNote")}
        >
          <Pencil className="size-3.5" />
        </button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{tList("editNote")}</DialogTitle>
          <DialogDescription className="font-mono text-xs break-all">
            {emailAddress}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSave} className="space-y-4">
          <div className="py-2">
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={tList("notePlaceholder")}
              maxLength={EMAIL_CONFIG.MAX_NOTE_LENGTH}
              disabled={saving}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={saving}
            >
              {tCommon("cancel")}
            </Button>
            <Button type="submit" disabled={saving}>
              {tCommon("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
