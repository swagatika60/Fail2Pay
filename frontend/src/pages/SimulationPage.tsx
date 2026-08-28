import { useState } from "react"
import { Link } from "react-router-dom"
import { formatCurrency } from "../components/dashboard/MetricCard"
import { fetchVerifiedImpactLedger } from "../services/analytics"
import type { VerifiedImpactLedger } from "../types/analytics"

interface SimulationResults {
  total_transactions: number
  customers_created: number
  cases_created: number
  analytics: {
    total_transactions: number
    total_original_revenue: number
    total_recovered_revenue: number
    total_remaining_revenue: number
    recovery_rate: number
    payments_count?: number
    recovered_revenue: number
    revenue_at_risk: number
    recovery_attempts: number
    customer_responses: number
    promised_revenue: number
    scheduled_revenue: number
    payment_plans_count: number
    lost_revenue: number
    metrics: {
      total_revenue: number
      revenue_at_risk: number
      recovery_attempts: number
      customer_responses: number
      promise_to_pay: number
      scheduled_revenue: number
      payment_plans: number
      recovered_revenue: number
      lost_revenue: number
      recovery_rate: number
    }
    status_breakdown: {
      recovered: number
      lost: number
      stopped: number
      in_progress: number
      promised: number
      partially_recovered: number
      scheduled: number
      at_risk: number
    }
    communication_stats: {
      total_messages: number
      inbound_messages: number
      outbound_messages: number
      customer_response_rate: number
    }
    financial_summary: {
      recovered: number
      at_risk: number
      partially_recovered: number
      lost: number
    }
    scenario_distribution: Record<string, number>
  }
}

const STATUS_COLORS: Record<string, string> = {
  recovered: "bg-green-500/20 text-green-400",
  lost: "bg-red-500/20 text-red-400",
  stopped: "bg-gray-500/20 text-gray-400",
  in_progress: "bg-amber-500/20 text-amber-400",
  promised: "bg-blue-500/20 text-blue-400",
  partially_recovered: "bg-yellow-500/20 text-yellow-400",
  scheduled: "bg-purple-500/20 text-purple-400",
  at_risk: "bg-red-500/20 text-red-400",
}

const STATUS_LABELS: Record<string, string> = {
  recovered: "Recovered",
  lost: "Lost",
  stopped: "Stopped (Opted Out)",
  in_progress: "In Progress",
  promised: "Promised to Pay",
  partially_recovered: "Partially Recovered",
  scheduled: "Scheduled (Plan)",
  at_risk: "At Risk",
}

