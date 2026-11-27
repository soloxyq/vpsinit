interface FeatureCardProps {
  icon: React.ReactNode
  title: string
  description: string
}

export function FeatureCard({ icon, title, description }: FeatureCardProps) {
  return (
    <div className="p-5 rounded-xl border border-border/80 bg-card/90 shadow-sm hover:border-border hover:shadow-md transition-all duration-200">
      <div className="flex items-start gap-3.5">
        <div className="rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/15 p-2.5 shrink-0">
          {icon}
        </div>
        <div className="text-left space-y-1">
          <h3 className="font-semibold text-sm text-foreground">{title}</h3>
          <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">{description}</p>
        </div>
      </div>
    </div>
  )
}
