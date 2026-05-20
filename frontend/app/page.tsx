import Link from "next/link"
import { Suspense } from "react"
import { HomeForm } from "@/components/home-form"
import { FolderOpen } from "lucide-react"

export default function HomePage() {
  return (
    <div className="min-h-screen bg-slate-50 px-6 py-8">
      <div className="mx-auto max-w-3xl">

        {/* Header */}
        <div className="relative flex justify-center mb-10">
          <div className="text-center">
            <h1 className="text-4xl font-bold tracking-tight text-slate-900 font-[family-name:var(--font-libre-baskerville)]">
              LLMs.txt Generator
            </h1>
            <p className="mt-1.5 text-slate-500">
              Create optimized documentation for AI models
            </p>
          </div>
          <Link
            href="/directory"
            className="absolute right-0 top-0 flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 transition-colors"
          >
            <FolderOpen className="h-4 w-4" />
            Directory
          </Link>
        </div>

        {/* Form card */}
        <div className="rounded-2xl bg-white px-6 py-5 shadow-md">
          <Suspense>
            <HomeForm />
          </Suspense>
        </div>

        {/* Info section */}
        <div className="mt-10 space-y-4 text-slate-600">
          <h2 className="text-xl font-bold text-slate-900">
            Make Your Website AI-Ready in Minutes
          </h2>
          <p>
            Want AI assistants like ChatGPT and Claude to talk about your website accurately?
            We&apos;ve got you covered.
          </p>
          <p>
            Our generator creates a special file that helps AI understand your site better.
            Think of it as giving AI a roadmap to your content.
          </p>
          <div className="space-y-2">
            <p className="font-semibold text-slate-900">What you&apos;ll get:</p>
            <ul className="list-disc list-inside space-y-1">
              <li>AI assistants will share accurate info about your site</li>
              <li>Better visibility when people ask AI about topics you cover</li>
              <li>Your content presented the way you want it</li>
              <li>Stay ahead of the curve as more people use AI for search</li>
            </ul>
          </div>
          <p>
            Join thousands of websites already optimized for the AI era. Just enter your URL
            and we&apos;ll handle the rest.
          </p>
        </div>

      </div>
    </div>
  )
}
