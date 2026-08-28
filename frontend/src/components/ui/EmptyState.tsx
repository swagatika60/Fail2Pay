import type { ReactNode } from "react"

export function EmptyState({
  icon = "📭",
  title,
  description,
  action,
}: {
  icon?: string
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-800 bg-slate-900/50 px-6 py-12 text-center">
      <span className="text-3xl">{icon}</span>
      <p className="mt-3 text-sm font-medium text-slate-300">{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-xs text-slate-500">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}