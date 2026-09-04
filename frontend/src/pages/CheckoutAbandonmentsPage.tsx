import { useEffect, useMemo, useState } from "react"
import type { CheckoutAbandonmentItem, CheckoutSummary } from "../types/operations"
import { fetchCheckoutAbandonments, fetchCheckoutSummary } from "../services/operations"
import { PageHeader } from "../components/ui/PageHeader"
import { Card } from "../components/ui/Card"
import { EmptyState } from "../components/ui/EmptyState"
import { SkeletonTable } from "../components/ui/Skeleton"
import { formatINR, formatDateTime, initials } from "../lib/format"

const STATUS_TABS = [
  { key: "all", label: "All" },
  { key: "abandoned", label: "Abandoned" },
  { key: "recovering", label: "Recovering" },
  { key: "recovered", label: "Recovered" },
  { key: "lost", label: "Lost" },
]

const CAUSE_LABELS: Record<string, { label: string; color: string }> = {
  payment_failure: { label: "Payment Failed", color: "text-red-400" },
  price_hesitation: { label: "Price Hesitation", color: "text-amber-400" },
  distraction: { label: "Distraction", color: "text-blue-400" },
  comparison_shopping: { label: "Comparison", color: "text-purple-400" },
  ux_friction: { label: "UX Friction", color: "text-orange-400" },
  unknown: { label: "Unknown", color: "text-slate-400" },
}

const STATUS_COLORS: Record<string, string> = {
  abandoned: "bg-red-500/15 text-red-400 border-red-500/30",
  recovering: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  recovered: "bg-green-500/15 text-green-400 border-green-500/30",
  lost: "bg-slate-500/15 text-slate-400 border-slate-500/30",
}

export default function CheckoutAbandonmentsPage() {
  const [items, setItems] = useState<CheckoutAbandonmentItem[]>([])
  const [summary, setSummary] = useState<CheckoutSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState("all")
  const [query, setQuery] = useState("")

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchCheckoutAbandonments(), fetchCheckoutSummary()])
      .then(([items, summary]) => {
        if (!cancelled) { setItems(items); setSummary(summary) }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const filtered = useMemo(() => {
    return items
      .filter((c) => statusFilter === "all" || c.status === statusFilter)
      .filter((c) => {
        if (!query.trim()) return true
        const q = query.toLowerCase()
        return (
          (c.customer_name ?? "").toLowerCase().includes(q) ||
          (c.customer_email ?? "").toLowerCase().includes(q) ||
          c.cart_ref.toLowerCase().includes(q)
        )
      })
      .sort((a, b) => Date.parse(b.created_at ?? "0") - Date.parse(a.created_at ?? "0"))
  }, [items, statusFilter, query])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Checkout Drop-off Recovery"
        subtitle={`${summary?.total ?? 0} abandoned carts · ${summary?.recovery_rate ?? 0}% recovery rate · ${formatINR(summary?.total_amount ?? 0)} at risk`}
      />

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            { label: "Abandoned", value: summary.abandoned, color: "text-red-400" },
            { label: "Recovering", value: summary.recovering, color: "text-amber-400" },
            { label: "Recovered", value: summary.recovered, color: "text-green-400" },
            { label: "Lost", value: summary.lost, color: "text-slate-400" },
            { label: "Recovery Rate", value: `${summary.recovery_rate}%`, color: "text-blue-400" },
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
          placeholder="Search carts..."
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
          title="No checkout abandonments"
          description="Abandoned carts will appear here when customers leave during checkout."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-edge">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-edge bg-panel-2 text-[10px] uppercase tracking-wider text-ink-faint">
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Cart</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Cause</th>
                <th className="px-4 py-3">Re-engagements</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Abandoned</th>
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
                    <td className="px-4 py-3 font-mono text-[11px] text-ink-muted">
                      {item.cart_ref.slice(0, 12)}
                    </td>
                    <td className="px-4 py-3 text-[12px] font-semibold text-ink">
                      {formatINR(item.amount)}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[11px] font-medium ${cause.color}`}>
                        {cause.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center text-[12px] text-ink-muted">
                      {item.reengagement_count}
                      {item.reengagement_channel && (
                        <span className="ml-1 text-[9px] text-ink-faint">
                          ({item.reengagement_channel})
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_COLORS[item.status] ?? ""}`}>
                        {item.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[11px] text-ink-faint">
                      {formatDateTime(item.abandoned_at)}
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
