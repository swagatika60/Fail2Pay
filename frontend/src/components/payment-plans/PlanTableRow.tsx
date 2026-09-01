import { useState } from "react"
import { useNavigate, Link } from "react-router-dom"
import type { PaymentPlan } from "./types"
import { estimatedNextLegDue, failedPortionPaise } from "./types"
import { formatCompact, formatCurrencyFull } from "./types"
import { formatDate } from "../../lib/format"
import { PLAN_SEMANTIC_META } from "./semantics"
import PlanInstallmentTimeline from "./PlanInstallmentTimeline"
import RetrySequencerPanel from "../dashboard/RetrySequencerPanel"

interface PlanTableRowProps {
  plan: PaymentPlan
  expanded: boolean
  onToggle: () => void
}

function frequencyLabel(freq: string): string {
  const f = freq.toLowerCase()
  if (f === "weekly") return "Weekly"
  if (f === "biweekly") return "Bi-weekly"
  if (f === "fortnightly") return "Bi-weekly"
  if (f === "monthly") return "Monthly"
  if (f === "quarterly") return "Quarterly"
  return freq
}

function RowActions({
  plan,
  onToggle,
}: {
  plan: PaymentPlan
  onToggle: () => void
}) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const navigate = useNavigate()

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(plan.id)
      setCopied(true)
      setOpen(false)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Plan actions"
        className="rounded-md border border-edge bg-canvas p-1.5 text-slate-400 transition-colors hover:border-slate-600/50 hover:text-slate-200"
      >
        <svg
          className="h-3.5 w-3.5"
          fill="currentColor"
          viewBox="0 0 24 24"
        >
          <circle cx="5" cy="12" r="1.6" />
          <circle cx="12" cy="12" r="1.6" />
          <circle cx="19" cy="12" r="1.6" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1 min-w-44 overflow-hidden rounded-md border border-edge bg-panel shadow-xl">
            {copied && (
              <p className="px-3 py-1.5 text-[10px] text-emerald-400">
                Plan ID copied
              </p>
            )}
            <button
              onClick={() => {
                setOpen(false)
                navigate(`/case/${plan.caseId}`)
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] text-slate-300 transition-colors hover:bg-slate-200/10"
            >
              <span className="text-slate-500">↗</span> View recovery case
            </button>
            <button
              onClick={() => {
                setOpen(false)
                onToggle()
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] text-slate-300 transition-colors hover:bg-slate-200/10"
            >
              <span className="text-slate-500">▤</span> Schedule / retry status
            </button>
            <button
              onClick={copyId}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] text-slate-300 transition-colors hover:bg-slate-200/10"
            >
              <span className="font-mono text-slate-500">#</span> Copy plan ID
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export default function PlanTableRow({
  plan,
  expanded,
  onToggle,
}: PlanTableRowProps) {
  const meta = PLAN_SEMANTIC_META(plan)
  const failedPortion = failedPortionPaise(plan)
  const remaining =
    plan.totalAmountPaise - plan.amountPaidPaise - failedPortion
  const nextDue = estimatedNextLegDue(plan)
  const pct = plan.progress.percentPaid

  const telehealth = (() => {
    if (plan.status === "DEFAULTED") {
      return {
        tag: "Defaulted — recovery escalated",
        tone: "text-rose-400 border-rose-800/40 bg-rose-950/30",
        note: "No further legs scheduled",
      }
    }
    if (plan.status === "COMPLETED") {
      return {
        tag: "All legs settled",
        tone: "text-emerald-400 border-emerald-800/40 bg-emerald-950/30",
        note: `${plan.installmentCount}/${plan.installmentCount} legs · ${formatDate(plan.completedAt)}`,
      }
    }
    if (plan.status === "CANCELLED") {
      return {
        tag: "Plan cancelled",
        tone: "text-slate-400 border-slate-600/50 bg-slate-800/40",
        note: "Not collecting",
      }
    }
    if (plan.degradation.degraded) {
      return {
        tag: "Mandate degraded",
        tone: "text-amber-400 border-amber-800/40 bg-amber-950/30",
        note:
          plan.degradation.strategyLabel ||
          `Retry via sequencer (${plan.degradation.failedCount} fails)`,
      }
    }
    if (nextDue) {
      return {
        tag: `Next leg · ${formatDate(nextDue)}`,
        tone: "text-emerald-400 border-emerald-800/40 bg-emerald-950/30",
        note: plan.frequency ? `Cadence · ${frequencyLabel(plan.frequency)}` : "Cadence · —",
      }
    }
    if (plan.installmentsFailed > 0) {
      return {
        tag: `${plan.installmentsFailed} legs failed`,
        tone: "text-amber-400 border-amber-800/40 bg-amber-950/30",
        note: "Degradation threshold approaching",
      }
    }
    return {
      tag: "Awaiting schedule",
      tone: "text-slate-400 border-slate-700/50 bg-slate-800/40",
      note: "Plan not yet on cadence",
    }
  })()

  return (
    <div
      className={`transition-colors ${expanded ? "bg-slate-800/20" : ""} hover:bg-slate-800/25`}
    >
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            onToggle()
          }
        }}
        className="grid cursor-pointer grid-cols-12 items-center gap-x-3 gap-y-2 px-4 py-2.5"
      >
        {/* Customer */}
        <div className="col-span-12 min-w-0 sm:col-span-6 lg:col-span-4">
          <div className="flex items-center gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-edge bg-panel-2 font-mono text-[11px] font-semibold text-slate-300">
              {plan.customer.initials}
            </span>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-[13px] font-medium text-slate-200">
                  {plan.customer.name || "Unknown customer"}
                </span>
                <span
                  className={`inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-medium ${meta.badge}`}
                >
                  <span className={`h-1 w-1 rounded-full ${meta.dot}`} />
                  {meta.label}
                </span>
              </div>
              <div className="truncate font-mono text-[10px] tabular-nums text-slate-500">
                {plan.installmentCount} ×{" "}
                {formatCurrencyFull(plan.installmentAmountPaise)} ·{" "}
                {frequencyLabel(plan.frequency)}
              </div>
            </div>
          </div>
        </div>

        {/* Progress & ratio */}
        <div className="col-span-6 lg:col-span-3">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="font-mono text-[11px] tabular-nums text-slate-400">
              {formatCompact(plan.amountPaidPaise)}{" "}
              <span className="text-slate-600">/</span>{" "}
              {formatCompact(plan.totalAmountPaise)}
            </span>
            <span
              className={`rounded px-1 py-0.5 font-mono text-[10px] tabular-nums ${
                plan.status === "DEFAULTED"
                  ? "bg-rose-950/30 text-rose-400"
                  : plan.installmentsFailed > 0
                    ? "bg-amber-950/30 text-amber-400"
                    : "bg-emerald-950/30 text-emerald-400"
              }`}
            >
              {pct.toFixed(0)}%
            </span>
          </div>
          <div className="flex h-1.5 overflow-hidden rounded-full bg-slate-800/50">
            <div
              className="h-full bg-emerald-500/80"
              style={{
                width: `${plan.totalAmountPaise > 0 ? (plan.amountPaidPaise / plan.totalAmountPaise) * 100 : 0}%`,
              }}
            />
            {failedPortion > 0 && (
              <div
                className="h-full bg-rose-500/70"
                style={{
                  width: `${(failedPortion / plan.totalAmountPaise) * 100}%`,
                }}
              />
            )}
            {remaining > 0 && (
              <div
                className="h-full bg-slate-700/50"
                style={{ width: `${(remaining / plan.totalAmountPaise) * 100}%` }}
              />
            )}
          </div>
        </div>

        {/* Schedule & retry telemetry */}
        <div className="col-span-6 lg:col-span-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <span
                className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium ${telehealth.tone}`}
              >
                {plan.status !== "COMPLETED" &&
                  plan.status !== "CANCELLED" &&
                  plan.status !== "DEFAULTED" && (
                    <span className="h-1 w-1 animate-pulse rounded-full bg-current" />
                  )}
                {telehealth.tag}
              </span>
              <p className="mt-1 truncate text-[10px] text-slate-500">
                {telehealth.note}
              </p>
            </div>
            <svg
              className={`h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform ${
                expanded ? "rotate-180" : ""
              }`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </div>
        </div>

        {/* Actions */}
        <div className="col-span-12 flex items-center justify-end gap-2 lg:col-span-2">
          <Link
            to={`/case/${plan.caseId}`}
            onClick={(e) => e.stopPropagation()}
            className="shrink-0 rounded-md border border-edge px-2.5 py-1.5 text-[11px] font-medium text-slate-400 transition-colors hover:border-slate-600/50 hover:text-slate-200"
          >
            View case →
          </Link>
          <div onClick={(e) => e.stopPropagation()}>
            <RowActions plan={plan} onToggle={onToggle} />
          </div>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-slate-800/60 bg-canvas/40">
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="panel-sub m-3 mr-0 rounded-lg bg-panel-2 sm:mr-0 xl:mr-0">
              <PlanInstallmentTimeline
                caseId={plan.caseId}
                planId={plan.id}
              />
            </div>
            <div className="m-3 ml-0 xl:ml-0">
              <RetrySequencerPanel
                planId={plan.id}
                degraded={plan.degradation?.degraded}
                strategyLabel={plan.degradation?.strategyLabel}
                strategy={plan.degradation?.strategy}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}