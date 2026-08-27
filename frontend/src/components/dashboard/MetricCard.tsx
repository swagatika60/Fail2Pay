interface MetricCardProps {
  title: string
  value: number
  prefix?: string
  suffix?: string
  color?: string
  subtitle?: string
}

function formatCurrency(amount: number): string {
  // Format as Indian currency (lakhs/crores)
  if (amount >= 10000000) {
    return `₹${(amount / 10000000).toFixed(2)} Cr`
  }
  if (amount >= 100000) {
    return `₹${(amount / 100000).toFixed(2)} L`
  }
  return `₹${amount.toLocaleString("en-IN")}`
}

export default function MetricCard({
  title,
  value,
  color = "text-slate-100",
  subtitle,
}: MetricCardProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <p className="text-sm font-medium text-slate-400">{title}</p>
      <p className={`mt-2 text-2xl font-bold ${color}`}>
        {formatCurrency(value)}
      </p>
      {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
    </div>
  )
}

export { formatCurrency }
