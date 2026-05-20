import Link from "next/link"
import { listJobs, type JobListItem } from "@/lib/api"
import { DirectoryTable } from "@/components/directory-table"

export const revalidate = 60

export default async function DirectoryPage() {
  let jobs: JobListItem[] = []
  try {
    jobs = await listJobs()
  } catch {
    // show empty state if backend unreachable
  }

  const totalTokens = jobs.reduce((sum, j) => sum + (j.total_tokens ?? 0), 0)
  const totalPages  = jobs.reduce((sum, j) => sum + (j.page_count ?? 0), 0)

  function formatBig(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}k`
    return String(n)
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b px-6 py-4 flex items-center justify-between">
        <Link href="/" className="font-semibold tracking-tight hover:opacity-70 transition-opacity font-[family-name:var(--font-libre-baskerville)]">
          llms.txt
        </Link>
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
          Generate
        </Link>
      </header>

      <main className="flex-1 px-6 py-12">
        <div className="mx-auto w-full max-w-[1600px] space-y-6">
          <div className="space-y-3">
            <h1 className="text-4xl font-bold tracking-tight font-mono">
              llms.txt directory
            </h1>
            <p className="text-sm text-muted-foreground max-w-2xl">
              Public index of generated llms.txt files across the web.
            </p>
            <div className="flex gap-8 text-sm font-mono text-muted-foreground">
              <span>{jobs.length} sites indexed</span>
              <span>{formatBig(totalTokens)} tokens processed</span>
              <span>{formatBig(totalPages)} pages crawled</span>
            </div>
          </div>

          {jobs.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center font-mono">
              No results yet.{" "}
              <Link href="/" className="underline underline-offset-4">
                Generate the first one.
              </Link>
            </p>
          ) : (
            <DirectoryTable jobs={jobs} />
          )}
        </div>
      </main>
    </div>
  )
}
