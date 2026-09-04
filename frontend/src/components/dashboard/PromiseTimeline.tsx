import type { ComponentType } from "react"
import {
  Ban,
  CheckCircle2,
  Clock3,
  Hourglass,
  XCircle,
} from "lucide-react"
import type { PaymentPromise } from "../../types/analytics"
import { formatCurrency } from "./MetricCard"

interface PromiseTimelineProps {
  promises: PaymentPromise[]
}

const STATUS_STYLES: Record<
  string,
  { bg: string; text: string; icon: ComponentType<{ className?: string }> }
> = {
  ACTIVE: { bg: "bg-blue-500/20", text: "text-blue-400", icon: Clock3 },
  FULFILLED: { bg: "bg-green-500/20", text: "text-green-400", icon: CheckCircle2 },
  MISSED: { bg: "bg-amber-500/20", text: "text-amber-400", icon: Clock3 },
  BROKEN: { bg: "bg-red-500/20", text: "text-red-400", icon: XCircle },
  CANCELLED: { bg: "bg-gray-500/20", text: "text-gray-400", icon: Ban },
  EXPIRED: { bg: "bg-gray-500/20", text: "text-gray-400", icon: Hourglass },
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

export default function PromiseTimeline({ promises }: PromiseTimelineProps) {
  if (promises.length === 0) {
    return (
      <div className="rounded-lg bg-slate-800/50 p-4 text-center text-sm text-slate-500">
        No promises recorded
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {promises.map((p) => {
        const style = STATUS_STYLES[p.status] || STATUS_STYLES.ACTIVE
        return (
          <div
            key={p.id}
            className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4"
          >
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${style.bg} ${style.text}`}
                >
                  <style.icon className="h-3.5 w-3.5" /> {p.status}
                </span>
                <span className="text-sm font-semibold text-slate-200">
                  {formatCurrency(p.amount_promised)}
                </span>
              </div>
              <span className="text-xs text-slate-500">
                {formatDateTime(p.created_at)}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs text-slate-400">
              <div>
                <span className="text-slate-500">Promised: </span>
                {formatDateTime(p.promised_date)}
              </div>
              <div>
                <span className="text-slate-500">Expires: </span>
                {formatDateTime(p.expires_at)}
              </div>
              {p.fulfilled_at && (
                <div>
                  <span className="text-green-500">Fulfilled: </span>
                  {formatDateTime(p.fulfilled_at)}
                </div>
              )}
              {p.missed_at && (
                <div>
                  <span className="text-amber-500">Missed: </span>
                  {formatDateTime(p.missed_at)}
                </div>
              )}
              {p.cancelled_at && (
                <div>
                  <span className="text-gray-500">Cancelled: </span>
                  {formatDateTime(p.cancelled_at)}
                </div>
              )}
              {p.cancellation_reason && (
                <div className="col-span-2">
                  <span className="text-slate-500">Reason: </span>
                  {p.cancellation_reason}
                </div>
              )}
            </div>

            {p.customer_message && (
              <div className="mt-2 rounded bg-slate-900/50 px-3 py-2 text-xs text-slate-300 italic">
                "{p.customer_message}"
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
