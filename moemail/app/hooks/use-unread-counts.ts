"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { usePolling } from "@/hooks/use-polling"
import { EMAIL_CONFIG } from "@/config"

// 每个邮箱的未读邮件数（邮箱 ID → 数量，没有未读的邮箱不在里面），给邮箱列表显示角标。
// 定时刷新，标签页在后台时暂停；读了邮件、标了已读、来了新邮件之后，调用方用 refresh 再取一次
export function useUnreadCounts() {
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [enabled, setEnabled] = useState(true)
  const latestRef = useRef(0)

  const refresh = useCallback(async () => {
    const request = ++latestRef.current
    try {
      const response = await fetch("/api/emails/unread")
      if (response.status === 401 || response.status === 403) {
        // 没登录，或者这个角色没有邮箱权限：不用再问了
        setEnabled(false)
        return
      }
      if (!response.ok) return
      const data = (await response.json()) as { counts: Record<string, number> }
      // 只认最后发出的那次请求：先发后到的旧结果会把新的数字盖掉
      if (request === latestRef.current) setCounts(data.counts)
    } catch {
      // 网络错误：等下一次
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])
  usePolling(refresh, EMAIL_CONFIG.UNREAD_POLL_INTERVAL, enabled)

  return { counts, refresh }
}
