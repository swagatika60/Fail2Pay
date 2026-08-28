import type { PaymentPlan } from "../../types/analytics"
import { formatCurrency } from "./MetricCard"

interface PaymentPlanViewProps {
  plans: PaymentPlan[]
}

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  PROPOSED: { bg: "bg-blue-500/20", text: "text-blue-400" },
  ACCEPTED: { bg: "bg-indigo-500/20", text: "text-indigo-400" },
  ACTIVE: { bg: "bg-green-500/20", text: "text-green-400" },
  COMPLETED: { bg: "bg-green-500/20", text: "text-green-400" },
  CANCELLED: { bg: "bg-gray-500/20", text: "text-gray-400" },
  DEFAULTED: { bg: "bg-red-500/20", text: "text-red-400" },
}

const INST_STATUS_STYLES: Record<string, { bg: string; text: string; icon: string }> = {
  SCHEDULED: { bg: "bg-slate-600/30", text: "text-slate-400", icon: "📅" },
  DUE: { bg: "bg-amber-500/20", text: "text-amber-400", icon: "⏰" },
  PAID: { bg: "bg-green-500/20", text: "text-green-400", icon: "✅" },
  FAILED: { bg: "bg-red-500/20", text: "text-red-400", icon: "❌" },
  OVERDUE: { bg: "bg-red-500/20", text: "text-red-400", icon: "🚨" },
  CANCELLED: { bg: "bg-gray-500/20", text: "text-gray-400", icon: "🚫" },
}

function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return "—"
  return new Date(dateStr).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

export default function PaymentPlanView({ plans }: PaymentPlanViewProps) {
  if (plans.length === 0) {
    return (
      <div className="rounded-lg bg-slate-800/50 p-4 text-center text-sm text-slate-500">
        No payment plans
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {plans.map((plan) => {
        const style = STATUS_STYLES[plan.status] || STATUS_STYLES.ACTIVE
        const paidPercent =
          plan.total_amount > 0
            ? Math.min(100, Math.round((plan.amount_paid / plan.total_amount) * 100))
            : 0

        return (
          <div
            key={plan.id}
            className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4"
          >
            {/* Plan header */}
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${style.bg} ${style.text}`}
                >
                  {plan.status}
                </span>
                <span className="text-sm font-semibold text-slate-200">
                  {plan.number_of_installments}× {formatCurrency(plan.installment_amount)}{" "}
                  <span className="text-slate-500">{plan.frequency}</span>
                </span>
              </div>
              <span className="text-xs text-slate-500">
                {formatDateTime(plan.created_at)}
              </span>
            </div>

            {/* Revenue map */}
            <div className="mb-3 grid grid-cols-4 gap-2 text-center text-xs">
              <div className="rounded bg-slate-900/50 p-2">
                <div className="text-slate-500">Original</div>
                <div className="font-semibold text-slate-200">
                  {formatCurrency(plan.total_amount)}
                </div>
              </div>
              <div className="rounded bg-green-900/20 p-2">
                <div className="text-green-500">Paid</div>
                <div className="font-semibold text-green-400">
                  {formatCurrency(plan.amount_paid)}
                </div>
              </div>
              <div className="rounded bg-amber-900/20 p-2">
                <div className="text-amber-500">Remaining</div>
                <div className="font-semibold text-amber-400">
                  {formatCurrency(plan.total_amount - plan.amount_paid)}
                </div>
              </div>
              <div className="rounded bg-slate-900/50 p-2">
                <div className="text-slate-500">Progress</div>
                <div className="font-semibold text-slate-200">{paidPercent}%</div>
              </div>
            </div>

            {/* Progress bar */}
            <div className="mb-3">
              <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full rounded-full bg-green-500 transition-all"
                  style={{ width: `${paidPercent}%` }}
                />
              </div>
            </div>

            {/* Installments */}
            {plan.installments.length > 0 && (
              <div>
                <h4 className="mb-2 text-xs font-medium text-slate-400">
                  Installments ({plan.installments_paid}/{plan.number_of_installments} paid)
                </h4>
                <div className="space-y-1.5">
                  {plan.installments.map((inst) => {
                    const instStyle =
                      INST_STATUS_STYLES[inst.status] || INST_STATUS_STYLES.SCHEDULED
                    return (
                      <div
                        key={inst.id}
                        className="flex items-center justify-between rounded bg-slate-900/30 px-3 py-1.5 text-xs"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-slate-500">#{inst.installment_number}</span>
                          <span className="font-medium text-slate-200">
                            {formatCurrency(inst.amount)}
                          </span>
                          <span
                            className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 ${instStyle.bg} ${instStyle.text}`}
                          >
                            {instStyle.icon} {inst.status}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-slate-500">
                          <span>Due: {formatDateTime(inst.due_date)}</span>
                          {inst.paid_at && (
                            <span className="text-green-400">
                              Paid: {formatDateTime(inst.paid_at)}
                            </span>
                          )}
                          {inst.failure_reason && (
                            <span className="text-red-400">{inst.failure_reason}</span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
