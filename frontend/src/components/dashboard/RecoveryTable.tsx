import type { RecoveryCaseSummary } from "../../types/analytics"
import { formatCurrency } from "./MetricCard"

interface RecoveryTableProps {
  cases: RecoveryCaseSummary[]
  onSelectCase: (caseId: string) => void
}

const STATUS_COLORS: Record<string, string> = {
  AT_RISK: "bg-red-500/20 text-red-400",
  RECOVERY_IN_PROGRESS: "bg-amber-500/20 text-amber-400",
  PROMISED: "bg-blue-500/20 text-blue-400",
  SCHEDULED: "bg-purple-500/20 text-purple-400",
  PARTIALLY_RECOVERED: "bg-yellow-500/20 text-yellow-400",
  RECOVERED: "bg-green-500/20 text-green-400",
  LOST: "bg-gray-500/20 text-gray-400",
  STOPPED: "bg-gray-500/20 text-gray-400",
}

const RISK_COLORS: Record<string, string> = {
  HIGH: "text-red-400",
  MEDIUM: "text-yellow-400",
  LOW: "text-green-400",
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

export default function RecoveryTable({
  cases,
  onSelectCase,
}: RecoveryTableProps) {
  if (cases.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-100">
          Recovery Cases
        </h2>
        <p className="text-center text-slate-500">No recovery cases yet.</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <h2 className="mb-4 text-lg font-semibold text-slate-100">
        Recovery Cases
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400">
              <th className="pb-3 pr-4 font-medium">Customer</th>
              <th className="pb-3 pr-4 font-medium">Amount</th>
              <th className="pb-3 pr-4 font-medium">Risk</th>
              <th className="pb-3 pr-4 font-medium">Status</th>
              <th className="pb-3 pr-4 font-medium">Recovered</th>
              <th className="pb-3 pr-4 font-medium">Remaining</th>
              <th className="pb-3 pr-4 font-medium">Attempts</th>
              <th className="pb-3 pr-4 font-medium">Created</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr
                key={c.id}
                className="cursor-pointer border-b border-slate-800/50 transition-colors hover:bg-slate-800/50"
                onClick={() => onSelectCase(c.id)}
              >
                <td className="py-3 pr-4">
                  <div className="font-medium text-slate-200">
                    {c.customer_name || "Unknown"}
                  </div>
                  <div className="text-xs text-slate-500">
                    {c.customer_email || "—"}
                  </div>
                </td>
                <td className="py-3 pr-4 font-medium text-slate-200">
                  {formatCurrency(c.original_amount)}
                </td>
                <td className={`py-3 pr-4 font-medium ${RISK_COLORS[c.risk_level] || "text-slate-400"}`}>
                  {c.risk_level}
                </td>
                <td className="py-3 pr-4">
                  <span
                    className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      STATUS_COLORS[c.status] || "bg-slate-700 text-slate-300"
                    }`}
                  >
                    {c.status.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="py-3 pr-4 text-green-400">
                  {formatCurrency(c.recovered_amount)}
                </td>
                <td className="py-3 pr-4 text-amber-400">
                  {formatCurrency(c.remaining_amount)}
                </td>
                <td className="py-3 pr-4 text-slate-400">
                  {c.attempt_count}
                </td>
                <td className="py-3 pr-4 text-slate-500">
                  {formatDate(c.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
