import { useEffect, useState } from "react"
import { fetchCasePaymentPlans } from "../../services/analytics"
import { formatDate } from "../../lib/format"
import type { InstallmentLeg } from "./types"
import { formatCurrencyFull, toInstallmentLegs } from "./types"
import { legMeta } from "./semantics"

interface PlanInstallmentTimelineProps {
  caseId: string
  planId: string
}

export default function PlanInstallmentTimeline({
  caseId,
  planId,
}: PlanInstallmentTimelineProps) {
  const [legs, setLegs] = useState<InstallmentLeg[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchCasePaymentPlans(caseId)
      .then((casePlans) => {
        if (cancelled) return
        const match = casePlans.find((p) => p.id === planId)
        if (!match) {
          setLegs([])
          return
        }
        setLegs(toInstallmentLegs(match.installments))
      })
      .catch((e) =>
        setError(
          e instanceof Error ? e.message : "Failed to load installment legs",
        ),
      )
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [caseId, planId])

  const paid = legs.filter((l) => l.status === "PAID").length
  const failed = legs.filter(
    (l) => l.status === "FAILED" || l.status === "OVERDUE",
  ).length
  const scheduled = legs.filter(
    (l) => l.status === "SCHEDULED" || l.status === "DUE" || l.status === "PROCESSING",
  ).length

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
          Installment legs
        </p>
        <div className="flex items-center gap-2 font-mono text-[10px] tabular-nums">
          <span className="text-emerald-400">{paid} paid</span>
          <span className="text-slate-600">·</span>
          <span className="text-amber-400">{scheduled} scheduled</span>
          {failed > 0 && (
            <>
              <span className="text-slate-600">·</span>
              <span className="text-rose-400">{failed} failed</span>
            </>
          )}
          <span className="text-slate-600">·</span>
          <span className="text-slate-400">{legs.length} total</span>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-9 animate-pulse rounded-md bg-slate-800/60"
            />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-md border border-rose-800/40 bg-rose-950/20 px-3 py-2 text-[11px] text-rose-300">
          {error}
        </div>
      ) : legs.length === 0 ? (
        <div className="rounded-md border border-dashed border-slate-700/60 px-3 py-3 text-center text-[11px] text-slate-500">
          No installment legs recorded for this plan yet.
        </div>
      ) : (
        <div className="relative ml-1.5 space-y-0 border-l border-slate-800 pl-5">
          {legs.map((leg) => {
            const m = legMeta(leg.status)
            return (
              <div key={leg.id} className="relative pb-3 last:pb-0">
                <span
                  className={`absolute -left-[1.55rem] top-1 h-2 w-2 rounded-full ${m.dot}`}
                />
                <div className="rounded-md border border-edge bg-canvas/60 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="font-mono text-[11px] text-slate-500">
                      Leg {leg.installmentNumber}
                    </span>
                    <span className="font-mono text-[13px] font-medium tabular-nums text-slate-200">
                      {formatCurrencyFull(leg.amountPaise)}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${m.badge}`}
                    >
                      <span className={`h-1 w-1 rounded-full ${m.dot}`} />
                      {m.label}
                    </span>
                    <span className="ml-auto text-[11px] text-slate-500">
                      {leg.dueDate
                        ? `Due ${formatDate(leg.dueDate)}`
                        : "No due date"}
                    </span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
                    <span className="flex items-center gap-1">
                      <span
                        className={`h-1 w-1 rounded-full ${m.dot}`}
                        aria-hidden
                      />
                      {leg.mandateStatus}
                    </span>
                    {leg.paidAt && (
                      <span className="text-emerald-500/90">
                        Paid {formatDate(leg.paidAt)}
                      </span>
                    )}
                    {leg.failedAt && (
                      <span className="text-rose-400">
                        Failed {formatDate(leg.failedAt)}
                      </span>
                    )}
                    {leg.retryAttempts > 0 && (
                      <span className="rounded border border-rose-800/40 bg-rose-950/30 px-1.5 py-0.5 text-rose-300">
                        {leg.retryAttempts} retry fed
                      </span>
                    )}
                    {leg.failureReason && (
                      <span className="truncate text-rose-400/80">
                        · {leg.failureReason}
                      </span>
                    )}
                    {leg.razorpayPaymentId && (
                      <span className="hidden font-mono text-[9px] text-slate-600 sm:inline">
                        {leg.razorpayPaymentId}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export type { InstallmentLeg }