export interface StatusMeta {
  label: string
  badge: string
  dot: string
  text: string
}

export const CASE_STATUS_META: Record<string, StatusMeta> = {
  AT_RISK: {
    label: "At Risk",
    badge: "bg-red-500/10 text-red-400 border-red-500/30",
    dot: "bg-red-400",
    text: "text-red-400",
  },
  RECOVERY_IN_PROGRESS: {
    label: "In Progress",
    badge: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    dot: "bg-amber-400",
    text: "text-amber-400",
  },
  PROMISED: {
    label: "Promised",
    badge: "bg-blue-500/10 text-blue-400 border-blue-500/30",
    dot: "bg-blue-400",
    text: "text-blue-400",
  },
  ENGAGED: {
    label: "Engaged",
    badge: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30",
    dot: "bg-cyan-400",
    text: "text-cyan-400",
  },
  PAYMENT_PLAN: {
    label: "Payment Plan",
    badge: "bg-indigo-500/10 text-indigo-400 border-indigo-500/30",
    dot: "bg-indigo-400",
    text: "text-indigo-400",
  },
  SCHEDULED: {
    label: "Scheduled",
    badge: "bg-purple-500/10 text-purple-400 border-purple-500/30",
    dot: "bg-purple-400",
    text: "text-purple-400",
  },
  PARTIALLY_RECOVERED: {
    label: "Partially Recovered",
    badge: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
    dot: "bg-yellow-400",
    text: "text-yellow-400",
  },
  RECOVERED: {
    label: "Recovered",
    badge: "bg-green-500/10 text-green-400 border-green-500/30",
    dot: "bg-green-400",
    text: "text-green-400",
  },
  LOST: {
    label: "Lost",
    badge: "bg-gray-500/10 text-gray-400 border-gray-500/30",
    dot: "bg-gray-500",
    text: "text-gray-400",
  },
  STOPPED: {
    label: "Stopped",
    badge: "bg-slate-500/10 text-slate-400 border-slate-500/30",
    dot: "bg-slate-500",
    text: "text-slate-400",
  },
}

export const RISK_META: Record<string, StatusMeta> = {
  HIGH: {
    label: "High",
    badge: "bg-red-500/10 text-red-400 border-red-500/30",
    dot: "bg-red-400",
    text: "text-red-400",
  },
  MEDIUM: {
    label: "Medium",
    badge: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    dot: "bg-amber-400",
    text: "text-amber-400",
  },
  LOW: {
    label: "Low",
    badge: "bg-green-500/10 text-green-400 border-green-500/30",
    dot: "bg-green-400",
    text: "text-green-400",
  },
}

export const PLAN_STATUS_META: Record<string, StatusMeta> = {
  PROPOSED: {
    label: "Proposed",
    badge: "bg-slate-500/10 text-slate-300 border-slate-500/30",
    dot: "bg-slate-400",
    text: "text-slate-300",
  },
  ACCEPTED: {
    label: "Accepted",
    badge: "bg-blue-500/10 text-blue-400 border-blue-500/30",
    dot: "bg-blue-400",
    text: "text-blue-400",
  },
  ACTIVE: {
    label: "Active",
    badge: "bg-purple-500/10 text-purple-400 border-purple-500/30",
    dot: "bg-purple-400",
    text: "text-purple-400",
  },
  COMPLETED: {
    label: "Completed",
    badge: "bg-green-500/10 text-green-400 border-green-500/30",
    dot: "bg-green-400",
    text: "text-green-400",
  },
  CANCELLED: {
    label: "Cancelled",
    badge: "bg-gray-500/10 text-gray-400 border-gray-500/30",
    dot: "bg-gray-500",
    text: "text-gray-400",
  },
  DEFAULTED: {
    label: "Defaulted",
    badge: "bg-red-500/10 text-red-400 border-red-500/30",
    dot: "bg-red-400",
    text: "text-red-400",
  },
}

export const INVOICE_STATUS_META: Record<string, StatusMeta> = {
  ISSUED: {
    label: "Issued",
    badge: "bg-blue-500/10 text-blue-400 border-blue-500/30",
    dot: "bg-blue-400",
    text: "text-blue-400",
  },
  PAID: {
    label: "Paid",
    badge: "bg-green-500/10 text-green-400 border-green-500/30",
    dot: "bg-green-400",
    text: "text-green-400",
  },
  EXPIRED: {
    label: "Expired",
    badge: "bg-gray-500/10 text-gray-400 border-gray-500/30",
    dot: "bg-gray-500",
    text: "text-gray-400",
  },
  CANCELLED: {
    label: "Cancelled",
    badge: "bg-gray-500/10 text-gray-400 border-gray-500/30",
    dot: "bg-gray-500",
    text: "text-gray-400",
  },
  DRAFT: {
    label: "Draft",
    badge: "bg-slate-500/10 text-slate-300 border-slate-500/30",
    dot: "bg-slate-400",
    text: "text-slate-300",
  },
}

export const CONVERSATION_STATUS_META: Record<string, StatusMeta> = {
  ACTIVE: {
    label: "Active",
    badge: "bg-green-500/10 text-green-400 border-green-500/30",
    dot: "bg-green-400",
    text: "text-green-400",
  },
  PAUSED: {
    label: "Paused",
    badge: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    dot: "bg-amber-400",
    text: "text-amber-400",
  },
  STOPPED: {
    label: "Stopped",
    badge: "bg-gray-500/10 text-gray-400 border-gray-500/30",
    dot: "bg-gray-500",
    text: "text-gray-400",
  },
  RESOLVED: {
    label: "Resolved",
    badge: "bg-green-500/10 text-green-400 border-green-500/30",
    dot: "bg-green-400",
    text: "text-green-400",
  },
}

export function caseMeta(status: string | null | undefined): StatusMeta {
  return CASE_STATUS_META[status ?? ""] ?? {
    label: status ?? "Unknown",
    badge: "bg-slate-700/40 text-slate-300 border-slate-600/40",
    dot: "bg-slate-400",
    text: "text-slate-300",
  }
}

export function riskMeta(risk: string | null | undefined): StatusMeta {
  return RISK_META[risk ?? ""] ?? {
    label: risk ?? "—",
    badge: "bg-slate-700/40 text-slate-300 border-slate-600/40",
    dot: "bg-slate-400",
    text: "text-slate-300",
  }
}