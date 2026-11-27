"use client"

import { useEffect, useState } from "react"

// 服务器（线上是 Cloudflare Worker：UTC 时区、en-US 格式）和访客浏览器的时区、语言不同。
// 按访客本地格式显示的时间只能在浏览器里算：服务器渲染时先不输出，挂载后再填上。
// 不要用 suppressHydrationWarning 代替：React 19 会直接保留服务器渲染的文字，访客看到的就是 UTC 时间。
export function useMounted() {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  return mounted
}
