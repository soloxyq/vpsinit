import { NextResponse } from "next/server"
import { requireUser } from "@/lib/guard"
import { PERMISSIONS } from "@/lib/permissions"
import { checkSendPermission } from "@/lib/send-permissions"

export const runtime = "edge"

export async function GET() {
  const guard = await requireUser(PERMISSIONS.MANAGE_EMAIL, { apiKey: true })
  if (guard.error) return guard.error

  try {
    const result = await checkSendPermission(guard.userId, false, guard.roles)
    
    return NextResponse.json(result)
  } catch (error) {
    console.error('Failed to check send permission:', error)
    return NextResponse.json(
      { 
        canSend: false, 
        error: "权限检查失败" 
      },
      { status: 500 }
    )
  }
}