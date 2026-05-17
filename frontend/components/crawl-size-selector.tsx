"use client"

import { cn } from "@/lib/utils"
import type { CrawlSize } from "@/lib/types"

const OPTIONS: { value: CrawlSize; label: string; description: string }[] = [
  { value: "quick", label: "Quick", description: "Homepage only — fastest" },
  { value: "recommended", label: "Recommended", description: "Homepage + important linked pages" },
  { value: "deep", label: "Deep", description: "More pages, slower — best for large sites" },
]

interface CrawlSizeSelectorProps {
  value: CrawlSize
  onChange: (value: CrawlSize) => void
  disabled?: boolean
}

export function CrawlSizeSelector({ value, onChange, disabled }: CrawlSizeSelectorProps) {
  return (
    <div className="flex gap-2">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          disabled={disabled}
          onClick={() => onChange(opt.value)}
          className={cn(
            "flex-1 rounded-md border px-3 py-2 text-left text-sm transition-colors",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            value === opt.value
              ? "border-foreground bg-foreground text-background"
              : "border-border text-muted-foreground hover:border-foreground/50 hover:text-foreground"
          )}
        >
          <div className="font-medium">{opt.label}</div>
          <div className="mt-0.5 text-xs opacity-70">{opt.description}</div>
        </button>
      ))}
    </div>
  )
}
