import type { JobStatusResponse } from "@/lib/types"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL

function log(method: string, url: string, status?: number, body?: unknown) {
  const parts = [`[api] ${method} ${url}`]
  if (status !== undefined) parts.push(`→ ${status}`)
  if (body !== undefined) parts.push(JSON.stringify(body))
  console.log(parts.join("  "))
}

export async function submitJob(
  url: string,
  depth: number
): Promise<{ job_id: string; status: string }> {
  const endpoint = `${API_BASE}/jobs`
  log("POST", endpoint, undefined, { url, depth })
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, depth }),
  })
  if (!res.ok) {
    const text = await res.text()
    log("POST", endpoint, res.status, text)
    throw new Error(text || `Request failed with status ${res.status}`)
  }
  const data = await res.json()
  log("POST", endpoint, res.status, data)
  return data
}

export interface JobListItem {
  job_id: string
  url: string
  page_count: number | null
  created_at: string
}

export async function listJobs(): Promise<JobListItem[]> {
  const endpoint = `${API_BASE}/jobs`
  log("GET", endpoint)
  const res = await fetch(endpoint)
  if (!res.ok) {
    const text = await res.text()
    log("GET", endpoint, res.status, text)
    throw new Error(text || `Request failed with status ${res.status}`)
  }
  const data = await res.json()
  log("GET", endpoint, res.status, { count: data.length })
  return data
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  const endpoint = `${API_BASE}/jobs/${jobId}`
  log("GET", endpoint)
  const res = await fetch(endpoint)
  if (!res.ok) {
    const text = await res.text()
    log("GET", endpoint, res.status, text)
    throw new Error(text || `Request failed with status ${res.status}`)
  }
  const data = await res.json()
  log("GET", endpoint, res.status, data)
  return data
}
