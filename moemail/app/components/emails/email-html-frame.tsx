"use client"

import { useEffect, useRef, useState } from "react"
import { useTheme } from "next-themes"
import { cn } from "@/lib/utils"
import type { AttachmentInfo } from "@/lib/attachments"
import { loadInlineImages } from "./inline-images"

// 邮件正文的 HTML 放进 blob: 地址的独立页面里显示，不用 document.write 写进空白 iframe。
// document.write 会把 iframe 的地址改成外层页面的地址，在邮箱分享页上就是 /shared/<token>：
// 邮件里的外链图片或链接加上 referrerpolicy="unsafe-url"（或 <meta name="referrer">），
// 浏览器就会把带 token 的地址放进 Referer 头发给对方。blob: 地址不会作为 Referer 发出去。
// iframe 仍是 sandbox="allow-same-origin allow-popups"：邮件里的脚本不运行，
// 本页可以读写里面的内容，用来适配宽度、切换深浅色和显示内嵌图片。

interface EmailHtmlFrameProps {
  html: string
  attachments?: AttachmentInfo[]
  // 附件下载地址前缀，后面接附件序号；内嵌图片从这里取
  attachmentBaseUrl?: string
}

const STYLE_ID = "moemail-frame-style"

const frameCss = (isDark: boolean) => `
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
`

// 邮件正文自带颜色或样式表时，深色模式下改用白纸模式，避免深字落深底或白板嵌黑框
const hasOwnColors = (body: HTMLElement) => {
  const hasInlineColor = (el: Element) =>
    /(^|;)\s*(color|background(-color|-image)?)\s*:/i.test(el.getAttribute("style") ?? "")
  return (
    body.hasAttribute("bgcolor") ||
    body.hasAttribute("background") ||
    body.hasAttribute("text") ||
    hasInlineColor(body) ||
    Boolean(body.querySelector("[bgcolor],[background],font[color],[text],style")) ||
    Array.from(body.querySelectorAll("[style]")).some(hasInlineColor)
  )
}

// 邮件里的 <style>、<meta> 等都会落在 <body> 里，<head> 里只有这里写的几个元素
const frameDocument = (html: string, isDark: boolean) => `<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <base target="_blank">
    <style id="${STYLE_ID}">${frameCss(isDark)}</style>
  </head>
  <body>${html}</body>
</html>`

// 切换深浅色时直接改已经显示的页面，不重新加载（不闪、不丢滚动位置）
function applyTheme(doc: Document, isDark: boolean, ownColors: boolean) {
  const style = doc.getElementById(STYLE_ID)
  const css = frameCss(isDark)
  if (style && style.textContent !== css) style.textContent = css
  const paper = isDark && ownColors
  doc.documentElement.classList.toggle("paper", paper)
  const meta = doc.head.querySelector('meta[name="color-scheme"]')
  if (paper && !meta) {
    const colorSchemeMeta = doc.createElement("meta")
    colorSchemeMeta.name = "color-scheme"
    colorSchemeMeta.content = "light"
    doc.head.appendChild(colorSchemeMeta)
  } else if (!paper && meta) {
    meta.remove()
  }
}

// 等 iframe 换成 blob: 页面并解析完（页面里没有脚本，只能从外面看）。
// 不等 load 事件：load 要等邮件里所有外链图片下载完，慢的要好几秒
function whenFrameParsed(iframe: HTMLIFrameElement, url: string, ready: (doc: Document) => void) {
  let done = false
  let frame = 0
  const check = () => {
    if (done) return true
    const doc = iframe.contentDocument
    if (doc && doc.URL === url && doc.readyState !== "loading" && doc.body) {
      done = true
      ready(doc)
    }
    return done
  }
  const poll = () => {
    if (!check()) frame = requestAnimationFrame(poll)
  }
  // 后台标签页里 requestAnimationFrame 会暂停，load 事件兜底
  iframe.addEventListener("load", check)
  poll()
  return () => {
    done = true
    cancelAnimationFrame(frame)
    iframe.removeEventListener("load", check)
  }
}

export function EmailHtmlFrame({ html, attachments, attachmentBaseUrl }: EmailHtmlFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === "dark"
  const isDarkRef = useRef(isDark)
  // 附件列表按内容比较，不按数组引用：调用方每次渲染都传一个新数组（例如 attachments ?? []）时，
  // 正文不会跟着重新加载（重新加载会闪一下、滚动位置回到顶部、内嵌图片重新下载）
  const attachmentsJson = JSON.stringify(attachments ?? [])
  // 已经显示出来的页面，以及重新适配布局的函数
  const loadedRef = useRef<{ doc: Document; ownColors: boolean; relayout: () => void } | null>(null)
  // 解析完、定好白纸模式和缩放之前不显示，免得先看到空白页、深色模式下闪白，或者没缩放的宽邮件
  const [ready, setReady] = useState(false)

  useEffect(() => {
    isDarkRef.current = isDark
    const loaded = loadedRef.current
    if (!loaded) return
    applyTheme(loaded.doc, isDark, loaded.ownColors)
    loaded.relayout()
  }, [isDark])

  useEffect(() => {
    const iframe = iframeRef.current
    if (!iframe) return
    setReady(false)

    const url = URL.createObjectURL(
      new Blob([frameDocument(html, isDarkRef.current)], { type: "text/html;charset=utf-8" })
    )
    let teardown: (() => void) | null = null

    const stopWaiting = whenFrameParsed(iframe, url, (doc) => {
      const ownColors = hasOwnColors(doc.body)
      applyTheme(doc, isDarkRef.current, ownColors)

      // 更新高度以填充容器
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
      // 所有外链图片下载完时 iframe 会触发 load
      iframe.addEventListener("load", handleLayout)

      // 监听内容变化
      const resizeObserver = new ResizeObserver(updateHeight)
      resizeObserver.observe(doc.body)

      // 监听容器宽度变化以重新适配缩放
      const containerObserver = iframe.parentElement ? new ResizeObserver(handleLayout) : null
      if (containerObserver && iframe.parentElement) {
        containerObserver.observe(iframe.parentElement)
      }

      // 图片加载完会改变宽度。load 事件不冒泡，在捕获阶段统一监听，后来换成 blob: 地址的内嵌图片也算在内
      doc.addEventListener("load", handleLayout, true)

      const releaseInlineImages = loadInlineImages(
        doc,
        JSON.parse(attachmentsJson) as AttachmentInfo[],
        attachmentBaseUrl
      )

      loadedRef.current = { doc, ownColors, relayout: handleLayout }
      setReady(true)

      teardown = () => {
        window.removeEventListener("resize", handleLayout)
        iframe.removeEventListener("load", handleLayout)
        doc.removeEventListener("load", handleLayout, true)
        resizeObserver.disconnect()
        containerObserver?.disconnect()
        releaseInlineImages()
      }
    })

    // 用 location.replace 换页面，不在浏览器历史里留下记录（否则按返回键会先退 iframe）
    if (iframe.contentWindow) iframe.contentWindow.location.replace(url)
    else iframe.src = url

    return () => {
      stopWaiting()
      teardown?.()
      loadedRef.current = null
      URL.revokeObjectURL(url)
    }
  }, [html, attachmentsJson, attachmentBaseUrl])

  return (
    <iframe
      ref={iframeRef}
      className={cn("absolute inset-0 w-full h-full border-0 bg-transparent", !ready && "invisible")}
      sandbox="allow-same-origin allow-popups"
    />
  )
}
