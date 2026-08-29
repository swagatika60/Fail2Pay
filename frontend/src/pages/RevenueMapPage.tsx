import { useDashboardStore } from "../hooks/dashboardStore"
import RevenueMapAnalytics from "../components/dashboard/RevenueMapAnalytics"
import { PageHeader } from "../components/ui/PageHeader"
import { Skeleton } from "../components/ui/Skeleton"

export default function RevenueMapPage() {
  const { map, loading, error } = useDashboardStore()

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