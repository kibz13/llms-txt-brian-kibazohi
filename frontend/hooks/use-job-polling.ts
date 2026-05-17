"use client"

import { useEffect, useRef, useState } from "react"
import { getJobStatus } from "@/lib/api"
import type { JobStatusResponse } from "@/lib/types"

export function useJobPolling(jobId: string) {
  const [data, setData] = useState<JobStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!jobId) return

    const stop = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }

    const poll = async () => {
      try {
        const result = await getJobStatus(jobId)
        setData(result)
        if (result.status === "done" || result.status === "error") {
          stop()
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unknown error")
        stop()
      }
    }

    poll()
    intervalRef.current = setInterval(poll, 2000)

    return stop
  }, [jobId])

  return { data, error }
}
