import type { PaymentPlanListItem } from "../../types/operations"
import { formatINRFull, initials } from "../../lib/format"

/**
 * Strict, normalized domain types for the Payment Plans command center.
 *
 * All money fields are stored as integer paise (₹1 = 100 paise) — identical to
 * the backend wire format. UI components render them with `formatCurrencyFull`
 * (monospace tabular figures) so amounts never mix with awkward shorthand.
 */

export type PlanStatus =
  | "PROPOSED"
  | "ACCEPTED"
  | "ACTIVE"
  | "COMPLETED"
  | "CANCELLED"
  | "DEFAULTED"

export type InstallmentLegStatus =
  | "SCHEDULED"
  | "DUE"
  | "PROCESSING"
  | "PAID"
  | "FAILED"
  | "OVERDUE"
  | "CANCELLED"
  | "WAIVED"

export type PlanPreset = "all" | "needs_action" | "on_track"

export type PlanSortKey = "total" | "recovery" | "nextLeg" | "risk"

export type PlanSortDir = "asc" | "desc"

export interface InstallmentLeg {
  id: string
  installmentNumber: number
  amountPaise: number
  dueDate: string | null
  status: InstallmentLegStatus
  paidAt: string | null
  paidAmountPaise: number
  failedAt: string | null
  failureReason: string | null
  mandateStatus: string
  retryAttempts: number
  razorpayPaymentId: string | null
}

export interface PlanDegradationSummary {
  degraded: boolean
  failThreshold: number
  failedCount: number
  strategy: string | null
  strategyLabel: string | null
}

export interface PlanProgressSummary {
  paidInstallments: number
  failedInstallments: number
  totalInstallments: number
  remainingInstallments: number
  paidAmountPaise: number
  remainingAmountPaise: number
  percentPaid: number
}

export interface PlanCustomer {
  name: string | null
  email: string | null
  phone: string | null
  initials: string
}

export interface PaymentPlan {
  id: string
  caseId: string
  customer: PlanCustomer
  status: PlanStatus
  totalAmountPaise: number
  installmentAmountPaise: number
  installmentCount: number
  frequency: string
  currency: string
  amountPaidPaise: number
  installmentsPaid: number
  installmentsFailed: number
  customerMessage: string | null
  agreedAt: string | null
  created: string | null
  firstPaymentDue: string | null
  lastPaymentDate: string | null
  completedAt: string | null
  degradation: PlanDegradationSummary
  progress: PlanProgressSummary
  caseStatus: string | null
  caseRiskLevel: string | null
}

/** Map a backend plan-list row into the normalized command-center shape. */
export function toPaymentPlan(raw: PaymentPlanListItem): PaymentPlan {
  return {
    id: raw.id,
    caseId: raw.case_id,
    customer: {
      name: raw.customer_name,
      email: raw.customer_email,
      phone: raw.customer_phone,
      initials: initials(raw.customer_name),
    },
    status: (raw.status ?? "PROPOSED") as PlanStatus,
    totalAmountPaise: raw.total_amount,
    installmentAmountPaise: raw.installment_amount,
    installmentCount: raw.number_of_installments,
    frequency: raw.frequency,
    currency: raw.currency ?? "INR",
    amountPaidPaise: raw.amount_paid,
    installmentsPaid: raw.installments_paid,
    installmentsFailed: raw.installments_failed,
    customerMessage: raw.customer_message,
    agreedAt: raw.agreed_at,
    created: raw.created_at,
    firstPaymentDue: raw.first_payment_date,
    lastPaymentDate: raw.last_payment_date,
    completedAt: raw.completed_at,
    degradation: {
      degraded: raw.degradation.degraded,
      failThreshold: raw.degradation.fail_threshold,
      failedCount: raw.degradation.failed_count,
      strategy: raw.degradation.strategy,
      strategyLabel: raw.degradation.strategy_label,
    },
    progress: {
      paidInstallments: raw.progress.paid_installments,
      failedInstallments: raw.progress.failed_installments,
      totalInstallments: raw.progress.total_installments,
      remainingInstallments: raw.progress.remaining_installments,
      paidAmountPaise: raw.progress.paid_amount,
      remainingAmountPaise: raw.progress.remaining_amount,
      percentPaid: raw.progress.percent_paid,
    },
    caseStatus: raw.case_status,
    caseRiskLevel: raw.case_risk_level,
  }
}

