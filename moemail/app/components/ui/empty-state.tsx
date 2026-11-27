import * as React from "react"
import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

interface EmptyStateProps {
  icon: LucideIcon
  title?: React.ReactNode
  className?: string
}

// 空白面板的占位：一个弱化的图标，可选一行说明。
export function EmptyState({ icon: Icon, title, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex h-full min-h-[10rem] flex-col items-center justify-center gap-3 px-6 py-10 text-center",
        className
      )}
    >
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-muted/70 text-muted-foreground/70 ring-1 ring-inset ring-border/70">
        <Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden="true" />
      </div>
      {title && <p className="max-w-[16rem] text-sm text-muted-foreground">{title}</p>}
    </div>
  )
}

interface ListSkeletonProps {
  rows?: number
  label?: string
  className?: string
}

// 列表加载中的骨架行；label 留给读屏软件。
export function ListSkeleton({ rows = 4, label, className }: ListSkeletonProps) {
  return (
    <div className={cn("divide-y divide-border/60", className)} role="status">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex items-start gap-2.5 px-3.5 py-3" aria-hidden="true">
          <div className="mt-0.5 h-4 w-4 shrink-0 animate-pulse rounded bg-muted" />
          <div className="min-w-0 flex-1 space-y-2">
            <div
              className="h-3.5 animate-pulse rounded bg-muted"
              style={{ width: `${[62, 78, 48, 70][index % 4]}%` }}
            />
            <div
              className="h-3 animate-pulse rounded bg-muted/70"
              style={{ width: `${[40, 52, 34, 46][index % 4]}%` }}
            />
          </div>
        </div>
      ))}
      {label && <span className="sr-only">{label}</span>}
    </div>
  )
}
