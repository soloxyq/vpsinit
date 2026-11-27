"use client"

import { useTranslations } from "next-intl"
import { usePathname } from "next/navigation"
import { Github } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export function FloatMenu() {
  const t = useTranslations("common")
  const pathname = usePathname()
  
  // 在分享页面和邮箱页面隐藏GitHub悬浮框
  if (pathname.includes("/shared/") || pathname.includes("/moe")) {
    return null
  }
  
  return (
    <div className="fixed bottom-4 right-4 z-50 sm:bottom-6 sm:right-6">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              className="h-10 w-10 sm:h-9 sm:w-9 bg-card/90 backdrop-blur-md rounded-full shadow-md group relative border-border/80 text-muted-foreground hover:text-foreground hover:border-border"
              onClick={() => window.open("https://github.com/beilunyang/moemail", "_blank")}
            >
              <Github
                className="w-4 h-4 transition-transform duration-200 group-hover:scale-105"
              />
              <span className="sr-only">{t("github")}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left" sideOffset={8}>
            <p>{t("github")}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  )
} 