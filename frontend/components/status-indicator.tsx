import type { JobStatus } from "@/lib/types"

interface StatusIndicatorProps {
  status: JobStatus
  url: string
  pageCount?: number | null
}

const STATUS_MESSAGES: Record<string, string> = {
  queued: "Waiting to start…",
  crawling: "Crawling site…",
  generating: "Generating llms.txt…",
}

export function StatusIndicator({ status, url, pageCount }: StatusIndicatorProps) {
  const message = STATUS_MESSAGES[status] ?? "Processing…"

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <span className="relative flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground opacity-50" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-foreground" />
        </span>
        <span className="text-lg font-medium">{message}</span>
      </div>

      <div className="space-y-1 text-sm text-muted-foreground">
        <div>
          <span className="text-foreground/60">URL: </span>
          {url}
        </div>
        {pageCount != null && (
          <div>
            <span className="text-foreground/60">Pages crawled: </span>
            {pageCount}
          </div>
        )}
      </div>
    </div>
  )
}
