"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { cancelJob } from "@/lib/api"

interface CancelButtonProps {
  jobId: string
}

export function CancelButton({ jobId }: CancelButtonProps) {
  const router = useRouter()
  const [confirming, setConfirming] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  if (cancelling) {
    return <p className="text-sm text-muted-foreground">Cancelling…</p>
  }

  if (confirming) {
    return (
      <div className="space-y-2">
        <p className="text-sm font-medium">Cancel this generation?</p>
        <p className="text-sm text-muted-foreground">
          You can start again from the same URL.
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setConfirming(false)}>
            Keep running
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={async () => {
              setCancelling(true)
              try {
                await cancelJob(jobId)
                router.push("/")
              } catch {
                setCancelling(false)
                setConfirming(false)
              }
            }}
          >
            Cancel generation
          </Button>
        </div>
      </div>
    )
  }

  return (
    <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setConfirming(true)}>
      Cancel
    </Button>
  )
}
