export const CRAWL_PRESETS = {
  quick: 1,
  recommended: 2,
  deep: 3,
} as const

export type CrawlSize = keyof typeof CRAWL_PRESETS

export type JobStatus = "queued" | "crawling" | "generating" | "done" | "error"

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
