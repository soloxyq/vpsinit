import React from "react"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

interface CheckboxProps {
  id?: string
  checked?: boolean
  onChange?: (checked: boolean) => void
  className?: string
  disabled?: boolean
}

export const Checkbox: React.FC<CheckboxProps> = ({
  id,
  checked = false,
  onChange,
  className,
  disabled = false
}) => {
  const handleChange = () => {
    if (!disabled && onChange) {
      onChange(!checked)
    }
  }

  return (
    <div 
      className={cn(
        "relative inline-flex h-5 w-5 items-center justify-center rounded-md border shadow-sm cursor-pointer transition-colors duration-150 focus-within:ring-2 focus-within:ring-ring/30 focus-within:ring-offset-1 focus-within:ring-offset-background",
        checked 
          ? "bg-primary border-primary text-primary-foreground" 
          : "bg-background border-muted-foreground/50 hover:border-muted-foreground",
        disabled && "opacity-50 cursor-not-allowed",
        className
      )}
      onClick={handleChange}
    >
      <input
        type="checkbox"
        id={id}
        checked={checked}
        onChange={() => {}} // Controlled by div onClick
        className="sr-only"
        disabled={disabled}
      />
      {checked && (
        <Check 
          className="h-3.5 w-3.5 text-current animate-in fade-in-0 zoom-in-50 duration-150" 
        />
      )}
    </div>
  )
} 