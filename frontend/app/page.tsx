import Link from "next/link"
import { Suspense } from "react"
import { HomeForm } from "@/components/home-form"

export default function HomePage() {
  return (
    <div className="min-h-screen bg-slate-50 px-6 py-8">
      <div className="mx-auto max-w-3xl">

        {/* Header */}
        <div className="mb-10">
          <div className="flex items-baseline justify-between">
            <h1 className="text-4xl font-bold tracking-tight text-slate-900 font-[family-name:var(--font-libre-baskerville)]">
              LLMs.txt Generator
            </h1>
            <Link
              href="/directory"
              className="text-sm text-slate-500 hover:text-slate-900 transition-colors"
            >
              Directory →
            </Link>
          </div>
          <p className="mt-1.5 text-slate-500">
            Generate AI-readable site maps from any public website
          </p>
        </div>

        {/* Form card */}
        <div className="rounded-2xl bg-white px-6 py-5 shadow-md">
          <Suspense>
            <HomeForm />
          </Suspense>
        </div>

        {/* Info section */}
        <div className="mt-10 grid gap-6 md:grid-cols-2 text-slate-600">
          <div className="space-y-4">
            <h2 className="text-xl font-bold text-slate-900">
              Generate an llms.txt from any website
            </h2>

            <p>
              Enter a URL and we&apos;ll crawl the site, identify the most important pages,
              and generate an AI-readable <code className="rounded bg-slate-100 px-1">llms.txt</code> file.
            </p>

            <div className="space-y-2">
              <p className="font-semibold text-slate-900">What happens:</p>
              <ul className="list-disc list-inside space-y-1">
                <li>Crawls public pages from your website</li>
                <li>Filters low-value and duplicate pages</li>
                <li>Ranks important docs, product pages, and resources</li>
                <li>Generates a structured llms.txt you can publish</li>
              </ul>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 font-mono text-xs text-slate-700 shadow-sm">
            <p className="text-slate-400 mb-3">Preview</p>
            <pre className="whitespace-pre-wrap">{`# Example Website

> Short description of what the site does.

## Docs
- Getting Started: /docs
- API Reference: /api
- Authentication: /docs/auth

## Product
- Pricing: /pricing
- Use Cases: /solutions`}</pre>
          </div>
        </div>

      </div>
    </div>
  )
}
