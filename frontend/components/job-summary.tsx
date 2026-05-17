interface JobSummaryProps {
  pageCount: number
  generationTimeMs?: number | null
}

export function JobSummary({ pageCount, generationTimeMs }: JobSummaryProps) {
  const seconds = generationTimeMs != null ? Math.round(generationTimeMs / 1000) : null

  return (
    <p className="text-sm text-muted-foreground">
      Generated from {pageCount} crawled {pageCount === 1 ? "page" : "pages"}
      {seconds != null ? ` in ${seconds}s` : ""}.
    </p>
  )
}
