import { useEffect, useMemo, useState } from "react"
import { AlertTriangle } from "lucide-react"
import type { SubscriptionFailureItem, SubscriptionSummary } from "../types/operations"
import { fetchSubscriptionFailures, fetchSubscriptionSummary } from "../services/operations"
import { PageHeader } from "../components/ui/PageHeader"
import { Card } from "../components/ui/Card"
import { EmptyState } from "../components/ui/EmptyState"
import { SkeletonTable } from "../components/ui/Skeleton"
import { formatINR, formatDateTime, initials } from "../lib/format"

const STATUS_TABS = [
  { key: "all", label: "All" },
  { key: "failed", label: "Failed" },
  { key: "retrying", label: "Retrying" },
  { key: "recovered", label: "Recovered" },
  { key: "churned", label: "Churned" },
]

const CAUSE_LABELS: Record<string, { label: string; color: string }> = {
  insufficient_funds: { label: "Insufficient Funds", color: "text-amber-400" },
  card_expired: { label: "Card Expired", color: "text-red-400" },
  mandate_issue: { label: "Mandate Issue", color: "text-orange-400" },
  bank_declined: { label: "Bank Declined", color: "text-red-400" },
  gateway_timeout: { label: "Gateway Timeout", color: "text-blue-400" },
  unknown: { label: "Unknown", color: "text-slate-400" },
}

const STATUS_COLORS: Record<string, string> = {
  failed: "bg-red-500/15 text-red-400 border-red-500/30",
  retrying: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  recovered: "bg-green-500/15 text-green-400 border-green-500/30",
  churned: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  cancelled: "bg-slate-500/15 text-slate-400 border-slate-500/30",
}

function ChurnBadge({ days }: { days: number | null }) {
  if (days === null) return <span className="text-[10px] text-ink-faint">—</span>
  if (days <= 1)
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-red-500/30 bg-red-500/15 px-2 py-0.5 text-[10px] font-semibold text-red-400">
        <AlertTriangle className="h-3 w-3" />
        {days}d left
      </span>
    )
  if (days <= 3)
    return (
      <span className="inline-flex rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-400">
        {days}d left
      </span>
    )
  return (
    <span className="inline-flex rounded-full border border-green-500/30 bg-green-500/15 px-2 py-0.5 text-[10px] text-green-400">
      {days}d left
    </span>
  )
}

function RetryBar({ count, max }: { count: number; max: number }) {
  const pct = max > 0 ? (count / max) * 100 : 0
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-panel-2">
        <div
          className="h-full rounded-full bg-amber-500 transition-all"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <span className="text-[10px] text-ink-faint">
        {count}/{max}
      </span>
    </div>
  )
}

export default function SubscriptionFailuresPage() {
  const [items, setItems] = useState<SubscriptionFailureItem[]>([])
  const [summary, setSummary] = useState<SubscriptionSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState("all")
  const [query, setQuery] = useState("")

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchSubscriptionFailures(), fetchSubscriptionSummary()])
      .then(([items, summary]) => {
        if (!cancelled) { setItems(items); setSummary(summary) }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const filtered = useMemo(() => {
    return items
      .filter((s) => statusFilter === "all" || s.status === statusFilter)
      .filter((s) => {
        if (!query.trim()) return true
        const q = query.toLowerCase()
        return (
          (s.customer_name ?? "").toLowerCase().includes(q) ||
          (s.customer_email ?? "").toLowerCase().includes(q) ||
          (s.plan_name ?? "").toLowerCase().includes(q) ||
          s.subscription_id.toLowerCase().includes(q)
        )
      })
      .sort((a, b) => Date.parse(b.created_at ?? "0") - Date.parse(a.created_at ?? "0"))
  }, [items, statusFilter, query])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Failed Subscription Recovery"
        subtitle={`${summary?.total ?? 0} failed subscriptions · ${summary?.retention_rate ?? 0}% retention rate · ${formatINR(summary?.total_amount ?? 0)} at risk`}
      />

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            { label: "Failed", value: summary.failed, color: "text-red-400" },
            { label: "Retrying", value: summary.retrying, color: "text-amber-400" },
            { label: "Recovered", value: summary.recovered, color: "text-green-400" },
            { label: "Churned", value: summary.churned, color: "text-slate-400" },
            { label: "Retention", value: `${summary.retention_rate}%`, color: "text-blue-400" },
          ].map((stat) => (
            <Card key={stat.label}>
              <p className="text-[11px] font-medium text-ink-faint">{stat.label}</p>
              <p className={`mt-1 text-lg font-bold ${stat.color}`}>{stat.value}</p>
            </Card>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1.5">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setStatusFilter(tab.key)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                statusFilter === tab.key
                  ? "border-blue-500/40 bg-blue-600/15 text-blue-400"
                  : "border-edge text-slate-400 hover:text-slate-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Search subscriptions..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="rounded-lg border border-edge bg-panel px-3 py-1.5 text-xs text-ink placeholder-ink-faint focus:border-royal focus:outline-none"
        />
      </div>

      {/* Table */}
      {loading ? (
        <SkeletonTable rows={5} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No subscription failures"
          description="Failed subscription renewals will appear here when customers' recurring payments fail."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-edge">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-edge bg-panel-2 text-[10px] uppercase tracking-wider text-ink-faint">
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Plan</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Cause</th>
                <th className="px-4 py-3">Retries</th>
                <th className="px-4 py-3">Churn Risk</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Failed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-edge">
              {filtered.map((item) => {
                const cause = CAUSE_LABELS[item.cause] ?? CAUSE_LABELS.unknown
                return (
                  <tr key={item.id} className="transition-colors hover:bg-white/[0.02]">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-panel-2 text-[10px] font-bold text-ink-muted">
                          {initials(item.customer_name)}
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-[12px] font-medium text-ink">
                            {item.customer_name || "Unknown"}
                          </p>
                          <p className="truncate text-[10px] text-ink-faint">
                            {item.customer_email || item.customer_phone || "—"}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-[12px] font-medium text-ink">
                        {item.plan_name || "—"}
                      </p>
                      <p className="text-[10px] text-ink-faint">
                        {item.billing_cycle || "—"}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-[12px] font-semibold text-ink">
                      {formatINR(item.amount)}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[11px] font-medium ${cause.color}`}>
                        {cause.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <RetryBar count={item.retry_count} max={item.max_retries} />
                    </td>
                    <td className="px-4 py-3">
                      <ChurnBadge days={item.days_until_churn} />
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_COLORS[item.status] ?? ""}`}>
                        {item.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[11px] text-ink-faint">
                      {formatDateTime(item.failed_at)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
