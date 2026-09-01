import { useId, type ReactNode } from "react"
import { ArrowDownRight, ArrowUpRight } from "lucide-react"
import { formatMoney } from "../../lib/format"

/** Back-compat classifier kept for shared case-detail components. */
export function formatCurrency(paise: number): string {
  return formatMoney(paise, "INR")
}

export type DeltaDirection = "up" | "down" | "flat"

export interface Delta {
  direction: DeltaDirection
  label: string
  /** Whether the change is favorable (drives accent color) or unfavorable. */
  favorable?: boolean
}

type Tone = "default" | "emerald" | "amber" | "rose"

const TONE_VALUE: Record<Tone, string> = {
  default: "text-slate-100",
  emerald: "text-emerald-400",
  amber: "text-amber-400",
  rose: "text-rose-400",
}

export interface MetricCardProps {
  label: string
  value: ReactNode
  /** Primary, tabular value rendered large. */
  delta?: Delta
  context?: ReactNode
  tone?: Tone
  /** Optional inline sparkline (series of numbers) rendered under the value. */
  spark?: number[]
  icon?: ReactNode
}

function DeltaBadge({ delta }: { delta: Delta }) {
  const { direction, label, favorable = true } = delta
  const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : null
  const color = direction === "flat"
    ? "text-slate-400"
    : favorable
      ? "text-emerald-400"
      : "text-rose-400"
  return (
    <span className={`inline-flex items-center gap-0.5 rounded-md bg-slate-800/60 px-1.5 py-0.5 text-[11px] font-medium ${color}`}>
      {Icon && <Icon className="h-3 w-3" strokeWidth={2} />}
      <span className="num">{label}</span>
    </span>
  )
}

function Sparkline({ data, gradientId }: { data: number[]; gradientId: string }) {
  if (data.length < 2) return null
  const max = Math.max(...data)
  const min = Math.min(...data)
  const range = max - min || 1
  const w = 96
  const h = 26
  const step = w / (data.length - 1)
  const points = data
    .map((v, i) => `${(i * step).toFixed(1)},${(h - ((v - min) / range) * (h - 4) - 2).toFixed(1)}`)
    .join(" ")
  const area = `0,${h} ${points} ${w},${h}`
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="h-[26px] w-full"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgb(52 211 153 / 0.25)" />
          <stop offset="100%" stopColor="rgb(52 211 153 / 0)" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gradientId})`} />
      <polyline
        points={points}
        fill="none"
        stroke="rgb(52 211 153 / 0.9)"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function MetricCard({
  label,
  value,
  delta,
  context,
  tone = "default",
  spark,
  icon,
}: MetricCardProps) {
  const sparkId = useId().replace(/:/g, "")
  return (
    <div className="panel flex flex-col rounded-xl p-5">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
          {label}
        </p>
        {icon && <span className="shrink-0 text-slate-500">{icon}</span>}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className={`text-2xl font-semibold tracking-tight ${TONE_VALUE[tone]}`}>
          {value}
        </span>
        {delta && (
          <span className="shrink-0">
            <DeltaBadge delta={delta} />
          </span>
        )}
      </div>
      {context && (
        <div className="mt-1.5 text-xs text-slate-500">{context}</div>
      )}
      {spark && (
        <div className="mt-3 rounded-md border border-slate-800/60 bg-slate-900/40 p-1.5">
          <Sparkline data={spark} gradientId={sparkId} />
        </div>
      )}
    </div>
  )
}
