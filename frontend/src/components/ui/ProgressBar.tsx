export function ProgressBar({
  value,
  total,
  className = "",
  barClassName = "bg-green-500",
}: {
  value: number
  total: number
  className?: string
  barClassName?: string
}) {
  const pct = total > 0 ? Math.min((Number(value) / Number(total)) * 100, 100) : 0
  return (
    <div className={`h-2 overflow-hidden rounded-full bg-slate-800 ${className}`}>
      <div
        className={`h-full rounded-full transition-all ${barClassName}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}