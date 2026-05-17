"use client"

import { useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { UrlInput } from "@/components/url-input"
import { CrawlSizeSelector } from "@/components/crawl-size-selector"
import { submitJob } from "@/lib/api"
import { CRAWL_PRESETS, type CrawlSize } from "@/lib/types"

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
  const [crawlSize, setCrawlSize] = useState<CrawlSize>("recommended")
  const [submitting, setSubmitting] = useState(false)
  const [urlError, setUrlError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Pre-fill from query params (e.g. from RetryButton)
  useEffect(() => {
    const paramUrl = searchParams.get("url")
    const paramCrawlSize = searchParams.get("crawl_size") as CrawlSize | null
    if (paramUrl) setUrl(paramUrl)
    if (paramCrawlSize && paramCrawlSize in CRAWL_PRESETS) setCrawlSize(paramCrawlSize)
  }, [searchParams])

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
      const { job_id } = await submitJob(normalized, CRAWL_PRESETS[crawlSize])
      router.push(`/result/${job_id}`)
    } catch {
      setSubmitError("Could not connect to the server. Please try again.")
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <UrlInput
            value={url}
            onChange={setUrl}
            error={urlError}
            disabled={submitting}
          />

          <div className="space-y-1.5">
            <p className="text-xs text-muted-foreground">Crawl size</p>
            <CrawlSizeSelector
              value={crawlSize}
              onChange={setCrawlSize}
              disabled={submitting}
            />
          </div>

          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? "Starting…" : "Generate"}
          </Button>

          {submitError && (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              <p>{submitError}</p>
            </div>
          )}
        </form>
      </CardContent>
    </Card>
  )
}
