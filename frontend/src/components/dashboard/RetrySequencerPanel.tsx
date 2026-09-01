import { useEffect, useRef, useState } from "react"
import type { RetrySequencer } from "../../services/operations"
import { fetchPlanRetrySequencer } from "../../services/operations"
import { formatCurrency } from "./MetricCard"

const ACTION_ICONS: Record<string, string> = {
  degrade_trigger: "🚨",
  send_upfront_link: "💸",
  send_gateway_link: "🔗",
  reminder_24h: "⏰",
  split_due: "📅",
  split_reminder: "🔔",
  escalate_review: "📈",
  installment_due: "💳",
  reminder: "🔔",
  review: "🔄",
}

export const ACTION_BADGES: Record<string, { label: string; bg: string; text: string }> = {
  degrade_trigger: { label: "CRIT", bg: "bg-rose-500/10 border-rose-500/30", text: "text-rose-400" },
  send_upfront_link: { label: "PAY", bg: "bg-emerald-500/10 border-emerald-500/30", text: "text-emerald-400" },
  send_gateway_link: { label: "LINK", bg: "bg-cyan-500/10 border-cyan-500/30", text: "text-cyan-400" },
  reminder_24h: { label: "24H", bg: "bg-amber-500/10 border-amber-500/30", text: "text-amber-400" },
  split_due: { label: "SPLIT", bg: "bg-purple-500/10 border-purple-500/30", text: "text-purple-400" },
  split_reminder: { label: "NOTIF", bg: "bg-blue-500/10 border-blue-500/30", text: "text-blue-400" },
  installment_due: { label: "EMI", bg: "bg-indigo-500/10 border-indigo-500/30", text: "text-indigo-400" },
  reminder: { label: "PING", bg: "bg-sky-500/10 border-sky-500/30", text: "text-sky-400" },
  review: { label: "SYNC", bg: "bg-violet-500/10 border-violet-500/30", text: "text-violet-400" },
  escalate_review: { label: "ESCL", bg: "bg-red-500/10 border-red-500/30", text: "text-red-400" },
};


function fmt(dt: string | null): string {
  if (!dt) return "—"
  return new Date(dt).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

interface Props {
  planId: string
  degraded?: boolean
  strategyLabel?: string | null
  strategy?: string | null
}

export default function RetrySequencerPanel({
  planId,
  degraded = false,
  strategyLabel,
  strategy,
}: Props) {
  const [seq, setSeq] = useState<RetrySequencer | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const loadedRef = useRef(false)

  // Fetch the full timeline the first time the panel is expanded. The header
  // (degraded flag + strategy) arrives from the parent's plan list, so we
  // avoid firing a retry-sequencer request for every plan on page load.
  useEffect(() => {
    if (!open || loadedRef.current) return
    loadedRef.current = true
    setLoading(true)
    setError(null)
    fetchPlanRetrySequencer(planId)
      .then(setSeq)
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load sequencer"),
      )
      .finally(() => setLoading(false))
  }, [open, planId])

  const toggle = () => setOpen((o) => !o)

  const title = degraded
    ? "Payment Degradation & Mandate Retry"
    : "Schedule / Retry Status"
  const subtitle = degraded
    ? strategyLabel || "Retry strategy recommended"
    : "No degradation — payments on track"

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-slate-700 bg-slate-900">
      <button
        onClick={toggle}
        className={`flex w-full items-center justify-between gap-2 px-4 py-3 text-left ${
          degraded
            ? "bg-amber-500/10 hover:bg-amber-500/15"
            : "bg-slate-800/40 hover:bg-slate-800/60"
        }`}
      >
        <div className="flex items-center gap-2">
          <span className="text-base">
            {degraded ? (strategy === "SPLIT_PLAN" ? "💳" : "🔗") : "📅"}
          </span>
          <div>
            <p
              className={`text-sm font-semibold ${
                degraded ? "text-amber-300" : "text-slate-200"
              }`}
            >
              {title}
            </p>
            <p className="text-xs text-slate-400">{subtitle}</p>
          </div>
        </div>
        <span className="text-slate-400">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-800 px-4 py-4">
          {loading && (
            <div className="text-sm text-slate-500">
              Loading retry timeline…
            </div>
          )}

          {!loading && error && (
            <div className="rounded-lg border border-red-800 bg-red-500/10 p-3 text-xs text-red-300">
              {error}
            </div>
          )}

          {!loading && seq && seq.blocked && (
            <div className="rounded-lg border border-red-800 bg-red-500/10 p-3 text-xs text-red-300">
              🛑 Retries halted: hard-stop condition ({seq.block_reason}). No
              automated outreach will be scheduled.
            </div>
          )}

          {!loading && seq && seq.degraded && seq.split && (
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg bg-slate-800/50 p-2.5">
                <p className="text-slate-500">Upfront (due now)</p>
                <p className="text-lg font-bold text-green-400">
                  {formatCurrency(seq.split.upfront_amount)}
                </p>
                <p className="text-[10px] text-slate-600">{fmt(seq.split.upfront_due)}</p>
              </div>
              <div className="rounded-lg bg-slate-800/50 p-2.5">
                <p className="text-slate-500">Balance (in 14 days)</p>
                <p className="text-lg font-bold text-amber-400">
                  {formatCurrency(seq.split.later_amount)}
                </p>
                <p className="text-[10px] text-slate-600">{fmt(seq.split.later_due)}</p>
              </div>
            </div>
          )}

          {!loading && seq && !seq.blocked && (
            <div>
              <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Retry timeline (scheduled execution)
              </p>
              <div className="relative ml-3 space-y-3 border-l border-slate-700 pl-5">
                {seq.timeline.map((step) => (
                  <div key={step.order} className="relative">
                    <span className="absolute -left-[1.43rem] top-1 h-2.5 w-2.5 rounded-full bg-slate-500" />
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-medium text-slate-200">
                        {ACTION_ICONS[step.action] ?? "•"} {step.label}
                      </p>
                      <span className="shrink-0 text-[10px] text-slate-500">
                        {fmt(step.scheduled_for)}
                      </span>
                    </div>
                    {step.payload && Object.keys(step.payload).length > 0 && (
                      <p className="mt-0.5 text-[10px] text-slate-500">
                        {Object.entries(step.payload)
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(" · ")}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
