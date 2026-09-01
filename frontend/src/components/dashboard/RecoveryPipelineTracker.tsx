import { Fragment, type ReactNode } from "react"
import { ChevronRight } from "lucide-react"
import { formatINR } from "../../lib/format"

/**
 * Recovery Pipeline — the revenue-map taxonomy:
 *
 *     At Risk → Contacted → Engaged → Promised → Payment Plan → Recovered
 *
 * Renders as a compact, self-contained horizontal flow (flex-wrap, no
 * horizontal scroll). Stage nodes are monochrome: a numbered badge + label,
 * tabular-num amount, and case count. Only money carries semantic tone —
 * amber for at-risk/pending, emerald for verified recovered.
 */

export interface RecoveryPipelineStage {
  key: string
  label: string
  amount: number
  count: number
}

export interface RecoveryPipelineTrackerProps {
  stages: RecoveryPipelineStage[]
  totalCases?: number
  footer?: ReactNode
}

const MONEY_TONES: Record<string, string> = {
  at_risk: "text-amber-400",
  recovered: "text-emerald-400",
}

export default function RecoveryPipelineTracker({
  stages,
  totalCases,
  footer,
}: RecoveryPipelineTrackerProps) {
  if (stages.length === 0) {
    return (
      <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-5">
        <TrackerHeader totalCases={totalCases} />
        <p className="mt-4 text-sm text-zinc-500">No pipeline data yet.</p>
      </section>
    )
  }

  return (
    <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-5 transition-colors duration-150 hover:border-zinc-700">
      <TrackerHeader totalCases={totalCases} />
      <div className="mt-5 flex flex-wrap items-center gap-y-4">
        {stages.map((stage, i) => (
          <Fragment key={stage.key}>
            {/* Stage node */}
            <div className="flex min-w-[92px] items-start gap-2.5">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-zinc-800 bg-zinc-800/50 font-mono text-[10px] font-semibold text-zinc-400">
                {i + 1}
              </span>
              <div className="min-w-0">
                <p className="text-[11px] font-medium text-zinc-300">{stage.label}</p>
                <p
                  className={`mt-0.5 font-mono text-sm font-semibold leading-none tabular-nums ${
                    MONEY_TONES[stage.key] ?? "text-zinc-100"
                  }`}
                >
                  {formatINR(stage.amount)}
                </p>
                <p className="mt-1 text-[10px] tabular-nums text-zinc-500">
                  {stage.count > 0 ? `${stage.count.toLocaleString("en-IN")} cases` : "\u00a0"}
                </p>
              </div>
            </div>
            {/* Chevron connector */}
            {i < stages.length - 1 && (
              <ChevronRight className="mx-1 h-3.5 w-3.5 shrink-0 text-zinc-700" />
            )}
          </Fragment>
        ))}
      </div>
      {footer ? <div className="mt-4 border-t border-zinc-800/80 pt-3">{footer}</div> : null}
    </section>
  )
}

function TrackerHeader({ totalCases }: { totalCases?: number }) {
  return (
    <div className="flex items-baseline gap-2">
      <h2 className="text-sm font-semibold tracking-tight text-zinc-100">Recovery Pipeline</h2>
      {totalCases != null ? (
        <span className="text-[11px] tabular-nums text-zinc-500">
          {totalCases.toLocaleString("en-IN")} total cases
        </span>
      ) : null}
    </div>
  )
}