"use client"

import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"
import { cn } from "@/lib/utils"

const Tabs = TabsPrimitive.Root

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "inline-flex h-10 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground dark:bg-background/70",
      className
    )}
    {...props}
  />
))
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ring-offset-background transition-colors duration-150 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm data-[state=active]:ring-1 data-[state=active]:ring-border/60 data-[state=active]:focus-visible:ring-2 data-[state=active]:focus-visible:ring-ring/40",
      className
    )}
    {...props}
  />
))
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-1",
      className
    )}
    {...props}
  />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

const SlidingTabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, children, ...props }, ref) => {
  const [activeIndex, setActiveIndex] = React.useState(0)
  
  const combinedRef = React.useCallback((node: HTMLDivElement | null) => {
    if (node) {
      const updateActiveIndex = () => {
        const triggers = node.querySelectorAll('[data-state="active"]')
        if (triggers.length > 0) {
          const allTriggers = node.querySelectorAll('[role="tab"]')
          const activeElement = triggers[0]
          const index = Array.from(allTriggers).indexOf(activeElement)
          if (index >= 0) {
            setActiveIndex(index)
          }
        }
      }

      setTimeout(updateActiveIndex, 0)
      
      const observer = new MutationObserver(updateActiveIndex)
      observer.observe(node, {
        attributes: true,
        attributeFilter: ['data-state'],
        subtree: true
      })
      
      return () => observer.disconnect()
    }
    
    if (typeof ref === 'function') {
      ref(node)
    }
  }, [ref])
  
  const childrenArray = React.Children.toArray(children)
  const tabCount = childrenArray.length
  const tabWidth = `calc(${100 / tabCount}% - ${2 * (tabCount - 1) / tabCount}px)`
  const slidePosition = `calc(${(100 / tabCount) * activeIndex}% + ${activeIndex}px)`
  
  return (
    <TabsPrimitive.List
      ref={combinedRef}
      className={cn(
        "relative flex w-full bg-muted rounded-lg p-1 h-auto dark:bg-background/70",
        className
      )}
      {...props}
    >
      <div 
        className="absolute top-1 bottom-1 bg-card border border-border/60 rounded-md shadow-sm transition-all duration-200 ease-out"
        style={{
          width: tabWidth,
          left: slidePosition
        }}
      />
      {children}
    </TabsPrimitive.List>
  )
})
SlidingTabsList.displayName = "SlidingTabsList"

const SlidingTabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "relative z-10 flex-1 h-8 gap-2 flex items-center justify-center text-xs font-medium transition-colors duration-150 rounded-md px-3 py-1.5 data-[state=active]:text-foreground data-[state=active]:bg-transparent data-[state=inactive]:text-muted-foreground data-[state=inactive]:hover:text-foreground ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-50",
      className
    )}
    {...props}
  />
))
SlidingTabsTrigger.displayName = "SlidingTabsTrigger"

export { Tabs, TabsList, TabsTrigger, TabsContent, SlidingTabsList, SlidingTabsTrigger } 