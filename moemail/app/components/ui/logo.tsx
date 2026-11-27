"use client"

import Link from "next/link"

export function Logo() {
  return (
    <Link
      href="/"
      className="flex items-center gap-2.5 group transition-opacity hover:opacity-90"
    >
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20 transition-colors group-hover:bg-primary/15">
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <rect
            x="2.5"
            y="4.5"
            width="19"
            height="15"
            rx="3"
            className="stroke-current"
            strokeWidth="1.8"
          />
          <path
            d="M3.5 6.5L11.1 12.2C11.63 12.6 12.37 12.6 12.9 12.2L20.5 6.5"
            className="stroke-current"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <span className="text-[15px] font-semibold tracking-tight text-foreground">
        MoeMail
      </span>
    </Link>
  )
}
