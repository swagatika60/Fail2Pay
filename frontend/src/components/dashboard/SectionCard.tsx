import type { ReactNode } from "react"

/**
 * Standard dashboard section shell: a subtle panel with a compact,
 * uppercase-kicker header and an optional right-aligned action slot.
 */
export function SectionCard({
  label,
  title,
  subtitle,
  action,
  children,
  className = "",
  bodyClassName = "",
}: {
  label?: string
  title?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={`panel rounded-xl ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800/70 px-5 py-3.5">
        <div className="min-w-0">
          {label && (
            <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
              {label}
            </p>
          )}
          {title && (
            <h2 className="mt-0.5 text-sm font-semibold text-slate-100">{title}</h2>
          )}
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      <div className={bodyClassName || "p-5"}>{children}</div>
    </section>
  )
}
