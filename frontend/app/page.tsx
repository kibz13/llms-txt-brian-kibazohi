import { Suspense } from "react"
import { HomeForm } from "@/components/home-form"

export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b px-6 py-4">
        <span className="font-semibold tracking-tight">llms.txt</span>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-16">
        <div className="w-full max-w-xl space-y-8">
          <div className="space-y-2">
            <h1 className="text-3xl font-bold tracking-tight">Generate llms.txt</h1>
            <p className="text-muted-foreground">
              Crawl any website and generate a spec-compliant{" "}
              <a
                href="https://llmstxt.org"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-4"
              >
                llms.txt
              </a>{" "}
              file.
            </p>
          </div>

          <Suspense>
            <HomeForm />
          </Suspense>
        </div>
      </main>
    </div>
  )
}
