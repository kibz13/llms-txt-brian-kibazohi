import type { JobStatusResponse } from "@/lib/types"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL

export async function submitJob(
  url: string,
  depth: number
): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, depth }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed with status ${res.status}`)
  }
  return res.json()
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed with status ${res.status}`)
  }
  return res.json()
}
