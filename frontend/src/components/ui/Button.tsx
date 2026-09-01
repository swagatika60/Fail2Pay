import { forwardRef, type ButtonHTMLAttributes } from "react"

type Variant = "primary" | "secondary" | "ghost" | "danger"
type Size = "sm" | "md"

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

const VARIANT: Record<Variant, string> = {
  primary:
    "border border-slate-600/60 bg-slate-100 text-slate-900 hover:bg-white hover:border-white",
  secondary:
    "border border-slate-700/70 bg-slate-800/40 text-slate-200 hover:bg-slate-800/70 hover:border-slate-600",
  ghost:
    "border border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/50",
  danger:
    "border border-rose-500/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/15 hover:border-rose-500/50",
}

const SIZE: Record<Size, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-9 px-3.5 text-sm",
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    { variant = "secondary", size = "sm", className = "", ...props },
    ref,
  ) {
    return (
      <button
        ref={ref}
        type="button"
        className={`inline-flex shrink-0 select-none items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${className}`}
        {...props}
      />
    )
  },
)
