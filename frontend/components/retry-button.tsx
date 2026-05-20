"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { submitJob } from "@/lib/api"
import { CRAWL_PRESETS, type CrawlSize } from "@/lib/types"

interface RetryButtonProps {
  url: string
  crawlSize?: CrawlSize
  label?: string
  variant?: "default" | "outline"
}

export function RetryButton({
  url,
  crawlSize = "recommended",
  label = "Try again",
  variant = "default",
}: RetryButtonProps) {
  const router = useRouter()
  const [loading, setLoading] = useState(false)

  const handleClick = async () => {
    if (!url) {
      router.push("/")
      return
    }
    setLoading(true)
    try {
      const { job_id } = await submitJob(url, CRAWL_PRESETS[crawlSize])
      router.push(`/result/${job_id}`)
    } catch {
      setLoading(false)
    }
  }

  return (
    <Button variant={variant} disabled={loading} onClick={handleClick}>
      {loading ? "Starting…" : label}
    </Button>
  )
}
