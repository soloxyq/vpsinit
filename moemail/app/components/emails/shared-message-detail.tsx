"use client"

import { useState, useEffect, useRef } from "react"
import { Loader2, Mail } from "lucide-react"
import { EmptyState } from "@/components/ui/empty-state"
import { Segmented, SegmentedItem } from "@/components/ui/segmented"
import { useTheme } from "next-themes"
import { useMounted } from "@/hooks/use-mounted"

interface MessageDetail {
  id: string
  from_address?: string
  to_address?: string
  subject: string
  content?: string
  html?: string
  received_at?: number
  sent_at?: number
}

interface SharedMessageDetailProps {
  message: MessageDetail | null
  loading?: boolean
  t: {
    messageContent: string
    selectMessage: string
    loading: string
    from: string
    to: string
    subject: string
    time: string
    htmlFormat: string
    textFormat: string
  }
}

type ViewMode = "html" | "text"

export function SharedMessageDetail({
  message,
  loading = false,
  t,
}: SharedMessageDetailProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("html")
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === "dark"
  const mounted = useMounted()

  // 如果没有HTML内容，默认显示文本
  useEffect(() => {
    if (message) {
      if (!message.html && message.content) {
        setViewMode("text")
      } else if (message.html) {
        setViewMode("html")
      }
    }
  }, [message])

  const updateIframeContent = () => {
    if (viewMode === "html" && message?.html && iframeRef.current) {
      const iframe = iframeRef.current
      const doc = iframe.contentDocument || iframe.contentWindow?.document

      if (doc) {
        doc.open()
        doc.write(`
          <!DOCTYPE html>
          <html>
            <head>
              <base target="_blank">
              <style>
                html, body {
                  margin: 0;
                  padding: 0;
                  min-height: 100%;
                  font-family: Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
                  font-size: 14px;
                  line-height: 1.65;
                  color: ${isDark ? "#e5e7eb" : "#151923"};
                  background: ${isDark ? "#16191f" : "#ffffff"};
                }
                body {
                  padding: 20px;
                }
                @media (max-width: 480px) {
                  body {
                    padding: 16px;
                  }
                }
                img {
                  max-width: 100%;
                  height: auto;
                }
                a {
                  color: ${isDark ? "#818cf8" : "#4f46e5"};
                }
                html.paper {
                  background: #16191f;
                  height: 100%;
                }
                .paper body {
                  background: #ffffff;
                  color: #151923;
                  margin: 12px;
                  border-radius: 8px;
                  min-height: calc(100% - 24px);
                  box-sizing: border-box;
                  overflow-x: auto;
                }
                .paper a {
                  color: #4f46e5;
                }
                ::-webkit-scrollbar {
                  width: 6px;
                  height: 6px;
                }
                ::-webkit-scrollbar-track {
                  background: transparent;
                }
                ::-webkit-scrollbar-thumb {
                  background: ${isDark ? "rgba(161, 161, 170, 0.25)" : "rgba(113, 113, 122, 0.25)"};
                  border-radius: 9999px;
                  transition: background-color 0.2s;
                }
                ::-webkit-scrollbar-thumb:hover {
                  background: ${isDark ? "rgba(161, 161, 170, 0.45)" : "rgba(113, 113, 122, 0.45)"};
                }
                * {
                  scrollbar-width: thin;
                  scrollbar-color: ${isDark ? "rgba(161, 161, 170, 0.25)" : "rgba(113, 113, 122, 0.25)"} transparent;
                }
              </style>
            </head>
            <body>${message.html}</body>
          </html>
        `)
        doc.close()

        // 深色模式下，若邮件正文自带颜色或样式表则切到白纸模式
        if (isDark && doc.body) {
          const hasInlineColor = (el: Element) =>
            /(^|;)\s*(color|background(-color|-image)?)\s*:/i.test(
              el.getAttribute("style") ?? ""
            )

          const hasOwnColors =
            doc.body.hasAttribute("bgcolor") ||
            doc.body.hasAttribute("background") ||
            doc.body.hasAttribute("text") ||
            hasInlineColor(doc.body) ||
            Boolean(
              doc.body.querySelector("[bgcolor],[background],font[color],[text],style")
            ) ||
            Array.from(doc.body.querySelectorAll("[style]")).some(hasInlineColor)

          if (hasOwnColors) {
            doc.documentElement.classList.add("paper")
            const colorSchemeMeta = doc.createElement("meta")
            colorSchemeMeta.name = "color-scheme"
            colorSchemeMeta.content = "light"
            doc.head.appendChild(colorSchemeMeta)
          }
        }

        const updateHeight = () => {
          const container = iframe.parentElement
          if (container) {
            iframe.style.height = `${container.clientHeight}px`
          }
        }

        // 固定宽度邮件缩放到适合当前阅读栏宽度（下限 0.6）
        const fitWidth = () => {
          if (!iframeRef.current || !doc.body || !doc.documentElement) return
          doc.body.style.removeProperty("zoom")
          const docCw = doc.documentElement.clientWidth
          const bodyCw = doc.body.clientWidth
          if (docCw <= 0 || bodyCw <= 0) return
          const docSw = doc.documentElement.scrollWidth
          const bodySw = doc.body.scrollWidth
          const padRight =
            parseFloat(doc.defaultView?.getComputedStyle(doc.body).paddingRight || "0") || 0
          const ratios: number[] = []
          if (bodySw > bodyCw + 1) {
            ratios.push(bodyCw / (bodySw + padRight))
          }
          if (docSw > docCw + 1) {
            ratios.push(docCw / docSw)
          }
          if (ratios.length > 0) {
            doc.body.style.setProperty("zoom", String(Math.max(0.6, Math.min(...ratios))))
          }
        }

        const handleLayout = () => {
          updateHeight()
          fitWidth()
        }

        handleLayout()
        window.addEventListener("resize", handleLayout)

        const resizeObserver = new ResizeObserver(updateHeight)
        resizeObserver.observe(doc.body)

        const containerObserver = iframe.parentElement
          ? new ResizeObserver(handleLayout)
          : null
        if (containerObserver && iframe.parentElement) {
          containerObserver.observe(iframe.parentElement)
        }

        doc.querySelectorAll("img").forEach((img: HTMLImageElement) => {
          img.onload = handleLayout
        })

        return () => {
          window.removeEventListener("resize", handleLayout)
          resizeObserver.disconnect()
          containerObserver?.disconnect()
        }
      }
    }
  }

  useEffect(() => {
    return updateIframeContent()
  }, [message?.html, viewMode, isDark])

  if (loading) {
    return (
      <div className="flex h-full min-h-[10rem] flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <span>{t.loading}</span>
      </div>
    )
  }

  if (!message) {
    return <EmptyState icon={Mail} title={t.selectMessage} />
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-5 py-4 space-y-2.5 border-b border-border/70 bg-muted/20">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-base font-semibold tracking-tight text-foreground flex-1">{message.subject}</h3>
        </div>
        <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
          {message.from_address && (
            <>
              <span className="text-muted-foreground">{t.from}:</span>
              <span className="truncate font-mono text-foreground/85">{message.from_address}</span>
            </>
          )}
          {message.to_address && (
            <>
              <span className="text-muted-foreground">{t.to}:</span>
              <span className="truncate font-mono text-foreground/85">{message.to_address}</span>
            </>
          )}
          <span className="text-muted-foreground">{t.time}:</span>
          <span className="truncate tabular-nums text-foreground/85">
            {mounted
              ? new Date(message.sent_at || message.received_at || 0).toLocaleString()
              : "\u00a0"}
          </span>
        </div>
      </div>

      {message.html && message.content && (
        <div className="border-b border-border/70 px-5 py-2 bg-muted/10 flex justify-end">
          <Segmented
            value={viewMode}
            onValueChange={(value) => setViewMode(value as ViewMode)}
          >
            <SegmentedItem value="html">{t.htmlFormat}</SegmentedItem>
            <SegmentedItem value="text">{t.textFormat}</SegmentedItem>
          </Segmented>
        </div>
      )}

      <div className="flex-1 overflow-auto relative">
        {viewMode === "html" && message.html ? (
          <iframe
            ref={iframeRef}
            className="absolute inset-0 w-full h-full border-0 bg-transparent"
            sandbox="allow-same-origin allow-popups"
          />
        ) : message.content ? (
          <div className="p-5 text-sm leading-relaxed whitespace-pre-wrap text-foreground">
            {message.content}
          </div>
        ) : (
          <EmptyState icon={Mail} title={t.selectMessage} />
        )}
      </div>
    </div>
  )
}
