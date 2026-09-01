import { CheckCircle2, Ban, AlertTriangle } from "lucide-react"
import type { RecoveryPipelineStage } from "../../types/analytics"

/**
 * Unified Recovery Pipeline Tracker.
 *
 * The canonical spec pipeline:
 *
 *     FAILED → CONTACTED → ENGAGED → PROMISED → RECOVERED
 *                        └→ ESCALATED / HARD_DROPPED (terminal branches)
 *
 * `<PipelineTracker current="…">` highlights where a single case sits in the
 * pipeline; `<PipelineTracker stages={…}>` renders the aggregate dashboard view
 * (amount + case count under every stage, recovered is always verified money).
 */

const CANONICAL = ["FAILED", "CONTACTED", "ENGAGED", "PROMISED", "PAYMENT_PLAN", "RECOVERED"]

type NormalStage = {
  stage: string
  label: string
  amount?: number
  count?: number
}

export default function PipelineTracker({
  current,
  stages,
  compact = false,
}: {
  current?: string | null
  stages?: RecoveryPipelineStage[] | null
  compact?: boolean
}) {
  const overrides = new Map((stages ?? []).map((s) => [s.stage, s]))

  const base: NormalStage[] = CANONICAL.map((key) => {
    const o = overrides.get(key)
    return {
      stage: key,
      label: o?.label ?? key,
      amount: o?.amount,
      count: o?.count,
    }
  })

  const escalated = overrides.get("ESCALATED") || null
  const hardDropped = overrides.get("HARD_DROPPED") || null

  const idxOf = (s: string | null | undefined) => {
    if (!s) return -1
    const i = CANONICAL.indexOf(s)
    return i >= 0 ? i : -1
  }

  const currentIdx = idxOf(current)
  const terminal: "escalated" | "dropped" | null =
    current === "ESCALATED" ? "escalated" : current === "HARD_DROPPED" ? "dropped" : null

  return (
    <div className="rounded-xl border border-edge bg-panel px-5 py-4">
      <div className="flex items-center">
        {base.map((step, i) => {
          const state =
            terminal === "dropped" && i > 0
              ? "stopped"
              : i < currentIdx
                ? "done"
                : i === currentIdx
                  ? "active"
                  : "pending"
          return (
            <div key={step.stage} className="flex flex-1 items-center">
              <StepNode step={step} state={state} i={i} compact={compact} />
              {i < base.length - 1 && (
                <Connector state={state} stepIndex={i} runTop={compact && currentIdx > i} />
              )}
            </div>
          )
        })}
      </div>

      {/* Terminal branches */}
      {(terminal || escalated || hardDropped) && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-edge pt-3">
          {terminal === "escalated" || escalated ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/25 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold text-amber-400">
              <AlertTriangle className="h-3 w-3" />
              Escalated — human review required
              {escalated?.count ? ` · ${escalated.count} cases · ${fmtAmount(escalated.amount)}` : ""}
            </span>
          ) : null}
          {terminal === "dropped" || hardDropped ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-danger/25 bg-danger-soft px-2.5 py-1 text-[10px] font-semibold text-danger">
              <Ban className="h-3 w-3" />
              Hard dropped — recovery stopped / opted out
              {hardDropped?.count ? ` · ${hardDropped.count} cases · ${fmtAmount(hardDropped.amount)}` : ""}
            </span>
          ) : null}
          {!terminal && !escalated && !hardDropped ? null : (
            <span className="ml-auto text-[10px] text-slate-600">Recovered amount is verified captured revenue only</span>
          )}
        </div>
      )}
    </div>
  )
}

function StepNode({ step, state, i, compact }: { step: NormalStage; state: string; i: number; compact: boolean }) {
  const tone =
    state === "done"
      ? "border-accent/40 bg-accent/15 text-accent"
      : state === "active"
        ? "border-accent/60 bg-accent/25 text-accent"
        : state === "stopped"
          ? "border-danger/40 bg-danger/15 text-danger"
          : "border-edge-strong bg-panel-2 text-slate-600"

  return (
    <div className="flex flex-col items-center">
      <div
        className={`flex items-center justify-center rounded-full border font-bold transition-colors ${
          state === "done" || state === "active" ? "h-7 w-7" : "h-6 w-6"
        } ${tone}`}
      >
        {state === "done" ? <CheckCircle2 className="h-3.5 w-3.5" /> :
          state === "stopped" ? <Ban className="h-3 w-3" /> :
            <span className="text-[10px]">{i + 1}</span>}
      </div>
      <span
        className={`mt-1.5 text-center text-[10px] font-medium ${
          state === "done" ? "text-accent"
            : state === "active" ? "text-accent"
              : state === "stopped" ? "text-danger"
                : "text-slate-600"
        }`}
      >
        {step.label}
      </span>
      {!compact && step.amount != null && (
        <span className={`mt-0.5 font-mono text-[10px] font-semibold ${state === "done" ? "text-accent/70" : "text-slate-500"}`}>
          {fmtAmount(step.amount)}
        </span>
      )}
      {!compact && step.count != null && step.count > 0 && (
        <span className="text-[9px] text-slate-600">{step.count} case{step.count === 1 ? "" : "s"}</span>
      )}
    </div>
  )
}

function Connector({ state, stepIndex, runTop }: { state: string; stepIndex: number; runTop: boolean }) {
  let color = "bg-edge"
  if (state === "done" || state === "active") color = "bg-accent/40"
  if (state === "stopped") color = "bg-danger/25"
  return (
    <div className={`mx-1.5 h-0.5 flex-1 rounded-full ${color}`}>
      {runTop && <div className="h-0.5 w-full animate-pulse rounded-full bg-accent/60" />}
      <span className="sr-only">{stepIndex}</span>
    </div>
  )
}

function fmtAmount(paise?: number | null): string {
  if (paise == null) return "—"
  return `₹${Math.round(Number(paise) / 100).toLocaleString("en-IN")}`
}