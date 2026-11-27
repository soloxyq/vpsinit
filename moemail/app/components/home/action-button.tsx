"use client"

import { Button } from "@/components/ui/button"
import { Mail } from "lucide-react"
import { useRouter } from "next/navigation"
import { useTranslations, useLocale } from "next-intl"
import { SignButton } from "../auth/sign-button"

interface ActionButtonProps {
  isLoggedIn?: boolean
}

export function ActionButton({ isLoggedIn }: ActionButtonProps) {
  const router = useRouter()
  const locale = useLocale()
  const t = useTranslations("home")

  if (isLoggedIn) {
    return (
      <Button
        size="lg"
        onClick={() => router.push(`/${locale}/moe`)}
        className="gap-2 px-7 shadow-sm"
      >
        <Mail className="w-4 h-4" />
        {t("actions.enterMailbox")}
      </Button>
    )
  }

  return <SignButton size="lg" />
} 