import { useEffect, useState } from "react"

import { fetchBackendStatus } from "./services/health"
import type { BackendStatus } from "./types/health"

const STATUS_STYLES: Record<BackendStatus, { dot: string; label: string }> = {
  checking: { dot: "bg-yellow-400", label: "Checking..." },
  connected: { dot: "bg-green-500", label: "Connected" },
  offline: { dot: "bg-red-500", label: "Offline" },
}

export default function App() {
  const [status, setStatus] = useState<BackendStatus>("checking")

  useEffect(() => {
    let cancelled = false

    fetchBackendStatus().then((result) => {
      if (!cancelled) setStatus(result)
    })

    return () => {
      cancelled = true
    }
  }, [])

  const style = STATUS_STYLES[status]

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-950 text-slate-100">
      <h1 className="text-5xl font-bold tracking-tight">Fail2Pay</h1>
      <p className="mt-3 text-lg text-slate-400">Autonomous Revenue Recovery</p>

      <div className="mt-8 flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900 px-4 py-2 text-sm">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${style.dot}`} />
        <span className="text-slate-300">Backend:</span>
        <span className="font-medium">{style.label}</span>
      </div>
    </main>
  )
}
