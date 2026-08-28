import { useEffect, useState } from "react"
import type { RevenueMap } from "../types/analytics"
import { fetchRevenueMap } from "../services/analytics"
import RevenueMapAnalytics from "../components/dashboard/RevenueMapAnalytics"
import { PageHeader } from "../components/ui/PageHeader"
import { Skeleton } from "../components/ui/Skeleton"

export default function RevenueMapPage() {
  const [map, setMap] = useState<RevenueMap | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchRevenueMap()
      .then((data) => {
        if (!cancelled) setMap(data)
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load revenue map")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <PageHeader
        title="Revenue Map"
        subtitle="At-risk, attempted, and verified recovered revenue. Recovered means money captured — nothing else."
      />
      {loading && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
            {Array.from({ length: 7 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-72 rounded-xl" />
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-red-800 bg-red-900/20 p-6 text-center text-red-400">
          {error}
        </div>
      )}
      {!loading && !error && map && <RevenueMapAnalytics data={map} />}
    </div>
  )
}