"use client"

import { useTranslations } from "next-intl"
import { AlertCircle } from "lucide-react"
import { Card } from "@/components/ui/card"
import { BrandHeader } from "@/components/ui/brand-header"
import { FloatingLanguageSwitcher } from "@/components/layout/floating-language-switcher"

interface SharedErrorPageProps {
  titleKey: string
  subtitleKey: string
  errorKey: string
  descriptionKey: string
  ctaTextKey: string
}

export function SharedErrorPage({
  titleKey,
  subtitleKey,
  errorKey,
  descriptionKey,
  ctaTextKey,
}: SharedErrorPageProps) {
  const tShared = useTranslations("emails.shared")

  const resolvedTitle = tShared(titleKey)
  const resolvedSubtitle = tShared(subtitleKey)
  const resolvedError = tShared(errorKey)
  const resolvedDescription = tShared(descriptionKey)
  const resolvedCtaText = tShared(ctaTextKey)

  return (
    <div className="min-h-screen bg-page flex flex-col justify-center items-center">
      <div className="container mx-auto p-4 max-w-4xl">
        <BrandHeader
          title={resolvedTitle}
          subtitle={resolvedSubtitle}
          ctaText={resolvedCtaText}
          monoTitle={false}
        />
        <div className="text-center mt-6">
          <Card className="max-w-md mx-auto p-6 sm:p-8 text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center mx-auto">
              <AlertCircle className="w-6 h-6 text-destructive" aria-hidden="true" />
            </div>
            <h2 className="text-lg font-semibold tracking-tight">{resolvedError}</h2>
            <p className="text-sm text-muted-foreground">
              {resolvedDescription}
            </p>
          </Card>
        </div>
      </div>

      <FloatingLanguageSwitcher />
    </div>
  )
}
