"use client"

import { AlertCircle } from "lucide-react"
import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "./toast"
import { useToast } from "./use-toast"

export interface ToastProps {
  id: string
  title?: string
  description?: string
  action?: React.ReactNode
  variant?: "default" | "destructive"
}

export function Toaster() {
  const { toasts } = useToast()

  return (
    <ToastProvider>
      {toasts.map(function ({ 
        id, 
        title, 
        description, 
        action, 
        variant,
        ...props 
      }: {
        id: string;
        title?: React.ReactNode;
        description?: React.ReactNode;
        action?: React.ReactNode;
        variant?: "default" | "destructive" | null;
        [key: string]: any;
      }) {
        return (
          <Toast key={id} variant={variant} {...props}>
            {variant === "destructive" && (
              <AlertCircle
                aria-hidden="true"
                className="mt-0.5 h-4 w-4 shrink-0 text-destructive"
              />
            )}
            <div className="grid min-w-0 flex-1 gap-1">
              {title && <ToastTitle>{title}</ToastTitle>}
              {description && description !== title && (
                <ToastDescription>{description}</ToastDescription>
              )}
            </div>
            {action}
            <ToastClose />
          </Toast>
        )
      })}
      <ToastViewport />
    </ToastProvider>
  )
} 