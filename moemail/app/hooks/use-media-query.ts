"use client"

import { useEffect, useState } from "react"

// 媒体查询当前是否命中。服务端渲染和浏览器里的首次渲染还不知道，返回 null
export function useMediaQuery(query: string): boolean | null {
  const [matches, setMatches] = useState<boolean | null>(null)

  useEffect(() => {
    const media = window.matchMedia(query)
    const update = () => setMatches(media.matches)
    update()
    media.addEventListener("change", update)
    return () => media.removeEventListener("change", update)
  }, [query])

  return matches
}