export default function SimulationPage() {
  const [results, setResults] = useState<SimulationResults | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ledger, setLedger] = useState<VerifiedImpactLedger | null>(null)

  const runSimulation = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch("/api/simulation/run", { method: "POST" })
      if (!response.ok) throw new Error("Failed to run simulation")
      const data = await response.json()
      setResults(data)
      try {
        setLedger(await fetchVerifiedImpactLedger())
      } catch (ledgerErr) {
        console.error("Failed to fetch impact ledger:", ledgerErr)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation failed")
    } finally {
      setLoading(false)
    }
  }

  const loadLedger = async () => {
    try {
      setLedger(await fetchVerifiedImpactLedger())
    } catch (err) {
      console.error("Failed to fetch impact ledger:", err)
    }
  }

  const resetData = async () => {
    if (!confirm("Reset all simulation data? This cannot be undone.")) return
    try {
      await fetch("/api/simulation/reset", { method: "DELETE" })
      setResults(null)
      setLedger(null)
    } catch (err) {
      console.error("Reset failed:", err)
    }
  }

  const analytics = results?.analytics
  const m = analytics?.metrics

  return (
    <div className="space-y-6 text-slate-100">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            🧪 Batch Simulation
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            100 controlled test transactions with real recovery workflow
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/"
            className="rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700"
          >
            ← Dashboard
          </Link>
          <button
            onClick={runSimulation}
            disabled={loading}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {loading ? "Running..." : "🚀 Run Simulation"}
          </button>
          {results && (
            <button
              onClick={resetData}
              className="rounded-lg bg-red-600/20 px-4 py-2 text-sm text-red-400 hover:bg-red-600/30"
            >
              🗑️ Reset
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-red-800 bg-red-900/20 p-4 text-red-400">
          {error}
        </div>
      )}

      {!results && !loading && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-slate-800 bg-slate-900 py-20">
          <p className="mb-4 text-lg text-slate-400">
            No simulation data yet
          </p>
          <p className="mb-6 text-sm text-slate-500">
            Click "Run Simulation" to generate 100 controlled test transactions
          </p>
          <button
            onClick={runSimulation}
            className="rounded-lg bg-blue-600 px-6 py-3 text-sm font-medium text-white hover:bg-blue-500"
          >
            🚀 Run Simulation
          </button>
        </div>
      )}

      {analytics && (
        <div className="space-y-6">
          {/* Top Metrics — 10 headline numbers */}
          <div className="space-y-4">
            {/* Recovered Revenue — THE number, verified captured money only */}
            <div className="rounded-2xl border-2 border-green-500/30 bg-gradient-to-br from-green-950/40 to-emerald-900/20 p-6">
              <p className="text-xs font-semibold uppercase tracking-wider text-green-400">
                💰 Recovered Revenue — Actual Money Collected
              </p>
              <p className="mt-2 text-4xl font-extrabold tracking-tight text-green-400">
                {m ? formatCurrency(m.recovered_revenue) : formatCurrency(analytics.total_recovered_revenue)}
              </p>
              <p className="mt-2 text-sm text-slate-400">
                Only <span className="font-medium text-green-400">verified captured payments</span> count.
                Messages, reminders and promises are NOT revenue.
              </p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-300">
                <span className="rounded-full bg-green-500/10 px-2.5 py-1">
                  {analytics.payments_count ?? m?.payment_plans ?? 0} verified payments
                </span>
                <span className="rounded-full bg-green-500/10 px-2.5 py-1">
                  {Math.round((m ? m.recovery_rate : analytics.recovery_rate) * 100)}% recovery rate
                </span>
              </div>
            </div>

            {/* Row 2: revenue, at risk, lost, recovery rate */}
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <MetricCard
                title="Total Revenue"
                value={formatCurrency(m ? m.total_revenue : analytics.total_original_revenue)}
                color="text-blue-400"
                subtitle={`${analytics.total_transactions} transactions · ₹${(analytics.total_original_revenue / 100).toLocaleString("en-IN")}`}
              />
              <MetricCard
                title="Revenue At Risk"
                value={formatCurrency(m ? m.revenue_at_risk : analytics.revenue_at_risk)}
                color="text-red-400"
                subtitle="Money still outstanding"
              />
              <MetricCard
                title="Lost Revenue"
                value={formatCurrency(m ? m.lost_revenue : analytics.lost_revenue)}
                color="text-gray-400"
                subtitle="Attempts exhausted"
              />
              <MetricCard
                title="Recovery Rate"
                value={`${Math.round((m ? m.recovery_rate : analytics.recovery_rate) * 100)}%`}
                color="text-emerald-400"
                subtitle="Captured / total revenue"
              />
            </div>

            {/* Row 3: recovery work + pipeline */}
            <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
              <MetricCard
                title="Recovery Attempts"
                value={(m ? m.recovery_attempts : analytics.recovery_attempts).toLocaleString()}
                color="text-amber-400"
                subtitle="Total actions taken"
              />
              <MetricCard
                title="Customer Responses"
                value={(m ? m.customer_responses : analytics.customer_responses).toLocaleString()}
                color="text-cyan-400"
                subtitle="Inbound replies"
              />
              <MetricCard
                title="Promise-to-Pay"
                value={formatCurrency(m ? m.promise_to_pay : analytics.promised_revenue)}
                color="text-blue-400"
                subtitle="Promised, NOT paid"
              />
              <MetricCard
                title="Scheduled Revenue"
                value={formatCurrency(m ? m.scheduled_revenue : analytics.scheduled_revenue)}
                color="text-purple-400"
                subtitle="On payment plans"
              />
              <MetricCard
                title="Payment Plans"
                value={m ? m.payment_plans : analytics.payment_plans_count}
                color="text-fuchsia-400"
                subtitle="Active plans created"
              />
            </div>
          </div>

          {/* Status Breakdown */}
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="mb-4 text-lg font-semibold text-slate-100">
              📊 Case Status Breakdown
            </h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {Object.entries(analytics.status_breakdown).map(([status, count]) => (
                <div
                  key={status}
                  className="rounded-lg bg-slate-800/50 p-3"
                >
                  <div className="flex items-center justify-between">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                        STATUS_COLORS[status] || "bg-slate-700 text-slate-300"
                      }`}
                    >
                      {STATUS_LABELS[status] || status}
                    </span>
                    <span className="text-lg font-bold text-slate-100">
                      {count}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {Math.round((count / analytics.total_transactions) * 100)}% of total
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Communication Stats */}
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="mb-4 text-lg font-semibold text-slate-100">
              💬 Communication Statistics
            </h2>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="rounded-lg bg-slate-800/50 p-4 text-center">
                <div className="text-2xl font-bold text-slate-100">
                  {analytics.communication_stats.total_messages}
                </div>
                <div className="text-xs text-slate-500">Total Messages</div>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-4 text-center">
                <div className="text-2xl font-bold text-green-400">
                  {analytics.communication_stats.outbound_messages}
                </div>
                <div className="text-xs text-slate-500">Messages Sent</div>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-4 text-center">
                <div className="text-2xl font-bold text-cyan-400">
                  {analytics.communication_stats.inbound_messages}
                </div>
                <div className="text-xs text-slate-500">Customer Replies</div>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-4 text-center">
                <div className="text-2xl font-bold text-emerald-400">
                  {Math.round(analytics.communication_stats.customer_response_rate * 100)}%
                </div>
                <div className="text-xs text-slate-500">Response Rate</div>
              </div>
            </div>
          </div>

          {/* Scenario Distribution */}
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="mb-4 text-lg font-semibold text-slate-100">
              🎯 Scenario Distribution
            </h2>
            <div className="space-y-2">
              {Object.entries(analytics.scenario_distribution).map(([scenario, count]) => (
                <div
                  key={scenario}
                  className="flex items-center gap-3 rounded-lg bg-slate-800/30 px-4 py-2"
                >
                  <div className="w-48 text-sm text-slate-300">
                    {scenario.replace(/_/g, " ")}
                  </div>
                  <div className="flex-1">
                    <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                      <div
                        className="h-full rounded-full bg-blue-500"
                        style={{
                          width: `${(count / analytics.total_transactions) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                  <div className="w-12 text-right text-sm font-medium text-slate-200">
                    {count}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Financial Summary */}
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="mb-4 text-lg font-semibold text-slate-100">
              💰 Financial Summary
            </h2>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="rounded-lg bg-green-900/20 p-4 text-center">
                <div className="text-xl font-bold text-green-400">
                  {formatCurrency(analytics.financial_summary.recovered)}
                </div>
                <div className="text-xs text-green-500">Verified Recovered</div>
              </div>
              <div className="rounded-lg bg-red-900/20 p-4 text-center">
                <div className="text-xl font-bold text-red-400">
                  {formatCurrency(analytics.financial_summary.at_risk)}
                </div>
                <div className="text-xs text-red-500">Still At Risk</div>
              </div>
              <div className="rounded-lg bg-amber-900/20 p-4 text-center">
                <div className="text-xl font-bold text-amber-400">
                  {formatCurrency(analytics.financial_summary.partially_recovered)}
                </div>
                <div className="text-xs text-amber-500">Partially Recovered</div>
              </div>
              <div className="rounded-lg bg-gray-900/20 p-4 text-center">
                <div className="text-xl font-bold text-gray-400">
                  {formatCurrency(analytics.financial_summary.lost)}
                </div>
                <div className="text-xs text-gray-500">Lost Revenue</div>
              </div>
            </div>

            {/* Revenue bar */}
            <div className="mt-4">
              <div className="mb-2 flex justify-between text-xs text-slate-400">
                <span>Revenue Distribution</span>
                <span>{formatCurrency(analytics.total_original_revenue)}</span>
              </div>
              <div className="flex h-6 overflow-hidden rounded-full">
                <div
                  className="bg-green-500"
                  style={{
                    width: `${(analytics.financial_summary.recovered / analytics.total_original_revenue) * 100}%`,
                  }}
                />
                <div
                  className="bg-amber-500"
                  style={{
                    width: `${(analytics.financial_summary.partially_recovered / analytics.total_original_revenue) * 100}%`,
                  }}
                />
                <div
                  className="bg-red-500"
                  style={{
                    width: `${(analytics.financial_summary.at_risk / analytics.total_original_revenue) * 100}%`,
                  }}
                />
                <div
                  className="bg-gray-500"
                  style={{
                    width: `${(analytics.financial_summary.lost / analytics.total_original_revenue) * 100}%`,
                  }}
                />
              </div>
              <div className="mt-2 flex gap-4 text-xs text-slate-500">
                <span className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-green-500" /> Recovered
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-amber-500" /> Partial
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-red-500" /> At Risk
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-gray-500" /> Lost
                </span>
              </div>
            </div>
          </div>

          {/* Important Note */}
          <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 p-4">
            <p className="text-sm text-blue-400">
              ℹ️ All data is from the database — no fake numbers.
              Only verified successful payments count as recovered revenue.
              Messages sent are NOT counted as revenue recovered.
            </p>
          </div>

          {/* Verified Impact Ledger & Recovery Pipeline */}
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">
                  🪙 Verified Impact Ledger &amp; Recovery Pipeline
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  At Risk → Intervention Dispatched → Promise Captured → Verified Recovered.
                  Money counts only when a captured payment lands in the ledger.
                </p>
              </div>
              <button
                onClick={loadLedger}
                className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700"
              >
                ⟳ Refresh Ledger
              </button>
            </div>

            {!ledger || !ledger.present ? (
              <div className="rounded-lg bg-slate-800/50 p-8 text-center text-sm text-slate-400">
                Run the simulation to populate the verified impact ledger.
              </div>
            ) : (
              <>
                {/* Funnel */}
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <FunnelStage
                    label="At Risk"
                    count={ledger.funnel.at_risk.count}
                    amount={ledger.funnel.at_risk.amount}
                    color="text-red-400 border-red-500/30 bg-red-900/10"
                    bar="bg-red-500"
                  />
                  <FunnelStage
                    label="Intervention Dispatched"
                    count={ledger.funnel.intervention_dispatched.count}
                    amount={ledger.funnel.intervention_dispatched.amount}
                    color="text-amber-400 border-amber-500/30 bg-amber-900/10"
                    bar="bg-amber-500"
                  />
                  <FunnelStage
                    label="Promise Captured"
                    count={ledger.funnel.promise_captured.count}
                    amount={ledger.funnel.promise_captured.amount}
                    color="text-blue-400 border-blue-500/30 bg-blue-900/10"
                    bar="bg-blue-500"
                  />
                  <FunnelStage
                    label="Verified Recovered"
                    count={ledger.funnel.verified_recovered.count}
                    amount={ledger.funnel.verified_recovered.amount}
                    color="text-emerald-400 border-emerald-500/30 bg-emerald-900/10"
                    bar="bg-emerald-500"
                  />
                </div>

                {/* Pipeline summary */}
                <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
                  <MetricCard
                    title="Original Revenue at Risk"
                    value={formatCurrency(ledger.summary.original_revenue)}
                    color="text-red-400"
                    subtitle={`${ledger.funnel.at_risk.count} invoices`}
                  />
                  <MetricCard
                    title="Verified Recovered"
                    value={formatCurrency(ledger.summary.verified_recovered)}
                    color="text-emerald-400"
                    subtitle="Captured payments only"
                  />
                  <MetricCard
                    title="Verified Recovery Rate"
                    value={`${Math.round(ledger.summary.recovery_rate * 100)}%`}
                    color="text-emerald-400"
                    subtitle="Verified recovered / original"
                  />
                </div>

                {/* Funnel bar visualization */}
                <div className="mt-4 flex h-6 overflow-hidden rounded-full">
                  <div
                    className="bg-red-500"
                    style={{ width: "100%" }}
                    title="At Risk"
                  />
                </div>
                <div className="mt-1 flex h-6 overflow-hidden rounded-full">
                  <div
                    className="bg-amber-500"
                    style={{
                      width: `${
                        (ledger.funnel.intervention_dispatched.count /
                          Math.max(ledger.funnel.at_risk.count, 1)) *
                        100
                      }%`,
                    }}
                  />
                </div>
                <div className="mt-1 flex h-6 overflow-hidden rounded-full">
                  <div
                    className="bg-blue-500"
                    style={{
                      width: `${
                        (ledger.funnel.promise_captured.count /
                          Math.max(ledger.funnel.at_risk.count, 1)) *
                        100
                      }%`,
                    }}
                  />
                </div>
                <div className="mt-1 flex h-6 overflow-hidden rounded-full">
                  <div
                    className="bg-emerald-500"
                    style={{
                      width: `${
                        (ledger.funnel.verified_recovered.count /
                          Math.max(ledger.funnel.at_risk.count, 1)) *
                        100
                      }%`,
                    }}
                  />
                </div>

                {/* Per-case ledger table */}
                <h3 className="mt-6 mb-2 text-sm font-semibold text-slate-200">
                  Per-Case Verified Ledger
                </h3>
                <div className="overflow-x-auto rounded-lg border border-slate-800">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-800/50 text-xs uppercase tracking-wide text-slate-400">
                      <tr>
                        <th className="px-3 py-2">Case</th>
                        <th className="px-3 py-2">Risk</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2 text-right">Original</th>
                        <th className="px-3 py-2 text-right">Verified Rec.</th>
                        <th className="px-3 py-2 text-right">Remaining</th>
                        <th className="px-3 py-2">Pipeline</th>
                        <th className="px-3 py-2">Recovered?</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ledger.ledger.map((row) => (
                        <tr
                          key={row.case_id}
                          className="border-t border-slate-800"
                        >
                          <td className="px-3 py-2 font-mono text-xs text-slate-400">
                            {row.case_id.slice(0, 8)}
                          </td>
                          <td className="px-3 py-2 text-xs text-slate-300">
                            {row.risk_level}
                          </td>
                          <td className="px-3 py-2">
                            <span
                              className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                                STATUS_COLORS[
                                  row.status.toLowerCase().replaceAll(" ", "_")
                                ] || "bg-slate-700 text-slate-300"
                              }`}
                            >
                              {row.status}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right text-slate-300">
                            {formatCurrency(row.original_amount)}
                          </td>
                          <td className="px-3 py-2 text-right text-green-400">
                            {formatCurrency(row.verified_recovered_amount)}
                          </td>
                          <td className="px-3 py-2 text-right text-slate-400">
                            {formatCurrency(row.remaining_amount)}
                          </td>
                          <td className="px-3 py-2 text-xs text-slate-400">
                            {["intervention_dispatched", "promise_captured"].map(
                              (stage) => (
                                <span
                                  key={stage}
                                  className={`mr-1 inline-block rounded px-1.5 py-0.5 text-[10px] ${
                                    row[stage as keyof typeof row]
                                      ? "bg-emerald-900/40 text-emerald-300"
                                      : "bg-slate-800 text-slate-600"
                                  }`}
                                >
                                  {stage.replace(/_/g, " ")}
                                </span>
                              ),
                            )}
                          </td>
                          <td className="px-3 py-2">
                            {row.verified_recovered ? (
                              <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs font-medium text-emerald-400">
                                ✔ Recovered
                              </span>
                            ) : (
                              <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-500">
                                Not yet
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function FunnelStage({
  label,
  count,
  amount,
  color,
  bar,
}: {
  label: string
  count: number
  amount: number
  color: string
  bar: string
}) {
  return (
    <div className={`rounded-xl border p-4 ${color}`}>
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-bold ${color.split(" ")[0]}`}>
        {count}
      </div>
      <div className="mt-0.5 text-sm font-medium text-slate-300">
        {formatCurrency(amount)}
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full ${bar}`} style={{ width: "100%" }} />
      </div>
    </div>
  )
}

function MetricCard({
  title,
  value,
  color,
  subtitle,
}: {
  title: string
  value: string | number
  color: string
  subtitle?: string
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <p className="text-xs text-slate-400">{title}</p>
      <p className={`text-xl font-bold ${color}`}>{value}</p>
      {subtitle && <p className="mt-0.5 text-[10px] text-slate-500">{subtitle}</p>}
    </div>
  )
}
