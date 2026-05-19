import Link from "next/link"
import { listJobs } from "@/lib/api"

export const revalidate = 60 // revalidate every 60 seconds

function formatDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return url
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

export default async function DirectoryPage() {
  let jobs = []
  try {
    jobs = await listJobs()
  } catch {
    // show empty state if backend unreachable
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b px-6 py-4 flex items-center justify-between">
        <Link href="/" className="font-semibold tracking-tight hover:opacity-70 transition-opacity">
          llms.txt
        </Link>
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
          Generate
        </Link>
      </header>

      <main className="flex-1 px-4 py-12">
        <div className="mx-auto w-full max-w-3xl space-y-6">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold tracking-tight">Directory</h1>
            <p className="text-sm text-muted-foreground">
              {jobs.length} llms.txt {jobs.length === 1 ? "file" : "files"} generated
            </p>
          </div>

          {jobs.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              No results yet.{" "}
              <Link href="/" className="underline underline-offset-4">
                Generate the first one.
              </Link>
            </p>
          ) : (
            <div className="rounded-lg border overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/40">
                    <th className="px-4 py-3 text-left font-medium text-muted-foreground">Site</th>
                    <th className="px-4 py-3 text-left font-medium text-muted-foreground hidden sm:table-cell">Pages</th>
                    <th className="px-4 py-3 text-left font-medium text-muted-foreground hidden sm:table-cell">Generated</th>
                    <th className="px-4 py-3 text-right font-medium text-muted-foreground">llms.txt</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job, i) => (
                    <tr
                      key={job.job_id}
                      className={i < jobs.length - 1 ? "border-b" : ""}
                    >
                      <td className="px-4 py-3">
                        <span className="font-medium">{formatDomain(job.url)}</span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground hidden sm:table-cell">
                        {job.page_count ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground hidden sm:table-cell">
                        {formatDate(job.created_at)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={`/result/${job.job_id}`}
                          className="text-foreground underline underline-offset-4 hover:opacity-70 transition-opacity"
                        >
                          view
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
