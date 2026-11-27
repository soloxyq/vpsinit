"use client"

import { useLocaleSwitcher } from "@/hooks/use-locale-switcher"
import { LOCALE_LABELS } from "@/i18n/config"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import { Check, Languages } from "lucide-react"
import { cn } from "@/lib/utils"

export function LanguageSwitcher() {
  const { locale, locales, switchLocale } = useLocaleSwitcher()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Switch language"
          className="h-10 w-10 data-[state=open]:bg-accent data-[state=open]:text-accent-foreground sm:h-9 sm:w-9"
        >
          <Languages className="h-5 w-5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {locales.map((loc) => (
          <DropdownMenuItem
            key={loc}
            onClick={() => switchLocale(loc)}
            lang={loc}
            className={cn(locale === loc && "font-medium")}
          >
            {LOCALE_LABELS[loc]}
            <Check
              aria-hidden="true"
              className={cn(
                "ml-auto h-4 w-4 shrink-0 text-primary",
                locale === loc ? "opacity-100" : "opacity-0"
              )}
            />
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
