"use client"

import Link from "next/link"
import { use } from "react"
import { useJobPolling } from "@/hooks/use-job-polling"
import { StatusIndicator } from "@/components/status-indicator"
import { LlmsPreview } from "@/components/llms-preview"
import { CopyButton } from "@/components/copy-button"
import { DownloadButton } from "@/components/download-button"
import { RetryButton } from "@/components/retry-button"
import { CancelButton } from "@/components/cancel-button"
import { Card, CardContent } from "@/components/ui/card"

function formatDuration(ms?: number | null): string {
  if (ms == null) return "—"
  const s = Math.round(ms / 1000)
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`
}

interface ResultPageProps {
  params: Promise<{ jobId: string }>
}

export default function ResultPage({ params }: ResultPageProps) {
  const { jobId } = use(params)
  const { data, error } = useJobPolling(jobId)

  const isInProgress =
    !data || data.status === "queued" || data.status === "crawling" || data.status === "generating" || data.status === "cancel_requested"

  let hostname = ""
  try {
    if (data?.url) hostname = new URL(data.url).hostname.replace(/^www\./, "")
  } catch {}

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b px-6 py-4 flex items-center justify-between">
        <Link href="/" className="font-semibold tracking-tight hover:opacity-70 transition-opacity">
          llms.txt
        </Link>
        <Link href="/directory" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
          Directory
        </Link>
      </header>

      <main className="flex-1 px-4 py-10">
        <div className="mx-auto w-full max-w-5xl space-y-6">

          {/* Network error */}
          {error && (
            <Card>
              <CardContent className="pt-6 space-y-4">
                <p className="font-medium">Something went wrong.</p>
                <p className="text-sm text-muted-foreground">{error}</p>
                <div className="flex gap-3">
                  <RetryButton url="" label="Go back" />
                </div>
              </CardContent>
            </Card>
          )}

          {/* In progress */}
          {!error && isInProgress && (
            <Card>
              <CardContent className="pt-6 space-y-4">
                <StatusIndicator
                  status={data?.status ?? "queued"}
                  url={data?.url ?? ""}
                  pageCount={data?.page_count}
                />
                {data?.status && data.status !== "cancel_requested" && (
                  <CancelButton jobId={jobId} />
                )}
              </CardContent>
            </Card>
          )}

          {/* Error state */}
          {!error && data?.status === "error" && (
            <Card>
              <CardContent className="pt-6 space-y-4">
                <p className="font-medium">
                  We could not generate llms.txt for this site.
                </p>
                <p className="text-sm text-muted-foreground">
                  {data.error ?? "It may block automated requests or require JavaScript."}
                </p>
                <div className="flex gap-3">
                  <RetryButton url={data.url} label="Try again" />
                  <RetryButton
                    url=""
                    label="Back to homepage"
                    variant="outline"
                  />
                </div>
              </CardContent>
            </Card>
          )}

          {/* Cancelled state */}
          {!error && data?.status === "cancelled" && (
            <Card>
              <CardContent className="pt-6 space-y-4">
                <p className="font-medium">Generation was cancelled.</p>
                <p className="text-sm text-muted-foreground">
                  This job stopped before llms.txt could be generated.
                </p>
                <div className="flex gap-3">
                  <RetryButton url={data.url} label="Generate again" />
                </div>
              </CardContent>
            </Card>
          )}

          {/* Done */}
          {!error && data?.status === "done" && data.result && (
            <>
              {/* Summary card */}
              <div className="rounded-lg border bg-muted/20 p-4 space-y-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Generated llms.txt for</p>
                    <h1 className="text-lg font-semibold tracking-tight">{hostname}</h1>
                    <p className="text-sm text-muted-foreground truncate">{data.url}</p>
                  </div>
                  <span className="rounded-full border px-2 py-1 text-xs text-muted-foreground shrink-0">
                    Done
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-muted-foreground">Pages crawled</p>
                    <p className="font-medium">{data.page_count ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Generation time</p>
                    <p className="font-medium">{formatDuration(data.generation_time_ms)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Format</p>
                    <p className="font-medium">llms.txt</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Spec</p>
                    <p className="font-medium">llmstxt.org</p>
                  </div>
                </div>
              </div>

              {/* Preview with sticky toolbar */}
              <div>
                <div className="sticky top-0 z-10 flex items-center justify-between border rounded-t-lg bg-background px-4 py-3">
                  <p className="text-sm font-medium">Preview</p>
                  <div className="flex gap-2">
                    <CopyButton text={data.result} />
                    <DownloadButton content={data.result} />
                    <RetryButton url={data.url} label="Regenerate" variant="outline" />
                  </div>
                </div>
                <LlmsPreview content={data.result} />
              </div>

              {/* Next step */}
              <div className="rounded-lg border p-4 text-sm text-muted-foreground">
                <p className="font-medium text-foreground mb-1">Next step</p>
                <p>
                  Add this file to your website at <code className="text-xs bg-muted px-1 py-0.5 rounded">/llms.txt</code> so AI systems can discover it.
                </p>
              </div>
            </>
          )}

        </div>
      </main>
    </div>
  )
}
