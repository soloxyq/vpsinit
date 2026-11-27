"use client"

import * as React from "react"
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group"
import { cn } from "@/lib/utils"

// 分段选择：语义上仍是一组单选按钮（radiogroup / radio，方向键可切换），只是外观做成并排的分段。
const Segmented = React.forwardRef<
  React.ElementRef<typeof RadioGroupPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Root>
>(({ className, ...props }, ref) => (
  <RadioGroupPrimitive.Root
    ref={ref}
    className={cn(
      "inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5",
      className
    )}
    {...props}
  />
))
Segmented.displayName = "Segmented"

const SegmentedItem = React.forwardRef<
  React.ElementRef<typeof RadioGroupPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Item>
>(({ className, ...props }, ref) => (
  <RadioGroupPrimitive.Item
    ref={ref}
    className={cn(
      "inline-flex h-7 items-center justify-center whitespace-nowrap rounded-md px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:pointer-events-none disabled:opacity-50 data-[state=checked]:bg-card data-[state=checked]:text-foreground data-[state=checked]:shadow-sm dark:data-[state=checked]:bg-white/10",
      className
    )}
    {...props}
  />
))
SegmentedItem.displayName = "SegmentedItem"

export { Segmented, SegmentedItem }
