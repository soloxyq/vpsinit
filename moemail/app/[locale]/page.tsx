import { Header } from "@/components/layout/header"
import { auth } from "@/lib/auth"
import { Shield, Share2, Clock, Code2 } from "lucide-react"
import { ActionButton } from "@/components/home/action-button"
import { FeatureCard } from "@/components/home/feature-card"
import { getTranslations } from "next-intl/server"
import type { Locale } from "@/i18n/config"

export const runtime = "edge"

export default async function Home({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale: localeFromParams } = await params
  const locale = localeFromParams as Locale
  const session = await auth()
  const t = await getTranslations({ locale, namespace: "home" })

  return (
    <div className="bg-page bg-hero-glow min-h-screen">
      <div className="container mx-auto px-4 lg:px-8 max-w-[1600px]">
        <Header />
        <main className="pt-16">
          <div className="min-h-[calc(100vh-4rem)] flex flex-col items-center justify-center text-center px-2 py-12 relative isolate overflow-hidden">
            <div className="absolute inset-0 -z-10 bg-grid-primary" />

            <div className="w-full max-w-3xl mx-auto space-y-8 sm:space-y-10 py-4">
              <div className="space-y-3 sm:space-y-4">
                <h1 className="text-3xl sm:text-4xl md:text-5xl font-semibold tracking-tight text-foreground">
                  {t("title")}
                </h1>
                <p className="text-base sm:text-lg text-muted-foreground max-w-xl mx-auto leading-relaxed">
                  {t("subtitle")}
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 sm:gap-4 px-1 sm:px-0">
                <FeatureCard
                  icon={<Shield className="w-5 h-5" />}
                  title={t("features.privacy.title")}
                  description={t("features.privacy.description")}
                />
                <FeatureCard
                  icon={<Share2 className="w-5 h-5" />}
                  title={t("features.instant.title")}
                  description={t("features.instant.description")}
                />
                <FeatureCard
                  icon={<Clock className="w-5 h-5" />}
                  title={t("features.expiry.title")}
                  description={t("features.expiry.description")}
                />
                <FeatureCard
                  icon={<Code2 className="w-5 h-5" />}
                  title={t("features.openapi.title")}
                  description={t("features.openapi.description")}
                />
              </div>

              <div className="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4 px-2 sm:px-0">
                <ActionButton isLoggedIn={!!session?.user} />
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}

