import { LoginForm } from "@/components/auth/login-form"
import { auth, isRegistrationOpen, oauthProviders } from "@/lib/auth"
import { redirect } from "next/navigation"
import type { Locale } from "@/i18n/config"
import { getTurnstileConfig } from "@/lib/turnstile"

export const runtime = "edge"

export default async function LoginPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale: localeFromParams } = await params
  const locale = localeFromParams as Locale
  const session = await auth()
  
  if (session?.user) {
    redirect(`/${locale}`)
  }

  const turnstile = await getTurnstileConfig()
  const allowRegistration = await isRegistrationOpen()

  return (
    <div className="min-h-screen flex items-center justify-center bg-page bg-hero-glow px-4">
      <LoginForm
        turnstile={{ enabled: turnstile.enabled, siteKey: turnstile.siteKey }}
        allowRegistration={allowRegistration}
        oauth={oauthProviders()}
      />
    </div>
  )
}
