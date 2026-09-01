import { formatINR, formatPercent } from "../../lib/format"

/**
 * Reconciliation — Attempted vs Verified Captured.
 *
 * The 3-column summary describes the outreach pool (attempted / settled /
 * outstanding). The multi-segment bar reconciles the FULL failed volume into
 * three buckets, each styled strictly by meaning:
 *
 *   Settled       → emerald
 *   In Pipeline   → amber   (at-risk / pending)
 *   Unrecoverable → zinc    (closed / opted out)
 */

export interface ReconciliationProgressProps {
  /** Failed volume the reconciliation spans (denominator for segment widths). */
  total: number
  settled: number
  inPipeline: number
  unrecoverable: number
  /** Attempted-pool summary (top strip). */
  attempted: number
  outstanding: number
  capturedPayments?: number
}

export default function ReconciliationProgress({
  total,
  settled,
  inPipeline,
  unrecoverable,
  attempted,
  outstanding,
  capturedPayments = 0,
}: ReconciliationProgressProps) {
  const pct = (value: number) => (total > 0 ? Math.max(0, Math.min((value / total) * 100, 100)) : 0)
  const settledW = pct(settled)
  const pipelineW = pct(inPipeline)
  const unrecoverableW = pct(unrecoverable)

  const hasData = total > 0

  return (
    <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-5 transition-colors duration-150 hover:border-zinc-700">
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold tracking-tight text-zinc-100">
          Reconciliation: Attempted vs Verified Captured
        </h2>
      </div>

      {/* Attempted-pool summary — 3-column comparative strip */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <SummaryStat
          label="Attempted Outreach Pool"
          value={formatINR(attempted)}
          note="volume we engaged"
          tone="text-zinc-100"
        />
        <SummaryStat
          label="Verified Settled"
          value={formatINR(settled)}
          note={`${capturedPayments} captured payments`}
          tone="text-emerald-400"
        />
        <SummaryStat
          label="Outstanding in Pipeline"
          value={formatINR(outstanding)}
          note="in-flight · promised"
          tone="text-amber-400"
        />
      </div>

      {/* Multi-segment reconciliation bar */}
      <div className="mt-5">
        {!hasData ? (
          <p className="text-sm text-zinc-500">
            No reconciliation data yet — run the Batch Simulation or wait for real failed payments.
          </p>
        ) : (
          <>
            <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-zinc-950">
              {settledW > 0 && (
                <div className="h-full bg-emerald-500" style={{ width: `${settledW}%` }} />
              )}
              {pipelineW > 0 && (
                <div className="h-full bg-amber-500" style={{ width: `${pipelineW}%` }} />
              )}
              {unrecoverableW > 0 && (
                <div className="h-full bg-zinc-700" style={{ width: `${unrecoverableW}%` }} />
              )}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1.5">
              <SegmentLegend
                dot="bg-emerald-500"
                label="Settled"
                value={formatINR(settled)}
                pct={formatPercent(settled / (total || 1))}
              />
              <SegmentLegend
                dot="bg-amber-500"
                label="In Pipeline"
                value={formatINR(inPipeline)}
                pct={formatPercent(inPipeline / (total || 1))}
              />
              <SegmentLegend
                dot="bg-zinc-600"
                label="Unrecoverable"
                value={formatINR(unrecoverable)}
                pct={formatPercent(unrecoverable / (total || 1))}
              />
              <span className="ml-auto text-[10px] text-zinc-600">shares of total failed volume</span>
            </div>
          </>
        )}
      </div>
    </section>
  )
}

function SummaryStat({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: string
  note: string
  tone: string
}) {
  return (
    <div className="rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3.5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400">
        {label}
      </p>
      <p className={`mt-1 font-mono text-xl font-semibold leading-tight tabular-nums ${tone}`}>
        {value}
      </p>
      <p className="mt-0.5 text-[10px] text-zinc-600">{note}</p>
    </div>
  )
}

function SegmentLegend({
  dot,
  label,
  value,
  pct,
}: {
  dot: string
  label: string
  value: string
  pct: string
}) {
  return (
    <span className="flex items-center gap-1.5 text-[10px] text-zinc-500">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      <span className="text-zinc-400">{label}</span>
      <span className="font-mono tabular-nums text-zinc-300">{value}</span>
      <span className="font-mono tabular-nums text-zinc-600">{pct}</span>
    </span>
  )
}