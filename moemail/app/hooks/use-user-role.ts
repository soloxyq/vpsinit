"use client"

import { useSession } from "next-auth/react"
import { Role } from "@/lib/permissions"

export function useUserRole() {
  const { data: session, status } = useSession()
  const role = (session?.user?.roles?.[0]?.name as Role | undefined) ?? null

  return {
    role,
    loading: status === "loading"
  }
} 