import type { ReactNode } from "react"

export interface StatCardProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: "default" | "success" | "danger" | "warning" | "info"
  icon?: ReactNode
}

const TONES: Record<string, { value: string; panel: string }> = {
  default: { value: "text-slate-100", panel: "border-slate-800 bg-slate-900" },
  success: {
    value: "text-green-400",
    panel: "border-green-500/30 bg-green-950/20",
  },
  danger: {
    value: "text-red-400",
    panel: "border-red-500/30 bg-red-950/20",
  },
  warning: {
    value: "text-amber-400",
    panel: "border-amber-500/30 bg-amber-950/20",
  },
  info: { value: "text-blue-400", panel: "border-blue-500/30 bg-blue-950/20" },
}

export function StatCard({
  label,
  value,
  sub,
  tone = "default",
  icon,
}: StatCardProps) {
  const t = TONES[tone]
  return (
    <div className={`rounded-xl border p-4 ${t.panel}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-xs font-medium text-slate-400">{label}</p>
        {icon && <span className="shrink-0 text-slate-500">{icon}</span>}
      </div>
      <p className={`mt-1.5 text-2xl font-bold tracking-tight ${t.value}`}>
        {value}
      </p>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}