interface LlmsPreviewProps {
  content: string
}

function highlightLine(line: string, index: number) {
  if (line.startsWith("# ")) {
    return (
      <span key={index} className="block font-bold text-foreground text-lg">
        {line}
      </span>
    )
  }
  if (line.startsWith("## ")) {
    return (
      <span key={index} className="block font-semibold text-foreground mt-4">
        {line}
      </span>
    )
  }
  if (line.startsWith("> ")) {
    return (
      <span key={index} className="block text-muted-foreground border-l-2 border-border pl-3 my-2">
        {line.slice(2)}
      </span>
    )
  }
  if (line.startsWith("- [")) {
    const match = line.match(/^- \[([^\]]+)\]\(([^)]+)\)(.*)$/)
    if (match) {
      return (
        <span key={index} className="block">
          <span className="text-muted-foreground">- </span>
          <span className="text-foreground font-medium">{match[1]}</span>
          <span className="text-muted-foreground/60 text-xs"> ({match[2]})</span>
          <span className="text-muted-foreground">{match[3]}</span>
        </span>
      )
    }
  }
  if (line === "") {
    return <span key={index} className="block h-2" />
  }
  return (
    <span key={index} className="block text-muted-foreground">
      {line}
    </span>
  )
}

export function LlmsPreview({ content }: LlmsPreviewProps) {
  const lines = content.split("\n")

  return (
    <div className="rounded-lg border bg-muted/30 p-4 font-mono text-sm leading-relaxed overflow-auto max-h-[60vh]">
      {lines.map((line, i) => highlightLine(line, i))}
    </div>
  )
}