interface RawInstallmentLeg {
  id: string
  installment_number: number
  amount: number
  due_date: string | null
  status: string
  paid_at: string | null
  paid_amount: number
  failed_at: string | null
  failure_reason: string | null
  razorpay_payment_id: string | null
}

const LEG_MANDATE_STATUS: Record<string, string> = {
  PAID: "Paid via mandate",
  SCHEDULED: "Mandate active",
  PROCESSING: "Debit in flight",
  DUE: "Awaiting debit",
  FAILED: "Mandate failed",
  OVERDUE: "Retry queued",
  CANCELLED: "Mandate cancelled",
  WAIVED: "Waived",
}

export function toInstallmentLegs(
  raw: RawInstallmentLeg[],
): InstallmentLeg[] {
  return raw.map((leg) => {
    const status = (leg.status ?? "SCHEDULED") as InstallmentLegStatus
    return {
      id: leg.id,
      installmentNumber: leg.installment_number,
      amountPaise: leg.amount,
      dueDate: leg.due_date,
      status,
      paidAt: leg.paid_at,
      paidAmountPaise: leg.paid_amount,
      failedAt: leg.failed_at,
      failureReason: leg.failure_reason,
      mandateStatus: LEG_MANDATE_STATUS[status] ?? "Mandate active",
      retryAttempts: status === "FAILED" || status === "OVERDUE" ? 1 : 0,
      razorpayPaymentId: leg.razorpay_payment_id,
    }
  })
}

// ---------------------------------------------------------------
// Derived analytics / sort helpers
// ---------------------------------------------------------------

export const OPEN_STATUSES: ReadonlySet<PlanStatus> = new Set([
  "PROPOSED",
  "ACCEPTED",
  "ACTIVE",
])

const FREQUENCY_INTERVAL_DAYS: Record<string, number> = {
  weekly: 7,
  biweekly: 14,
  fortnightly: 14,
  monthly: 30,
  quarterly: 90,
}

/** Live "next due leg" estimate derived from cadence + paid count. */
export function estimatedNextLegDue(plan: PaymentPlan): string | null {
  if (
    plan.status === "COMPLETED" ||
    plan.status === "CANCELLED" ||
    plan.installmentsPaid >= plan.installmentCount
  ) {
    return null
  }
  const intervalDays =
    FREQUENCY_INTERVAL_DAYS[plan.frequency.toLowerCase()] ?? 7
  const base = plan.firstPaymentDue || plan.agreedAt || plan.created
  if (!base) return plan.lastPaymentDate || plan.created
  const due = new Date(base)
  if (Number.isNaN(due.getTime())) return plan.lastPaymentDate || plan.created
  due.setUTCDate(due.getUTCDate() + plan.installmentsPaid * intervalDays)
  return due.toISOString()
}

export function isPlanOpen(plan: PaymentPlan): boolean {
  return OPEN_STATUSES.has(plan.status)
}

export function planAdherence(plan: PaymentPlan): number | null {
  const settled = plan.installmentsPaid + plan.installmentsFailed
  if (settled === 0) return null
  return (plan.installmentsPaid / settled) * 100
}

/** Deterministic risk score: severity + fail volume + degradation + terminal. */
export function planRiskScore(plan: PaymentPlan): number {
  const severity = { HIGH: 3, MEDIUM: 2, LOW: 1 }[plan.caseRiskLevel ?? ""] ?? 0
  const failPenalty = plan.installmentsFailed
  const degradedPenalty = plan.degradation.degraded ? 2 : 0
  const terminalPenalty = plan.status === "DEFAULTED" ? 3 : 0
  return severity + failPenalty + degradedPenalty + terminalPenalty
}

export function riskLevelLabel(plan: PaymentPlan): string {
  const score = planRiskScore(plan)
  if (score >= 6) return "High"
  if (score >= 3) return "Med"
  return "Low"
}

/** Failure portion (paise) to carve out of the inline progress bar. */
export function failedPortionPaise(plan: PaymentPlan): number {
  if (plan.installmentsFailed === 0 || plan.totalAmountPaise === 0) return 0
  return Math.min(
    plan.installmentsFailed * plan.installmentAmountPaise,
    Math.max(0, plan.totalAmountPaise - plan.amountPaidPaise),
  )
}

export function formatCurrencyFull(paise: number): string {
  return formatINRFull(paise)
}

export function formatCompact(paise: number): string {
  const rupees = Number(paise) / 100
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(1)}L`
  if (rupees >= 1000) return `₹${(rupees / 1000).toFixed(1)}k`
  return `₹${rupees.toLocaleString("en-IN")}`
}