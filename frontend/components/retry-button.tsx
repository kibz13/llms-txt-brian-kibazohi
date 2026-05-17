"use client"

import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import type { CrawlSize } from "@/lib/types"

interface RetryButtonProps {
  url: string
  crawlSize?: CrawlSize
  label?: string
  variant?: "default" | "outline"
}

export function RetryButton({
  url,
  crawlSize,
  label = "Try again",
  variant = "default",
}: RetryButtonProps) {
  const router = useRouter()

  const handleClick = () => {
    const params = new URLSearchParams({ url })
    if (crawlSize) params.set("crawl_size", crawlSize)
    router.push(`/?${params.toString()}`)
  }

  return (
    <Button variant={variant} onClick={handleClick}>
      {label}
    </Button>
  )
}
