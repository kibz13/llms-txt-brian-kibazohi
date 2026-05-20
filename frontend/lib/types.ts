export const CRAWL_PRESETS = {
  quick:         1,
  standard:      2,
  comprehensive: 5,
} as const

export type CrawlSize = keyof typeof CRAWL_PRESETS

export const COVERAGE_OPTIONS: Record<CrawlSize, { label: string; description: string }> = {
  quick: {
    label:       "Quick",
    description: "Homepage + core navigation pages. Fastest generation.",
  },
  standard: {
    label:       "Standard",
    description: "Balanced crawl across important pages. Recommended for most websites.",
  },
  comprehensive: {
    label:       "Comprehensive",
    description: "Deep crawl with broader coverage. Best for docs, APIs, and developer platforms.",
  },
}

export type JobStatus = "queued" | "crawling" | "generating" | "done" | "error" | "cancel_requested" | "cancelled"

export interface JobStatusResponse {
  job_id: string
  status: JobStatus
  url: string
  site_type?: string | null
  page_count?: number | null
  error?: string | null
  result?: string | null
  generation_time_ms?: number | null
  created_at: string
  updated_at?: string | null
}
