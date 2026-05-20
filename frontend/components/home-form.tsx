"use client"

import { useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowRight } from "lucide-react"
import { submitJob } from "@/lib/api"
import { CRAWL_PRESETS } from "@/lib/types"

function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === "http:" || url.protocol === "https:"
  } catch {
    return false
  }
}

export function HomeForm() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const [url, setUrl] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [urlError, setUrlError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    const paramUrl = searchParams.get("url")
    if (paramUrl) setUrl(paramUrl)
  }, [searchParams])

  const handleBlur = () => {
    const trimmed = url.trim()
    if (!trimmed) return
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
      setUrl(`https://${trimmed}`)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setUrlError(null)
    setSubmitError(null)

    const trimmed = url.trim()
    const normalized =
      !trimmed.startsWith("http://") && !trimmed.startsWith("https://")
        ? `https://${trimmed}`
        : trimmed

    if (!isValidUrl(normalized)) {
      setUrlError("Please enter a valid URL.")
      return
    }

    setSubmitting(true)
    try {
      const { job_id } = await submitJob(normalized, CRAWL_PRESETS["recommended"])
      router.push(`/result/${job_id}`)
    } catch {
      setSubmitError("Could not connect to the server. Please try again.")
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <label className="block text-sm font-medium text-slate-700">
        Website URL
      </label>
      <div className="flex gap-3">
        <input
          type="url"
          placeholder="https://example.com"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onBlur={handleBlur}
          disabled={submitting}
          aria-invalid={!!urlError}
          className="flex-1 h-11 rounded-xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:opacity-50 font-[family-name:var(--font-geist-sans)]"
        />
        <button
          type="submit"
          disabled={submitting}
          className="flex items-center gap-2 h-11 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {submitting ? "Starting…" : (
            <>Generate <ArrowRight className="h-4 w-4" /></>
          )}
        </button>
      </div>

      {urlError && (
        <p className="text-sm text-red-600">{urlError}</p>
      )}
      {submitError && (
        <p className="text-sm text-red-600">{submitError}</p>
      )}
    </form>
  )
}
