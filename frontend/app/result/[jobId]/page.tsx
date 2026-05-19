"use client"

import Link from "next/link"
import { use } from "react"
import { useJobPolling } from "@/hooks/use-job-polling"
import { StatusIndicator } from "@/components/status-indicator"
import { LlmsPreview } from "@/components/llms-preview"
import { CopyButton } from "@/components/copy-button"
import { DownloadButton } from "@/components/download-button"
import { RetryButton } from "@/components/retry-button"
import { JobSummary } from "@/components/job-summary"
import { Card, CardContent } from "@/components/ui/card"

interface ResultPageProps {
  params: Promise<{ jobId: string }>
}

export default function ResultPage({ params }: ResultPageProps) {
  const { jobId } = use(params)
  const { data, error } = useJobPolling(jobId)

  const isInProgress =
    !data || data.status === "queued" || data.status === "crawling" || data.status === "generating"

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

      <main className="flex-1 px-4 py-12">
        <div className="mx-auto w-full max-w-3xl space-y-6">

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
              <CardContent className="pt-6">
                <StatusIndicator
                  status={data?.status ?? "queued"}
                  url={data?.url ?? ""}
                  pageCount={data?.page_count}
                />
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
                    url={data.url}
                    crawlSize="quick"
                    label="Use homepage only"
                    variant="outline"
                  />
                </div>
              </CardContent>
            </Card>
          )}

          {/* Done */}
          {!error && data?.status === "done" && data.result && (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-4 flex-wrap">
                <JobSummary
                  pageCount={data.page_count ?? 0}
                  generationTimeMs={data.generation_time_ms}
                />
                <div className="flex gap-2 flex-wrap">
                  <CopyButton text={data.result} />
                  <DownloadButton content={data.result} />
                  <RetryButton url={data.url} label="Generate again" variant="outline" />
                </div>
              </div>

              <LlmsPreview content={data.result} />
            </div>
          )}

        </div>
      </main>
    </div>
  )
}
