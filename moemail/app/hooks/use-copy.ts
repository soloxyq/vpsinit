"use client"

import { useCallback } from "react"
import { useTranslations } from "next-intl"
import { useToast } from "@/components/ui/use-toast"

interface UseCopyOptions {
  successMessage?: string
  errorMessage?: string
}

export function useCopy(options: UseCopyOptions = {}) {
  const { toast } = useToast()
  const t = useTranslations("common.copy")
  const successMessage = options.successMessage ?? t("success")
  const errorMessage = options.errorMessage ?? t("failed")
  const successTitle = t("successTitle")
  const errorTitle = t("errorTitle")

  const copyToClipboard = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast({
        title: successTitle,
        description: successMessage
      })
      return true
    } catch {
      toast({
        title: errorTitle,
        description: errorMessage,
        variant: "destructive"
      })
      return false
    }
  }, [successTitle, successMessage, errorTitle, errorMessage, toast])

  return {
    copyToClipboard
  }
}