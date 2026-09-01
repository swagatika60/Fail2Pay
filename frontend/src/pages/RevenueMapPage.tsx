import { useMemo } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Ban,
  Layers,
  MessageSquare,
  Percent,
} from "lucide-react"
import { useDashboardStore } from "../hooks/dashboardStore"
import RevenueMapAnalytics from "../components/dashboard/RevenueMapAnalytics"
import MetricStatCard from "../components/dashboard/MetricStatCard"
import RecoveryPipelineTracker, {
  type RecoveryPipelineStage,
} from "../components/dashboard/RecoveryPipelineTracker"
import ReconciliationProgress from "../components/dashboard/ReconciliationProgress"
import { Skeleton } from "../components/ui/Skeleton"
import { formatINR, formatPercent } from "../lib/format"
import type { RevenueMap } from "../types/analytics"

/**
 * Build the 6-stage revenue-map pipeline from the analytics snapshot.
 * Contacted/Engaged are derived from the attempted pool since the revenue
 * map tracks money, not per-stage case tallies; per-stage case counts come
 * from the derived recovery pipeline where available.
 */
function buildStages(map: RevenueMap): RecoveryPipelineStage[] {
  const byStage = new Map((map.recovery_pipeline ?? []).map((s) => [s.stage, s]))
  const countFor = (...keys: string[]) =>
    keys.reduce((acc, key) => acc || byStage.get(key)?.count || 0, 0)

  const attempted = map.attempted_recovery
  const recovered = map.recovered_revenue
  const promised = map.promise_to_pay_recovery.promised_amount ?? 0
  const planTotal = map.payment_plan_recovery.total_amount ?? 0

  return [
    {
      key: "at_risk",
      label: "At Risk",
      amount: map.at_risk_revenue,
      count: countFor("FAILED"),
    },
    {
      key: "contacted",
      label: "Contacted",
      amount: Math.max(attempted - recovered - promised - planTotal, 0),
      count: countFor("CONTACTED"),
    },
    {
      key: "engaged",
      label: "Engaged",
      amount: Math.max(attempted - recovered, 0),
      count: countFor("ENGAGED"),
    },
    {
      key: "promised",
      label: "Promised",
      amount: promised,
      count: countFor("PROMISED") || (map.promise_to_pay_recovery.promised_cases ?? 0),
    },
    {
      key: "payment_plan",
      label: "Payment Plan",
      amount: planTotal,
      count: map.payment_plan_recovery.plans_count ?? 0,
    },
    {
      key: "recovered",
      label: "Recovered",
      amount: recovered,
      count: countFor("RECOVERED") || (map.payments_count ?? 0),
    },
  ]
}

export default function RevenueMapPage() {
  const { map, loading, error } = useDashboardStore()

  const stages = useMemo(() => (map ? buildStages(map) : []), [map])

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-6">
      {/* Page header */}
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-100">Revenue Map</h1>
          <p className="mt-1 text-xs text-slate-500">
            Full pipeline view from at-risk through recovery — verified captured payments only.
          </p>
        </div>
        {map && !loading ? (
          <span className="rounded-full border border-edge bg-panel px-2.5 py-1 font-mono text-[10px] tabular-nums text-slate-400">
            {formatINR(map.recovered_revenue)} settled · {formatPercent(map.recovery_rate)} yield
          </span>
        ) : null}
      </div>

      {loading && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
            {Array.from({ length: 7 }).map((_, i) => (
              <Skeleton key={i} className="h-[92px] rounded-lg" />
            ))}
          </div>
          <Skeleton className="h-40 rounded-xl" />
          <Skeleton className="h-56 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-800/60 bg-rose-900/20 p-6 text-center text-sm text-rose-400">
          {error}
        </div>
      )}

      {!loading && !error && map && (
        <div className="space-y-4">
          {/* 7-metric KPI strip */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
            <MetricStatCard
              label="Total Failed Volume"
              value={formatINR(map.total_revenue)}
              subtitle="All initial failures"
              icon={<Layers className="h-3.5 w-3.5" />}
            />
            <MetricStatCard
              label="At-Risk Revenue"
              value={formatINR(map.at_risk_revenue)}
              subtitle="Active open cases"
              tone="amber"
              icon={<AlertTriangle className="h-3.5 w-3.5" />}
            />
            <MetricStatCard
              label="Verified Recovered"
              value={formatINR(map.recovered_revenue)}
              subtitle={`${map.payments_count} captured payments`}
              tone="emerald"
              icon={<CheckCircle2 className="h-3.5 w-3.5" />}
            />
            <MetricStatCard
              label="Lost / Opted Out"
              value={formatINR(map.lost_revenue)}
              subtitle="Closed · unrecoverable"
              tone="rose"
              icon={<Ban className="h-3.5 w-3.5" />}
            />
            <MetricStatCard
              label="Recovery Yield"
              value={formatPercent(map.recovery_rate)}
              subtitle="Settled ÷ total failed"
              tone="emerald"
              icon={<Percent className="h-3.5 w-3.5" />}
            />
            <MetricStatCard
              label="Avg Recovery Velocity"
              value={`${map.avg_recovery_time_days.toFixed(1)}d`}
              subtitle="Failure → settlement"
              icon={<Clock className="h-3.5 w-3.5" />}
            />
            <MetricStatCard
              label="Avg Touchpoints"
              value={map.avg_attempts_before_recovery.toFixed(1)}
              subtitle="Attempts per case"
              icon={<MessageSquare className="h-3.5 w-3.5" />}
            />
          </div>

          {/* Pipeline + reconciliation */}
          <RecoveryPipelineTracker
            stages={stages}
            totalCases={map.cases_count}
            footer={
              <p className="text-[10px] text-zinc-600">
                Pipeline amounts reconcile verified captured revenue only; stage counts derive from
                the recovery state machine.
              </p>
            }
          />

          <ReconciliationProgress
            total={map.total_revenue}
            settled={map.recovered_revenue}
            inPipeline={map.at_risk_revenue}
            unrecoverable={map.lost_revenue}
            attempted={map.attempted_recovery}
            outstanding={map.attempted_unfulfilled}
            capturedPayments={map.payments_count}
          />

          {/* Charts */}
          <RevenueMapAnalytics data={map} />
        </div>
      )}
    </div>
  )
}