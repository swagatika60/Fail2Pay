import { Fragment } from "react"
import { ArrowDown } from "lucide-react"

export interface FunnelStage {
  key: string
  label: string
  amount: number
  count: number
  tone?: "default" | "amber" | "emerald" | "slate"
}

const BAR_TONE: Record<string, string> = {
  default: "from-slate-600/80 to-slate-700/60",
  amber: "from-amber-500/70 to-amber-600/40",
  emerald: "from-emerald-500/70 to-emerald-600/40",
  slate: "from-slate-700 to-slate-800",
}

const TEXT_TONE: Record<string, string> = {
  default: "text-slate-200",
  amber: "text-amber-300",
  emerald: "text-emerald-300",
  slate: "text-slate-300",
}

/**
 * Horizontal, tapered revenue-conversion funnel. The bar width is proportional
 * to each stage's amount, so the shrinking silhouette reads as drop-off.
 * Only recovered money is verified; everything upstream is "at risk" in-train.
 *
 * Conversion is always money-based (stage amount ÷ previous stage amount) so
 * stages must be nested sub-pools of the entering volume — otherwise the
 * ratio would exceed 100% and mislead.
 */
export function RecoveryFunnel({
  stages,
  formatAmount,
}: {
  stages: FunnelStage[]
  formatAmount: (amount: number) => string
}) {
  if (stages.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">No pipeline data yet.</p>
    )
  }

  const maxAmount = Math.max(...stages.map((s) => s.amount), 1)
  const maxCount = Math.max(...stages.map((s) => s.count), 1)

  return (
    <div className="flex flex-col gap-3">
      {stages.map((stage, i) => {
        const prev = stages[i - 1]
        // Money in ÷ money out of the previous stage. Stage amounts must be
        // nested pools (see docstring) so this is always a sane 0-100% rate.
        const conversion = prev
          ? prev.amount > 0
            ? (stage.amount / prev.amount) * 100
            : 0
          : null
        const widthPct = Math.max((stage.amount / maxAmount) * 100, 6)
        const countPct = prev ? Math.max((stage.count / maxCount) * 100, 30) : 100
        const tone = stage.tone ?? "default"
        return (
          <Fragment key={stage.key}>
            <div className="flex items-center gap-4">
              {/* Stage body */}
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-xs font-medium text-slate-300">
                    {stage.label}
                  </span>
                  <span className="shrink-0 text-xs text-slate-500 num">
                    {stage.count} cases
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <div
                    className={`h-3 overflow-hidden rounded-sm bg-gradient-to-r ${BAR_TONE[tone]}`}
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <span className={`text-sm font-semibold tabular-nums ${TEXT_TONE[tone]}`}>
                    {formatAmount(stage.amount)}
                  </span>
                  {conversion !== null && (
                    <span className="text-[11px] text-slate-500 num">
                      {conversion.toFixed(0)}% of prev
                    </span>
                  )}
                </div>
              </div>

              {/* Case-count density bar (side-by-side falloff) */}
              <div className="hidden h-8 w-10 shrink-0 items-end justify-center overflow-hidden rounded-sm border border-slate-800/60 bg-slate-900/50 sm:flex">
                <div
                  className={`w-full ${BAR_TONE[tone]}`}
                  style={{ height: `${countPct}%` }}
                />
              </div>
            </div>
            {i < stages.length - 1 && (
              <div className="flex items-center gap-2 pl-1">
                <ArrowDown className="h-3 w-3 text-slate-600" />
                <span className="h-px flex-1 bg-slate-800/60" />
              </div>
            )}
          </Fragment>
        )
      })}
    </div>
  )
}
