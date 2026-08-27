import { useEffect, useState } from "react"
import type { RecoveryCaseDetail } from "../../types/analytics"
import { fetchRecoveryCaseDetail } from "../../services/analytics"
import { formatCurrency } from "./MetricCard"

interface CaseDetailModalProps {
  caseId: string | null
  onClose: () => void
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

function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return "—"
  return new Date(dateStr).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function CaseDetailModal({
  caseId,
  onClose,
}: CaseDetailModalProps) {
  const [detail, setDetail] = useState<RecoveryCaseDetail | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!caseId) {
      setDetail(null)
      return
    }
    setLoading(true)
    fetchRecoveryCaseDetail(caseId)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [caseId])

  if (!caseId) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
          </div>
        )}

        {detail && (
          <>
            {/* Header */}
            <div className="mb-6 flex items-start justify-between">
              <div>
                <h2 className="text-xl font-bold text-slate-100">
                  Recovery Case
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  {detail.customer_name || "Unknown Customer"} •{" "}
                  {detail.customer_email || "—"}
                </p>
              </div>
              <button
                onClick={onClose}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              >
                <svg
                  className="h-5 w-5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>

            {/* Status badge */}
            <div className="mb-6 flex items-center gap-3">
              <span
                className={`inline-block rounded-full px-3 py-1 text-sm font-medium ${
                  STATUS_COLORS[detail.status] ||
                  "bg-slate-700 text-slate-300"
                }`}
              >
                {detail.status.replace(/_/g, " ")}
              </span>
              <span className="text-sm text-slate-400">
                Risk:{" "}
                <span
                  className={
                    detail.risk_level === "HIGH"
                      ? "font-medium text-red-400"
                      : detail.risk_level === "MEDIUM"
                        ? "font-medium text-yellow-400"
                        : "font-medium text-green-400"
                  }
                >
                  {detail.risk_level}
                </span>
              </span>
            </div>

            {/* Amounts */}
            <div className="mb-6 grid grid-cols-3 gap-4">
              <div className="rounded-lg bg-slate-800 p-4">
                <p className="text-xs text-slate-400">Original</p>
                <p className="text-lg font-bold text-slate-100">
                  {formatCurrency(detail.original_amount)}
                </p>
              </div>
              <div className="rounded-lg bg-slate-800 p-4">
                <p className="text-xs text-slate-400">Recovered</p>
                <p className="text-lg font-bold text-green-400">
                  {formatCurrency(detail.recovered_amount)}
                </p>
              </div>
              <div className="rounded-lg bg-slate-800 p-4">
                <p className="text-xs text-slate-400">Remaining</p>
                <p className="text-lg font-bold text-amber-400">
                  {formatCurrency(detail.remaining_amount)}
                </p>
              </div>
            </div>

            {/* Progress bar */}
            <div className="mb-6">
              <div className="mb-1 flex justify-between text-xs text-slate-400">
                <span>Recovery Progress</span>
                <span>
                  {detail.original_amount > 0
                    ? Math.round(
                        (detail.recovered_amount / detail.original_amount) *
                          100,
                      )
                    : 0}
                  %
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full rounded-full bg-green-500 transition-all"
                  style={{
                    width: `${
                      detail.original_amount > 0
                        ? Math.min(
                            100,
                            (detail.recovered_amount /
                              detail.original_amount) *
                              100,
                          )
                        : 0
                    }%`,
                  }}
                />
              </div>
            </div>

            {/* Details grid */}
            <div className="mb-6 grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-slate-400">Customer Phone</p>
                <p className="text-slate-200">
                  {detail.customer_phone || "—"}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Event Type</p>
                <p className="text-slate-200">
                  {detail.event_type || "—"}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Source</p>
                <p className="text-slate-200">{detail.source || "—"}</p>
              </div>
              <div>
                <p className="text-slate-400">Failure Reason</p>
                <p className="text-slate-200">
                  {detail.failure_reason || "—"}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Attempts</p>
                <p className="text-slate-200">
                  {detail.attempt_count} / {detail.max_attempts}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Risk Reason</p>
                <p className="text-slate-200">
                  {detail.risk_reason || "—"}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Created</p>
                <p className="text-slate-200">
                  {formatDateTime(detail.created_at)}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Last Activity</p>
                <p className="text-slate-200">
                  {formatDateTime(detail.updated_at)}
                </p>
              </div>
            </div>

            {/* Audit trail */}
            {detail.audit_events && detail.audit_events.length > 0 && (
              <div>
                <h3 className="mb-3 text-sm font-semibold text-slate-300">
                  Audit Trail
                </h3>
                <div className="space-y-2">
                  {detail.audit_events.map((ae) => (
                    <div
                      key={ae.id}
                      className="rounded-lg bg-slate-800/50 px-4 py-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-slate-300">
                          {ae.action}
                        </span>
                        <span className="text-xs text-slate-500">
                          {formatDateTime(ae.created_at)}
                        </span>
                      </div>
                      {ae.new_value && (
                        <pre className="mt-1 overflow-x-auto text-xs text-slate-400">
                          {JSON.stringify(ae.new_value, null, 2)}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
