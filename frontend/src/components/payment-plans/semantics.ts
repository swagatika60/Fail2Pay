import type {
  InstallmentLegStatus,
  PaymentPlan,
} from "./types"

export interface SemanticMeta {
  label: string
  badge: string
  dot: string
}

/**
 * Calibrated, low-chroma semantic badges. No neon pills: subtle
 * `*-950/40` fills with hairline `*-800/40` borders, per the command-center
 * design system.
 */
export const PLAN_SEMANTIC_META = (
  plan: PaymentPlan,
): SemanticMeta => {
  const degraded = plan.degradation?.degraded || plan.installmentsFailed > 0
  switch (plan.status) {
    case "ACTIVE":
      return degraded
        ? {
            label: "At Risk",
            badge: "bg-amber-950/40 text-amber-400 border border-amber-800/40",
            dot: "bg-amber-400",
          }
        : {
            label: "On Track",
            badge: "bg-emerald-950/40 text-emerald-400 border border-emerald-800/40",
            dot: "bg-emerald-400",
          }
    case "ACCEPTED":
      return {
        label: "Accepted",
        badge: "bg-indigo-950/40 text-indigo-400 border border-indigo-800/40",
        dot: "bg-indigo-400",
      }
    case "PROPOSED":
      return {
        label: "Proposed",
        badge: "bg-indigo-950/40 text-indigo-400 border border-indigo-800/40",
        dot: "bg-indigo-400",
      }
    case "COMPLETED":
      return {
        label: "Completed",
        badge: "bg-emerald-950/40 text-emerald-400 border border-emerald-800/40",
        dot: "bg-emerald-400",
      }
    case "DEFAULTED":
      return {
        label: "Defaulted",
        badge: "bg-rose-950/40 text-rose-400 border border-rose-800/40",
        dot: "bg-rose-400",
      }
    case "CANCELLED":
      return {
        label: "Cancelled",
        badge: "bg-slate-800/60 text-slate-400 border border-slate-700/60",
        dot: "bg-slate-500",
      }
    default:
      return {
        label: plan.status,
        badge: "bg-slate-800/60 text-slate-400 border border-slate-700/60",
        dot: "bg-slate-500",
      }
  }
}

const LEG_META: Record<InstallmentLegStatus, SemanticMeta> = {
  PAID: {
    label: "Paid",
    badge: "bg-emerald-950/40 text-emerald-400 border border-emerald-800/40",
    dot: "bg-emerald-400",
  },
  SCHEDULED: {
    label: "Scheduled",
    badge: "bg-slate-800/50 text-slate-400 border border-slate-700/50",
    dot: "bg-slate-400",
  },
  DUE: {
    label: "Due",
    badge: "bg-amber-950/40 text-amber-400 border border-amber-800/40",
    dot: "bg-amber-400",
  },
  PROCESSING: {
    label: "Processing",
    badge: "bg-indigo-950/40 text-indigo-400 border border-indigo-800/40",
    dot: "bg-indigo-400",
  },
  FAILED: {
    label: "Failed",
    badge: "bg-rose-950/40 text-rose-400 border border-rose-800/40",
    dot: "bg-rose-400",
  },
  OVERDUE: {
    label: "Overdue",
    badge: "bg-rose-950/40 text-rose-400 border border-rose-800/40",
    dot: "bg-rose-400",
  },
  CANCELLED: {
    label: "Cancelled",
    badge: "bg-slate-800/50 text-slate-400 border border-slate-700/50",
    dot: "bg-slate-500",
  },
  WAIVED: {
    label: "Waived",
    badge: "bg-slate-800/50 text-slate-400 border border-slate-700/50",
    dot: "bg-slate-500",
  },
}

export function legMeta(status: InstallmentLegStatus): SemanticMeta {
  return LEG_META[status] ?? LEG_META.SCHEDULED
}