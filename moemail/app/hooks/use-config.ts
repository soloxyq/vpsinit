"use client"

import { create } from "zustand"
import { Role, ROLES } from "@/lib/permissions"
import { EMAIL_CONFIG } from "@/config"
import { useEffect } from "react"

interface Config {
  defaultRole: Exclude<Role, typeof ROLES.EMPEROR>
  emailDomains: string
  emailDomainsArray: string[]
  adminContact: string
  maxEmails: number
}

interface ConfigStore {
  config: Config | null
  loading: boolean
  error: string | null
  fetch: () => Promise<void>
}

let inflightConfigFetch: Promise<void> | null = null

const useConfigStore = create<ConfigStore>((set) => ({
  config: null,
  loading: false,
  error: null,
  fetch: async () => {
    if (inflightConfigFetch) return inflightConfigFetch
    inflightConfigFetch = (async () => {
      try {
        set({ loading: true, error: null })
        const res = await fetch("/api/config")
        if (!res.ok) throw new Error("获取配置失败")
        const data = await res.json() as Config
        const domains = (data.emailDomains || "moemail.app")
          .split(",")
          .map((d) => d.trim())
          .filter(Boolean)
        const emailDomainsArray = domains.length > 0 ? domains : ["moemail.app"]
        set({
          config: {
            defaultRole: data.defaultRole || ROLES.CIVILIAN,
            emailDomains: emailDomainsArray.join(","),
            emailDomainsArray,
            adminContact: data.adminContact || "",
            maxEmails: Number(data.maxEmails) || EMAIL_CONFIG.MAX_ACTIVE_EMAILS
          },
          loading: false,
          error: null,
        })
      } catch (error) {
        set({ 
          error: error instanceof Error ? error.message : "获取配置失败",
          loading: false 
        })
      } finally {
        inflightConfigFetch = null
      }
    })()
    return inflightConfigFetch
  }
}))

export function refreshCachedConfig() {
  return useConfigStore.getState().fetch()
}

export function useConfig() {
  const store = useConfigStore()

  useEffect(() => {
    if (!store.config && !store.loading && !store.error) {
      store.fetch()
    }
  }, [store.config, store.loading, store.error, store.fetch])

  return store
}