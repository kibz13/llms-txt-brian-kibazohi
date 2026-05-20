"use client"

import { Check } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import type { JobStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

interface StatusIndicatorProps {
  status: JobStatus
  url: string
  pageCount?: number | null
}

type StepState = "complete" | "active" | "pending"

const STEPS = ["Crawling", "Classifying", "Generating", "Done"]

const CONNECTOR_MESSAGES: string[][] = [
  ["Reading robots.txt", "Checking sitemap", "Fetching pages"],
  ["Detecting page types", "Scoring important pages", "Filtering duplicates"],
  ["Building sections", "Writing summary", "Formatting llms.txt"],
]

const LOG_LINES: Record<JobStatus, string[]> = {
  queued:     ["Preparing crawl…"],
  crawling:   ["Fetching robots.txt", "Sitemap found", "Fetching public pages", "Removing duplicate URLs", "Scoring page importance"],
  generating: ["Classifying page types", "Filtering low-value pages", "Scoring documentation pages", "Preparing generation payload", "Sending to Claude", "Formatting llms.txt"],
  done:       ["Done"],
  error:      ["Error encountered"],
}

function getStepStates(status: JobStatus): StepState[] {
  switch (status) {
    case "queued":
    case "crawling":
      return ["active", "pending", "pending", "pending"]
    case "generating":
      return ["complete", "complete", "active", "pending"]
    case "done":
      return ["complete", "complete", "complete", "complete"]
    case "error":
      return ["pending", "pending", "pending", "pending"]
    default:
      return ["pending", "pending", "pending", "pending"]
  }
}

function getStatusTitle(status: JobStatus): string {
  if (status === "queued")     return "Preparing crawl"
  if (status === "crawling")   return "Reading website content"
  if (status === "generating") return "Generating llms.txt"
  return "Processing"
}

function useCycling(messages: string[], intervalMs = 2000) {
  const [index, setIndex] = useState(0)
  const [visible, setVisible] = useState(true)
  const tidRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setIndex(0)
    setVisible(true)
  }, [messages])

  useEffect(() => {
    const id = setInterval(() => {
      setVisible(false)
      tidRef.current = setTimeout(() => {
        setIndex(prev => (prev + 1) % messages.length)
        setVisible(true)
      }, 200)
    }, intervalMs)
    return () => {
      clearInterval(id)
      if (tidRef.current) clearTimeout(tidRef.current)
    }
  }, [messages, intervalMs])

  return { message: messages[index], visible }
}

function CyclingLabel({ messages, className }: { messages: string[]; className?: string }) {
  const { message, visible } = useCycling(messages)
  return (
    <span
      className={cn(
        "transition-opacity duration-200 select-none",
        visible ? "opacity-100" : "opacity-0",
        className,
      )}
    >
      {message}
    </span>
  )
}

function useActivityLog(status: JobStatus) {
  const [lines, setLines] = useState<string[]>([])
  const seenStatus = useRef<Set<JobStatus>>(new Set())
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (seenStatus.current.has(status)) return
    seenStatus.current.add(status)

    const newLines = LOG_LINES[status] ?? []
    let i = 0

    function revealNext() {
      if (i >= newLines.length) return
      setLines(prev => [...prev, newLines[i]])
      i++
      timerRef.current = setTimeout(revealNext, 900)
    }

    revealNext()
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [status])

  return lines
}

function StepList({ states }: { states: StepState[] }) {
  return (
    <div className="flex flex-col">
      {STEPS.map((label, i) => {
        const state = states[i]
        const isLast = i === STEPS.length - 1

        return (
          <div key={label}>
            <div className="flex items-center gap-3">
              <div className="relative flex-shrink-0 h-8 w-8">
                {state === "active" && (
                  <span className="absolute inset-0 rounded-full ring-[3px] ring-blue-400 animate-pulse" />
                )}
                <div
                  className={cn(
                    "absolute inset-0 flex items-center justify-center rounded-full border-2 text-xs font-semibold transition-all duration-300",
                    state === "complete" && "border-blue-600 bg-blue-600 text-white",
                    state === "active"   && "border-blue-600 bg-white text-blue-600",
                    state === "pending"  && "border-slate-200 bg-white text-slate-400",
                  )}
                >
                  {state === "complete" ? (
                    <Check className="h-4 w-4" />
                  ) : state === "active" ? (
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-600 opacity-75" />
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-blue-600" />
                    </span>
                  ) : (
                    <span>{i + 1}</span>
                  )}
                </div>
              </div>

              <span
                className={cn(
                  "text-sm font-medium",
                  state === "complete" && "text-blue-600",
                  state === "active"   && "text-slate-900",
                  state === "pending"  && "text-slate-400",
                )}
              >
                {label}
              </span>
            </div>

            {!isLast && (
              <div className="ml-[15px] flex gap-4 min-h-10 py-1">
                <div
                  className={cn(
                    "w-0.5 self-stretch",
                    state === "complete" ? "bg-blue-600" : "bg-slate-200",
                  )}
                />
                {state === "active" && (
                  <div className="flex items-center">
                    <CyclingLabel
                      messages={CONNECTOR_MESSAGES[i]}
                      className="text-xs font-medium text-blue-500"
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function LivePanel({ status, url, pageCount }: StatusIndicatorProps) {
  const logLines = useActivityLog(status)
  const isActive = status === "crawling" || status === "generating" || status === "queued"

  return (
    <div className="space-y-4">
      {/* Status title */}
      <p className="text-sm font-semibold text-slate-800">{getStatusTitle(status)}</p>

      {/* URL */}
      <div className="rounded-lg border bg-slate-50 px-3 py-2 text-sm font-mono text-slate-600 truncate">
        {url}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
          <p className="text-slate-400 mb-0.5">Pages discovered</p>
          <p className="font-mono font-medium text-slate-700">{pageCount != null ? pageCount : "—"}</p>
        </div>
        <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
          <p className="text-slate-400 mb-0.5">Output</p>
          <p className="font-mono font-medium text-slate-700">llms.txt</p>
        </div>
      </div>

      {/* Activity log */}
      {isActive && logLines.length > 0 && (
        <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 space-y-1">
          {logLines.slice(-5).map((line, i) => (
            <p key={i} className="text-xs font-mono text-slate-500">{line}</p>
          ))}
        </div>
      )}
    </div>
  )
}

export function StatusIndicator({ status, url, pageCount }: StatusIndicatorProps) {
  const states = getStepStates(status)

  return (
    <div className="grid gap-8 md:grid-cols-[240px_1fr]">
      <StepList states={states} />
      <LivePanel status={status} url={url} pageCount={pageCount} />
    </div>
  )
}
