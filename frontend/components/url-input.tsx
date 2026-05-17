"use client"

import { Input } from "@/components/ui/input"

interface UrlInputProps {
  value: string
  onChange: (value: string) => void
  error?: string | null
  disabled?: boolean
}

export function UrlInput({ value, onChange, error, disabled }: UrlInputProps) {
  const handleBlur = () => {
    const trimmed = value.trim()
    if (!trimmed) return
    // Auto-prefix https:// for bare domains
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
      onChange(`https://${trimmed}`)
    }
  }

  return (
    <div className="w-full">
      <Input
        type="url"
        placeholder="https://example.com"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={handleBlur}
        disabled={disabled}
        className={error ? "border-destructive focus-visible:ring-destructive" : ""}
        aria-invalid={!!error}
      />
      {error && (
        <p className="mt-1.5 text-sm text-destructive">{error}</p>
      )}
    </div>
  )
}
