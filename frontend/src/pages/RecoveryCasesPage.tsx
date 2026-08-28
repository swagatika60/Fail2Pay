import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import type { RecoveryCaseSummary } from "../types/analytics"
import { fetchRecoveryCases } from "../services/analytics"
import { PageHeader } from "../components/ui/PageHeader"
import { Card } from "../components/ui/Card"
import { EmptyState } from "../components/ui/EmptyState"
import { StatusBadge } from "../components/ui/Badge"
import { SkeletonTable } from "../components/ui/Skeleton"
import { caseMeta, riskMeta } from "../lib/status"
import { formatINR, formatDateTime, initials } from "../lib/format"

const STATUS_TABS: { key: string; label: string }[] = [
  { key: "all", label: "All" },
  { key: "AT_RISK", label: "At Risk" },
  { key: "RECOVERY_IN_PROGRESS", label: "In Progress" },
  { key: "PROMISED", label: "Promised" },
  { key: "SCHEDULED", label: "Scheduled" },
  { key: "PARTIALLY_RECOVERED", label: "Partially Recovered" },
  { key: "RECOVERED", label: "Recovered" },
  { key: "LOST", label: "Lost" },
  { key: "STOPPED", label: "Stopped" },
]

const RISKS = ["all", "HIGH", "MEDIUM", "LOW"]

export default function RecoveryCasesPage() {
  const [cases, setCases] = useState<RecoveryCaseSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string>("all")
  const [risk, setRisk] = useState<string>("all")
  const [query, setQuery] = useState("")

  useEffect(() => {
    let cancelled = false
    fetchRecoveryCases()
      .then((data) => {
        if (!cancelled) setCases(data)
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load cases")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    return cases
      .filter((c) => (status === "all" ? true : c.status === status))
      .filter((c) => (risk === "all" ? true : c.risk_level === risk))
      .filter((c) => {
        if (!query.trim()) return true
        const q = query.trim().toLowerCase()
        return (
          (c.customer_name ?? "").toLowerCase().includes(q) ||
          (c.customer_email ?? "").toLowerCase().includes(q)
        )
      })
      .slice()
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  }, [cases, status, risk, query])

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: cases.length }
    for (const c of cases) m[c.status] = (m[c.status] ?? 0) + 1
    return m
  }, [cases])

  const totalOutstanding = filtered.reduce((sum, c) => sum + c.remaining_amount, 0)
  const totalRecovered = filtered.reduce((sum, c) => sum + c.recovered_amount, 0)
  const totalOriginal = filtered.reduce((sum, c) => sum + c.original_amount, 0)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Recovery Cases"
        subtitle={`${cases.length} total cases · ${formatINR(totalOriginal)} in original failures · ${formatINR(totalRecovered)} recovered`}
      />

      {/* Status filter tabs */}
      <div className="flex flex-wrap gap-1.5">
        {STATUS_TABS.map((tab) => {
          const active = status === tab.key
          const count = counts[tab.key] ?? 0
          return (
            <button
              key={tab.key}
              onClick={() => setStatus(tab.key)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                active
                  ? "border-blue-500/40 bg-blue-600/15 text-blue-400"
                  : "border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700 hover:text-slate-300"
              }`}
            >
              {tab.label} <span className="ml-1 opacity-70">{count}</span>
            </button>
          )
        })}
      </div>

      {/* Risk + search */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-slate-500">Risk</span>
          <select
            value={risk}
            onChange={(e) => setRisk(e.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-sm text-slate-200"
          >
            {RISKS.map((r) => (
              <option key={r} value={r}>
                {r === "all" ? "All levels" : r.charAt(0) + r.slice(1).toLowerCase()}
              </option>
            ))}
          </select>
        </div>
        <div className="relative flex-1 sm:max-w-xs">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by customer or email…"
            className="w-full rounded-lg border border-slate-800 bg-slate-900 py-1.5 pl-9 pr-3 text-sm text-slate-200 placeholder:text-slate-600"
          />
        </div>
        <div className="ml-auto text-sm text-slate-500">
          {filtered.length} shown · <span className="text-amber-400">{formatINR(totalOutstanding)}</span> outstanding
        </div>
      </div>

      {/* Table */}
      <Card className="overflow-hidden">
        {loading ? (
          <div className="p-6">
            <SkeletonTable rows={8} />
          </div>
        ) : error ? (
          <div className="p-6 text-center text-red-400">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon="🗂️"
              title="No cases match"
              description="Try a different status, risk level, or search term."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-3 font-medium">Customer</th>
                  <th className="px-4 py-3 font-medium">Original</th>
                  <th className="px-4 py-3 font-medium">Recovered</th>
                  <th className="px-4 py-3 font-medium">Remaining</th>
                  <th className="px-4 py-3 font-medium">Risk</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Attempts</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => {
                  const riskObj = riskMeta(c.risk_level)
                  return (
                    <tr
                      key={c.id}
                      className="border-b border-slate-800/50 transition-colors last:border-0 hover:bg-slate-800/40"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-700 text-xs font-bold text-slate-200">
                            {initials(c.customer_name)}
                          </span>
                          <div className="min-w-0">
                            <div className="truncate font-medium text-slate-200">
                              {c.customer_name || "Unknown customer"}
                            </div>
                            <div className="truncate text-xs text-slate-500">
                              {c.customer_email || "—"}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-medium text-slate-200">
                        {formatINR(c.original_amount)}
                      </td>
                      <td className={`px-4 py-3 font-medium ${riskObj.text}`}>
                        {formatINR(c.recovered_amount)}
                      </td>
                      <td className="px-4 py-3 text-amber-400">
                        {formatINR(c.remaining_amount)}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`font-medium ${riskObj.text}`}>
                          {riskObj.label}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge meta={caseMeta(c.status)} />
                      </td>
                      <td className="px-4 py-3 text-slate-400">
                        {c.attempt_count}
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {formatDateTime(c.created_at)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          to={`/case/${c.id}`}
                          className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                        >
                          Open →
                        </Link>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}