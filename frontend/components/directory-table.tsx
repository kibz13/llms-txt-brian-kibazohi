"use client"

import { useState } from "react"
import Link from "next/link"
import { Search } from "lucide-react"
import type { JobListItem } from "@/lib/api"

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

function formatTokens(total: number | null): string {
  if (!total) return "—"
  if (total >= 1000) return `${(total / 1000).toFixed(1)}k`
  return String(total)
}

export function DirectoryTable({ jobs }: { jobs: JobListItem[] }) {
  const [query, setQuery] = useState("")

  const filtered = query.trim()
    ? jobs.filter(j => formatDomain(j.url).includes(query.trim().toLowerCase()))
    : jobs

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 border border-border/50 px-3 py-2">
        <Search className="h-4 w-4 text-muted-foreground flex-shrink-0" />
        <input
          placeholder="Search domains..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          className="bg-transparent outline-none text-sm w-full font-medium text-slate-900 placeholder:text-slate-400 font-[family-name:var(--font-geist-sans)]"
        />
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8 text-center font-mono">
          No results for &ldquo;{query}&rdquo;.
        </p>
      ) : (
        <div className="border border-border/40 overflow-hidden">
          <table className="w-full text-sm font-mono">
            <thead>
              <tr className="border-b border-border/40 bg-muted/30">
                <th className="px-4 py-1.5 text-left font-medium text-muted-foreground">Site</th>
                <th className="px-4 py-1.5 text-left font-medium text-muted-foreground hidden sm:table-cell">Pages</th>
                <th className="px-4 py-1.5 text-left font-medium text-muted-foreground hidden sm:table-cell">Tokens</th>
                <th className="px-4 py-1.5 text-left font-medium text-muted-foreground hidden sm:table-cell">Generated</th>
                <th className="px-4 py-1.5 text-right font-medium text-muted-foreground">llms.txt</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((job, i) => (
                <tr
                  key={job.job_id}
                  className={`hover:bg-muted/30 transition-colors${i < filtered.length - 1 ? " border-b border-border/40" : ""}`}
                >
                  <td className="px-4 py-1.5 font-medium">
                    <Link href={`/result/${job.job_id}`} className="hover:underline underline-offset-4">
                      {formatDomain(job.url)}
                    </Link>
                  </td>
                  <td className="px-4 py-1.5 text-muted-foreground hidden sm:table-cell">{job.page_count ?? "—"}</td>
                  <td className="px-4 py-1.5 text-muted-foreground hidden sm:table-cell">{formatTokens(job.total_tokens)}</td>
                  <td className="px-4 py-1.5 text-muted-foreground hidden sm:table-cell">{formatDate(job.created_at)}</td>
                  <td className="px-4 py-1.5 text-right">
                    <Link
                      href={`/result/${job.job_id}`}
                      className="underline underline-offset-4 hover:opacity-70 transition-opacity"
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
  )
}
