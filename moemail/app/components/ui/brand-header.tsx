"use client"

import Link from "next/link"
import { useTranslations } from "next-intl"
import { Button } from "@/components/ui/button"
import { ExternalLink, Mail } from "lucide-react"
import { cn } from "@/lib/utils"

interface BrandHeaderProps {
  title?: string
  subtitle?: string
  ctaText?: string
  monoTitle?: boolean
}

export function BrandHeader({
  title,
  subtitle,
  ctaText,
  monoTitle = true,
}: BrandHeaderProps) {
  const t = useTranslations("emails.shared.brand")

  const displayTitle = title || t("title")
  const displaySubtitle = subtitle || t("subtitle")
  const displayCtaText = ctaText || t("cta")
  return (
    <div className="text-center space-y-3 lg:space-y-4 lg:pb-2">
      <div className="flex justify-center pt-2">
        <Link
          href="https://moemail.app"
          className="flex items-center gap-3 hover:opacity-85 transition-opacity group"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-inset ring-primary/20 transition-transform duration-200 group-hover:scale-105">
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <rect
                x="2.5"
                y="4.5"
                width="19"
                height="15"
                rx="3"
                className="stroke-current"
                strokeWidth="1.8"
              />
              <path
                d="M3.5 6.5L11.1 12.2C11.63 12.6 12.37 12.6 12.9 12.2L20.5 6.5"
                className="stroke-current"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <span className="text-xl font-semibold tracking-tight text-foreground">
            MoeMail
          </span>
        </Link>
      </div>

      <div className="space-y-1.5">
        <h1
          className={cn(
            "text-xl md:text-2xl font-semibold tracking-tight text-foreground",
            monoTitle ? "font-mono break-all sm:break-normal" : "break-words"
          )}
        >
          {displayTitle}
        </h1>
        <p
          className="text-sm text-muted-foreground max-w-md mx-auto tabular-nums"
          suppressHydrationWarning
        >
          {displaySubtitle}
        </p>
      </div>

      <div className="flex justify-center">
        <Button
          asChild
          size="default"
          className="gap-2 px-5"
        >
          <Link href="/" target="_blank" rel="noopener noreferrer">
            <Mail className="w-4 h-4" />
            {displayCtaText}
            <ExternalLink className="w-3.5 h-3.5 opacity-80" />
          </Link>
        </Button>
      </div>
    </div>
  )
}
