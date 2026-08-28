import type { SentEmail } from "../../types/analytics"

interface EmailHistoryProps {
  emails: SentEmail[]
}

const STATUS_STYLES: Record<string, { bg: string; text: string; icon: string }> = {
  pending: { bg: "bg-slate-600/30", text: "text-slate-400", icon: "⏳" },
  sent: { bg: "bg-blue-500/20", text: "text-blue-400", icon: "📤" },
  delivered: { bg: "bg-green-500/20", text: "text-green-400", icon: "✅" },
  bounced: { bg: "bg-red-500/20", text: "text-red-400", icon: "❌" },
  failed: { bg: "bg-red-500/20", text: "text-red-400", icon: "❌" },
}

const TYPE_LABELS: Record<string, string> = {
  failed_payment: "⚠️ Payment Failed",
  payment_retry: "🔄 Payment Retry",
  invoice: "📄 Invoice",
  payment_plan_confirmation: "📋 Plan Confirmation",
  promise_to_pay_reminder: "⏰ Promise Reminder",
  payment_success: "✅ Payment Success",
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

export default function EmailHistory({ emails }: EmailHistoryProps) {
  if (emails.length === 0) {
    return (
      <div className="rounded-lg bg-slate-800/50 p-4 text-center text-sm text-slate-500">
        No emails sent
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {emails.map((email) => {
        const style =
          STATUS_STYLES[email.delivery_status] || STATUS_STYLES.pending
        const typeLabel =
          TYPE_LABELS[email.email_type] || email.email_type

        return (
          <div
            key={email.id}
            className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4"
          >
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">{typeLabel}</span>
                <span
                  className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${style.bg} ${style.text}`}
                >
                  {style.icon} {email.delivery_status}
                </span>
              </div>
              <span className="text-xs text-slate-500">
                {formatDateTime(email.sent_at || email.created_at)}
              </span>
            </div>

            <div className="mb-1 text-sm font-medium text-slate-200">
              {email.subject}
            </div>

            <div className="mb-2 text-xs text-slate-500">
              To: {email.recipient_email}
            </div>

            <div className="rounded bg-slate-900/50 px-3 py-2 text-xs text-slate-400 whitespace-pre-wrap">
              {email.body}
            </div>

            {email.error_message && (
              <div className="mt-2 rounded bg-red-900/20 px-3 py-2 text-xs text-red-400">
                Error: {email.error_message}
              </div>
            )}

            {email.provider_message_id && (
              <div className="mt-1 text-[10px] text-slate-600">
                Provider ID: {email.provider_message_id}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
