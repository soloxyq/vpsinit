"use client"

import { useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Loader2, Mail } from "lucide-react"
import { useTranslations, useLocale } from "next-intl"
import { cn } from "@/lib/utils"
import { SignButton } from "../auth/sign-button"

interface ActionButtonProps {
  isLoggedIn?: boolean
}

export function ActionButton({ isLoggedIn }: ActionButtonProps) {
  const locale = useLocale()
  const t = useTranslations("home")
  const [navigating, setNavigating] = useState(false)

  if (isLoggedIn) {
    return (
      <Button
        asChild
        size="lg"
        className={cn("gap-2 px-7 shadow-sm", navigating && "pointer-events-none opacity-80")}
      >
        <Link
          href={`/${locale}/moe`}
          onClick={(e) => {
            if (!e.defaultPrevented && e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) {
              setNavigating(true)
            }
          }}
        >
          {navigating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
          {t("actions.enterMailbox")}
        </Link>
      </Button>
    )
  }

  return <SignButton size="lg" />
} 