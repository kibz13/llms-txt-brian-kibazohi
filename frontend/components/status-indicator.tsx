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

// Messages that cycle in the connector below each active step
const CONNECTOR_MESSAGES: string[][] = [
  ["Normalizing", "Filtering", "Crawling"],        // below Crawling
  ["Classifying", "Grouping"],                     // below Classifying
  ["Thinking", "More thinking", "Deep thinking"],  // below Generating
]

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

function getActivityMessages(status: JobStatus, pageCount: number | null | undefined): string[] {
  switch (status) {
    case "queued":
      return ["Queued", "Starting up"]
    case "crawling": {
      const base = ["Sitemap found", "Fetching content"]
      if (pageCount) base.splice(1, 0, `Crawling ${pageCount} pages`)
      return base
    }
    case "generating":
      return ["Classifying pages", "Talking to AI", "Thinking", "Almost done"]
    default:
      return ["Processing"]
  }
}

function CyclingLabel({ messages }: { messages: string[] }) {
  const [index, setIndex] = useState(0)
  const [visible, setVisible] = useState(true)
  const tidRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const id = setInterval(() => {
      setVisible(false)
      tidRef.current = setTimeout(() => {
        setIndex(prev => (prev + 1) % messages.length)
        setVisible(true)
      }, 200)
    }, 1800)
    return () => {
      clearInterval(id)
      if (tidRef.current) clearTimeout(tidRef.current)
    }
  }, [messages])

  return (
    <span
      className={cn(
        "text-xs font-medium text-blue-500 transition-opacity duration-200 select-none",
        visible ? "opacity-100" : "opacity-0",
      )}
    >
      {messages[index]}
    </span>
  )
}

export function StatusIndicator({ status, url, pageCount }: StatusIndicatorProps) {
  const states = getStepStates(status)
  const activityMessages = getActivityMessages(status, pageCount)

  return (
    <div className="space-y-6">
      {/* Step list */}
      <div className="flex flex-col">
        {STEPS.map((label, i) => {
          const state = states[i]
          const isLast = i === STEPS.length - 1

          return (
            <div key={label}>
              {/* Step row */}
              <div className="flex items-center gap-3">
                {/* Circle */}
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

                {/* Label */}
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

              {/* Connector */}
              {!isLast && (
                <div className="ml-[15px] flex gap-4 min-h-10 py-1">
                  {/* Vertical line */}
                  <div
                    className={cn(
                      "w-0.5 self-stretch",
                      state === "complete" ? "bg-blue-600" : "bg-slate-200",
                    )}
                  />
                  {/* Cycling message — shown while this step is active */}
                  {state === "active" && (
                    <div className="flex items-center">
                      <CyclingLabel messages={CONNECTOR_MESSAGES[i]} />
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* URL */}
      <div className="text-sm text-slate-500">
        <span className="text-slate-400">URL: </span>{url}
      </div>

      {/* Activity feed */}
      {(status === "crawling" || status === "generating" || status === "queued") && (
        <div className="rounded-lg bg-slate-50 border border-slate-100 px-4 py-3 text-sm">
          <CyclingLabel messages={activityMessages} />
        </div>
      )}
    </div>
  )
}
