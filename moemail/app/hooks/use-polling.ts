"use client"

import { useEffect, useRef } from "react"

// 每隔 interval 毫秒调用一次 callback。标签页切到后台时暂停，切回前台立即调用一次再接着轮询：
// 后台标签页不发请求，省 Workers 请求数和 D1 读取的免费额度。
// callback 每次渲染都换成最新的，里面读到的状态不会是旧的
export function usePolling(callback: () => void, interval: number, enabled = true) {
  const callbackRef = useRef(callback)

  useEffect(() => {
    callbackRef.current = callback
  })

  useEffect(() => {
    if (!enabled) return
    let timer: ReturnType<typeof setInterval> | null = null

    const start = () => {
      if (!timer) timer = setInterval(() => callbackRef.current(), interval)
    }
    const stop = () => {
      if (timer) clearInterval(timer)
      timer = null
    }
    const onVisibilityChange = () => {
      if (document.hidden) {
        stop()
      } else {
        callbackRef.current()
        start()
      }
    }

    if (!document.hidden) start()
    document.addEventListener("visibilitychange", onVisibilityChange)
    return () => {
      stop()
      document.removeEventListener("visibilitychange", onVisibilityChange)
    }
  }, [interval, enabled])
}
