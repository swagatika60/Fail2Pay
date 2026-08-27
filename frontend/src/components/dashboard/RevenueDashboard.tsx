import { useEffect, useState } from "react"
import type { RevenueSummary, RecoveryCaseSummary } from "../../types/analytics"
import {
  fetchRevenueSummary,
  fetchRecoveryCases,
} from "../../services/analytics"
import MetricCard from "./MetricCard"
import RevenueFlow from "./RevenueFlow"
import RecoveryTable from "./RecoveryTable"
import CaseDetailModal from "./CaseDetailModal"

function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}

export default function RevenueDashboard() {
  const [summary, setSummary] = useState<RevenueSummary | null>(null)
  const [cases, setCases] = useState<RecoveryCaseSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const [summaryData, casesData] = await Promise.all([
          fetchRevenueSummary(),
          fetchRecoveryCases(),
        ])
        setSummary(summaryData)
        setCases(casesData)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load data")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <div className="flex flex-col items-center gap-4">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
          <p className="text-slate-400">Loading revenue data...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <div className="rounded-xl border border-red-800 bg-red-900/20 p-6 text-center">
          <p className="text-lg font-semibold text-red-400">
            Failed to load dashboard
          </p>
          <p className="mt-2 text-sm text-slate-400">{error}</p>
        </div>
      </div>
    )
  }

  if (!summary) return null

  return (
    <div className="min-h-screen bg-slate-950 p-6 text-slate-100">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Revenue Map</h1>
        <p className="mt-1 text-slate-400">
          Real-time revenue recovery dashboard
        </p>
      </div>

      {/* Top metrics row */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
        <MetricCard
          title="Total Revenue"
          value={summary.total_revenue}
          color="text-blue-400"
          subtitle="All expected revenue"
        />
        <MetricCard
          title="Revenue At Risk"
          value={summary.revenue_at_risk}
          color="text-red-400"
          subtitle="Failed payments pending recovery"
        />
        <MetricCard
          title="Revenue Recovered"
          value={summary.revenue_recovered}
          color="text-green-400"
          subtitle="Successfully recovered"
        />
        <MetricCard
          title="Revenue Remaining"
          value={summary.revenue_remaining}
          color="text-amber-400"
          subtitle="Still to be recovered"
        />
        <MetricCard
          title="Recovery Rate"
          value={0}
          color="text-emerald-400"
          subtitle={formatPercent(summary.recovery_rate)}
        />
      </div>

      {/* Second metrics row */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <MetricCard
          title="Expected"
          value={summary.expected_revenue}
          color="text-blue-400"
        />
        <MetricCard
          title="Collected"
          value={summary.collected_revenue}
          color="text-green-400"
        />
        <MetricCard
          title="In Progress"
          value={summary.recovery_in_progress}
          color="text-amber-400"
        />
        <MetricCard
          title="Promised"
          value={summary.promised_revenue}
          color="text-purple-400"
        />
        <MetricCard
          title="Partially Recovered"
          value={summary.partially_recovered}
          color="text-yellow-400"
        />
        <MetricCard
          title="Lost"
          value={summary.lost_revenue}
          color="text-gray-400"
        />
      </div>

      {/* Revenue flow chart */}
      <div className="mb-6">
        <RevenueFlow data={summary} />
      </div>

      {/* Recovery table */}
      <RecoveryTable
        cases={cases}
        onSelectCase={(id) => setSelectedCaseId(id)}
      />

      {/* Case detail modal */}
      <CaseDetailModal
        caseId={selectedCaseId}
        onClose={() => setSelectedCaseId(null)}
      />
    </div>
  )
}
