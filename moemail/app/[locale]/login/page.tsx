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

  const [turnstile, allowRegistration] = await Promise.all([
    getTurnstileConfig(),
    isRegistrationOpen(),
  ])

  return (
    <div className="min-h-screen flex flex-col items-center justify-start px-4 pt-[12vh] pb-12 sm:pt-[16vh] bg-page bg-hero-glow">
      <LoginForm
        turnstile={{ enabled: turnstile.enabled, siteKey: turnstile.siteKey }}
        allowRegistration={allowRegistration}
        oauth={oauthProviders()}
      />
    </div>
  )
}
