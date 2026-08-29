import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import type { PaymentPlanListItem } from "../types/operations"
import { fetchPaymentPlansList } from "../services/operations"
import { PageHeader } from "../components/ui/PageHeader"
import { Card } from "../components/ui/Card"
import { EmptyState } from "../components/ui/EmptyState"
import { StatusBadge } from "../components/ui/Badge"
import { ProgressBar } from "../components/ui/ProgressBar"
import { SkeletonTable } from "../components/ui/Skeleton"
import { PLAN_STATUS_META } from "../lib/status"
import { formatINR, formatDate, initials } from "../lib/format"
import RetrySequencerPanel from "../components/dashboard/RetrySequencerPanel"

function frequencyLabel(freq: string): string {
  const f = freq.toLowerCase()
  if (f === "weekly") return "Weekly"
  if (f === "biweekly") return "Bi-weekly"
  if (f === "monthly") return "Monthly"
  return freq
}

export default function PaymentPlansPage() {
  const [plans, setPlans] = useState<PaymentPlanListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string>("all")
  const [query, setQuery] = useState("")

  useEffect(() => {
    let cancelled = false
    fetchPaymentPlansList()
      .then((data) => {
        if (!cancelled) setPlans(data)
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load payment plans")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    return plans
      .filter((p) => (status === "all" ? true : p.status === status))
      .filter((p) => {
        if (!query.trim()) return true
        const q = query.trim().toLowerCase()
        return (p.customer_name ?? "").toLowerCase().includes(q)
      })
      .slice()
      .sort((a, b) => Date.parse(b.created_at ?? "0") - Date.parse(a.created_at ?? "0"))
  }, [plans, status, query])

  const activePlans = plans.filter((p) => p.status === "ACTIVE" || p.status === "ACCEPTED")
  const totalCollected = plans.reduce((s, p) => s + p.amount_paid, 0)
  const totalPlanned = plans.reduce((s, p) => s + p.total_amount, 0)

  const statusTabs = useMemo(() => {
    const counts: Record<string, number> = { all: plans.length }
    for (const p of plans) counts[p.status] = (counts[p.status] ?? 0) + 1
    return [
      { key: "all", label: "All", count: counts.all ?? 0 },
      { key: "ACTIVE", label: "Active", count: counts.ACTIVE ?? 0 },
      { key: "ACCEPTED", label: "Accepted", count: counts.ACCEPTED ?? 0 },
      { key: "PROPOSED", label: "Proposed", count: counts.PROPOSED ?? 0 },
      { key: "COMPLETED", label: "Completed", count: counts.COMPLETED ?? 0 },
      { key: "DEFAULTED", label: "Defaulted", count: counts.DEFAULTED ?? 0 },
      { key: "CANCELLED", label: "Cancelled", count: counts.CANCELLED ?? 0 },
    ]
  }, [plans])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payment Plans"
        subtitle={`${activePlans.length} plans active · ${formatINR(totalCollected)} of ${formatINR(totalPlanned)} collected across all plans`}
      />

      <div className="flex flex-wrap gap-1.5">
        {statusTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setStatus(tab.key)}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              status === tab.key
                ? "border-blue-500/40 bg-blue-600/15 text-blue-400"
                : "border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-300"
            }`}
          >
            {tab.label} <span className="ml-1 opacity-70">{tab.count}</span>
          </button>
        ))}
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search customer…"
          className="ml-auto w-full rounded-lg border border-slate-800 bg-slate-900 py-1.5 pl-3 pr-3 text-sm text-slate-200 placeholder:text-slate-600 sm:max-w-xs"
        />
      </div>

      {loading ? (
        <Card className="p-6">
          <SkeletonTable rows={7} />
        </Card>
      ) : error ? (
        <Card className="p-6 text-center text-red-400">{error}</Card>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="📅"
          title="No payment plans yet"
          description="When a customer agrees to pay in installments, the plan shows up here."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {filtered.map((plan) => {
            const meta = PLAN_STATUS_META[plan.status] ?? {
              label: plan.status,
              badge: "bg-slate-700/40 text-slate-300 border-slate-600/40",
              dot: "bg-slate-400",
              text: "text-slate-300",
            }
            const pctPaid = plan.progress.percent_paid
            return (
              <Card key={plan.id} className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-700 text-xs font-bold text-slate-200">
                      {initials(plan.customer_name)}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-200">
                        {plan.customer_name || "Unknown customer"}
                      </p>
                      <p className="text-xs text-slate-500">
                        {plan.number_of_installments}× {formatINR(plan.installment_amount)}{" "}
                        · {frequencyLabel(plan.frequency)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {plan.degradation?.degraded && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                        ⚠️ Mandate Degraded
                      </span>
                    )}
                    <StatusBadge meta={meta} />
                  </div>
                </div>

                <div className="mt-4 flex items-end justify-between">
                  <div>
                    <p className="text-2xl font-bold tracking-tight text-slate-100">
                      {formatINR(plan.total_amount)}
                    </p>
                    <p className="text-xs text-slate-500">
                      <span className="text-green-400">{formatINR(plan.amount_paid)}</span> collected
                    </p>
                  </div>
                  <div className="text-right text-sm">
                    <p className="font-semibold text-slate-200">{pctPaid.toFixed(0)}%</p>
                    <p className="text-xs text-slate-500">
                      {plan.progress.paid_installments}/{plan.progress.total_installments} installments
                    </p>
                  </div>
                </div>

                <ProgressBar
                  value={plan.amount_paid}
                  total={plan.total_amount}
                  className="mt-3"
                  barClassName={
                    plan.status === "DEFAULTED"
                      ? "bg-red-500"
                      : plan.status === "COMPLETED"
                        ? "bg-green-500"
                        : "bg-blue-500"
                  }
                />

                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                  <span>
                    Created {formatDate(plan.created_at)}
                    {plan.last_payment_date &&
                      ` · last due ${formatDate(plan.last_payment_date)}`}
                  </span>
                  {plan.progress.failed_installments > 0 && (
                    <span className="font-medium text-red-400">
                      {plan.progress.failed_installments} missed
                    </span>
                  )}
                </div>

                {plan.case_id && (
                  <div className="mt-3 border-t border-slate-800 pt-2.5">
                    <Link
                      to={`/case/${plan.case_id}`}
                      className="text-xs font-medium text-blue-400 hover:text-blue-300"
                    >
                      View recovery case →
                    </Link>
                  </div>
                )}

                <RetrySequencerPanel
                  planId={plan.id}
                  degraded={plan.degradation?.degraded}
                  strategyLabel={plan.degradation?.strategy_label}
                  strategy={plan.degradation?.strategy}
                />
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}