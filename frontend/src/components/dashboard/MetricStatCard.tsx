import type { ReactNode } from "react"

/**
 * KPI stat card. Strictly: a micro-caption label, a tabular-num value, and a
 * muted subtitle. Semantic color is reserved for the value only — the icon
 * (if any) stays monochrome so the strip reads as one quiet grid.
 */

export type MetricTone = "neutral" | "emerald" | "amber" | "rose" | "muted"

export interface MetricStatCardProps {
  label: string
  value: string
  subtitle?: string
  tone?: MetricTone
  icon?: ReactNode
}

const VALUE_TONES: Record<MetricTone, string> = {
  neutral: "text-slate-100",
  emerald: "text-accent",
  amber: "text-warning",
  rose: "text-danger",
  muted: "text-slate-500",
}

export default function MetricStatCard({
  label,
  value,
  subtitle,
  tone = "neutral",
  icon,
}: MetricStatCardProps) {
  return (
    <div className="rounded-xl border border-edge bg-panel p-4 transition-colors duration-150 hover:border-edge-strong">
      <div className="flex items-center gap-1.5">
        {icon != null && <span className="flex shrink-0 items-center text-slate-500">{icon}</span>}
        <p className="truncate text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
          {label}
        </p>
      </div>
      <p
        className={`mt-1.5 font-mono text-lg font-semibold leading-tight tabular-nums ${VALUE_TONES[tone]}`}
      >
        {value}
      </p>
      {subtitle ? (
        <p className="mt-1 truncate text-[11px] text-slate-500">{subtitle}</p>
      ) : null}
    </div>
  )
}