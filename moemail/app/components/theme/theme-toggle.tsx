"use client"

import { Moon, Sun } from "lucide-react"
import { useTheme } from "next-themes"
import { Button } from "@/components/ui/button"

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()

  return (
    <Button
      variant="ghost"
      size="icon"
      // 按实际显示的主题切换：默认“跟随系统”时 theme 是 "system"，按它判断第一下会切到同一个主题，看起来没反应
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      className="relative h-10 w-10 sm:h-9 sm:w-9"
    >
      <Sun className="h-5 w-5 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute h-5 w-5 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
      <span className="sr-only">切换主题</span>
    </Button>
  )
} 