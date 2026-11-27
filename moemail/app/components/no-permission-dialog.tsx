"use client"

import { Button } from "@/components/ui/button"
import { Lock } from "lucide-react"
import { useRouter } from "next/navigation"
import { useTranslations, useLocale } from "next-intl"
import { useConfig } from "@/hooks/use-config"

export function NoPermissionDialog() {
  const router = useRouter()
  const locale = useLocale()
  const t = useTranslations("emails.noPermission")
  const { config } = useConfig()

  return (
    <div className="fixed inset-x-0 top-16 bottom-0 bg-background/60 backdrop-blur-md z-40">
      <div className="fixed left-[50%] top-[50%] translate-x-[-50%] translate-y-[-50%] w-[90%] max-w-md">
        <div role="dialog" aria-modal="true" className="bg-card border border-border/80 rounded-2xl p-6 md:p-10 shadow-xl">
          <div className="text-center space-y-4">
            <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
              <Lock className="h-5 w-5" aria-hidden="true" />
            </div>
            <h1 className="text-xl font-semibold tracking-tight">{t("title")}</h1>
            <p className="text-sm md:text-base text-muted-foreground">{t("description")}</p>
            {
              config?.adminContact && (
                <p className="text-sm md:text-base text-muted-foreground">{t("adminContact")}：<span className="font-mono text-foreground/80 break-all">{config.adminContact}</span></p>
              )
            }
            <div className="pt-2">
              <Button
                onClick={() => router.push(`/${locale}`)}
                className="w-full md:w-auto"
              >
                {t("backToHome")}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
} 