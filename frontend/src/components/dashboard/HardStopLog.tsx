import { Ban, CheckCircle2 } from "lucide-react"
import type { HardStop } from "../../types/analytics"

interface HardStopLogProps {
  hardStops: HardStop[]
}

const CONDITION_LABELS: Record<string, { label: string; color: string }> = {
  hard_stop_payment_succeeded: { label: "Payment Succeeded", color: "text-green-400" },
  hard_stop_customer_stopped: { label: "Customer Stopped", color: "text-red-400" },
  hard_stop_customer_opted_out: { label: "Customer Opted Out", color: "text-red-400" },
  hard_stop_case_closed: { label: "Case Closed", color: "text-gray-400" },
  hard_stop_max_attempts_reached: { label: "Max Attempts", color: "text-amber-400" },
  hard_stop_deadline_expired: { label: "Deadline Expired", color: "text-amber-400" },
  hard_stop_plan_cancelled: { label: "Plan Cancelled", color: "text-red-400" },
  hard_stop_invoice_paid: { label: "Invoice Paid", color: "text-green-400" },
  hard_stop_merchant_disabled: { label: "Merchant Disabled", color: "text-gray-400" },
}

function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return "—"
  return new Date(dateStr).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function HardStopLog({ hardStops }: HardStopLogProps) {
  if (hardStops.length === 0) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-lg bg-slate-800/50 p-4 text-sm text-slate-500">
        <CheckCircle2 className="h-4 w-4 text-green-400" />
        No hard stop events — all clear
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {hardStops.map((hs) => {
        const info = CONDITION_LABELS[hs.action] || {
          label: hs.action,
          color: "text-slate-400",
        }

        return (
          <div
            key={hs.id}
            className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4"
          >
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Ban className="h-4 w-4 shrink-0 text-red-400" />
                <span className={`text-sm font-medium ${info.color}`}>
                  {info.label}
                </span>
              </div>
              <span className="text-xs text-slate-500">
                {formatDateTime(hs.created_at)}
              </span>
            </div>

            {hs.new_value && (
              <div className="rounded bg-slate-900/50 px-3 py-2 text-xs text-slate-400">
                {Boolean(hs.new_value.stop_condition) && (
                  <div>
                    <span className="text-slate-500">Condition: </span>
                    {String(hs.new_value.stop_condition)}
                  </div>
                )}
                {Boolean(hs.new_value.reason) && (
                  <div>
                    <span className="text-slate-500">Reason: </span>
                    {String(hs.new_value.reason)}
                  </div>
                )}
                {Boolean(hs.new_value.action_type) && (
                  <div>
                    <span className="text-slate-500">Action: </span>
                    {String(hs.new_value.action_type)}
                  </div>
                )}
                {hs.new_value.actions_cancelled !== undefined && (
                  <div>
                    <span className="text-slate-500">Cancelled: </span>
                    {String(hs.new_value.actions_cancelled)} actions
                  </div>
                )}
                {Boolean(hs.new_value.case_status) && (
                  <div>
                    <span className="text-slate-500">Status: </span>
                    {String(hs.new_value.case_status)}
                  </div>
                )}
                {Boolean(hs.new_value.intent) && (
                  <div>
                    <span className="text-slate-500">Intent: </span>
                    {String(hs.new_value.intent)}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
