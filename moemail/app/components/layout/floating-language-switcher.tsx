"use client"

import { useLocaleSwitcher } from "@/hooks/use-locale-switcher"
import { LOCALE_LABELS } from "@/i18n/config"
import { Button } from "@/components/ui/button"
import { Check, Languages } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export function FloatingLanguageSwitcher() {
  const { locale, locales, switchLocale } = useLocaleSwitcher()

  return (
    <div className="fixed bottom-4 right-4 z-50 sm:bottom-6 sm:right-6">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="icon"
            className="h-10 w-10 sm:h-9 sm:w-9 bg-card/90 backdrop-blur-md rounded-full shadow-md group relative border-border/80 text-muted-foreground hover:text-foreground hover:border-border transition-colors"
            aria-label="Switch language"
          >
            <Languages className="h-4 w-4 transition-transform duration-200 group-hover:scale-105" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" side="top" className="mb-2">
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
    </div>
  )
}
