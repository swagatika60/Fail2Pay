import { useEffect, useMemo, useState } from "react"
import type { ComponentType } from "react"
import { CheckCircle2, Clock3, MailPlus, Send, XCircle } from "lucide-react"
import type { SentEmail } from "../../types/analytics"

interface EmailHistoryProps {
  emails: SentEmail[]
  onGenerateEmail?: () => void
  onPayNow?: (caseId: string) => void
}

const STATUS_STYLES: Record<
  string,
  { bg: string; text: string; icon: ComponentType<{ className?: string }> }
> = {
  pending: { bg: "bg-slate-600/30", text: "text-slate-400", icon: Clock3 },
  sent: { bg: "bg-blue-500/20", text: "text-blue-400", icon: Send },
  delivered: { bg: "bg-green-500/20", text: "text-green-400", icon: CheckCircle2 },
  bounced: { bg: "bg-red-500/20", text: "text-red-400", icon: XCircle },
  failed: { bg: "bg-red-500/20", text: "text-red-400", icon: XCircle },
}

const TYPE_LABELS: Record<string, string> = {
  failed_payment: "Payment Failed",
  payment_retry: "Payment Retry",
  invoice: "Invoice",
  payment_plan_confirmation: "Plan Confirmation",
  promise_to_pay_reminder: "Promise Reminder",
  payment_success: "Payment Success",
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

function isHtml(body: string): boolean {
  const t = body.trim().toLowerCase()
  return t.startsWith("<!doctype") || t.startsWith("<html") || t.includes("<table")
}

export default function EmailHistory({
  emails,
  onGenerateEmail,
  onPayNow,
}: EmailHistoryProps) {
  if (emails.length === 0) {
    return (
      <div className="space-y-3">
        <div className="rounded-lg bg-slate-800/50 p-4 text-center text-sm text-slate-500">
          No emails sent yet
        </div>
        {onGenerateEmail && (
          <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-4 text-center">
            <p className="mb-2 text-sm text-blue-300">
              Generate the matching transactional email thread for this case.
            </p>
            <button
              onClick={onGenerateEmail}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
            >
              <MailPlus className="h-4 w-4" />
              Generate matching email
            </button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {emails.map((email) => {
        const style =
          STATUS_STYLES[email.delivery_status] || STATUS_STYLES.pending
        const typeLabel = TYPE_LABELS[email.email_type] || email.email_type
        const html = isHtml(email.body)

        return (
          <EmailCard
            key={email.id}
            email={email}
            html={html}
            style={style}
            typeLabel={typeLabel}
            onPayNow={onPayNow}
          />
        )
      })}
    </div>
  )
}

function EmailCard({
  email,
  html,
  style,
  typeLabel,
  onPayNow,
}: {
  email: SentEmail
  html: boolean
  style: { bg: string; text: string; icon: ComponentType<{ className?: string }> }
  typeLabel: string
  onPayNow?: (caseId: string) => void
}) {
  const [showHtml, setShowHtml] = useState(false)

  const previewHtml = useMemo(
    () => (html ? buildPreviewHtml(email.body, email.id) : null),
    [html, email.body, email.id],
  )

  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">{typeLabel}</span>
          <span
            className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${style.bg} ${style.text}`}
          >
            <style.icon className="h-3.5 w-3.5" /> {email.delivery_status}
          </span>
        </div>
        <span className="text-xs text-slate-500">
          {formatDateTime(email.sent_at || email.created_at)}
        </span>
      </div>

      <div className="mb-1 text-sm font-medium text-slate-200">{email.subject}</div>

      <div className="mb-2 text-xs text-slate-500">To: {email.recipient_email}</div>

      {html ? (
        <div className="overflow-hidden rounded-lg border border-slate-700/50">
          {showHtml && previewHtml ? (
            <Previews iframeKey={email.id} srcDoc={previewHtml} onPayNow={onPayNow} />
          ) : (
            <div className="bg-slate-900/50 p-3 text-xs text-slate-300">
              This is an HTML transactional email (invoice + Pay Now CTA + DND
              footer).
            </div>
          )}
          <div className="flex items-center gap-2 border-t border-slate-700/50 bg-slate-900/60 px-3 py-2">
            <button
              onClick={() => setShowHtml((v) => !v)}
              className="rounded bg-slate-700 px-3 py-1 text-xs text-slate-200 hover:bg-slate-600"
            >
              {showHtml ? "Hide preview" : "Preview HTML email"}
            </button>
            {showHtml && (
              <span className="text-[10px] text-slate-500">
                Rendered as an email client would show it.
              </span>
            )}
          </div>
        </div>
      ) : (
        <div className="rounded bg-slate-900/50 px-3 py-2 text-xs text-slate-400 whitespace-pre-wrap">
          {email.body}
        </div>
      )}

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
}

/**
 * Neutralize external navigation inside the email preview and turn "Pay Now"
 * into a local action.
 *
 * The raw email HTML is rendered via `srcDoc` (never `src`), so the preview
 * itself never fetches an external domain. But clicking a link inside the
 * sandboxed frame would still attempt to navigate to the (possibly unreachable)
 * payment host. We inject a small script that prevents default on every anchor
 * and posts a `fail2pay:paynow` message to the parent for payment links, so the
 * click is handled locally instead.
 */
function buildPreviewHtml(rawHtml: string, emailId: string): string {
  const bridge = `
  <script>
    (function () {
      function handle(e) {
        var a = e.target && e.target.closest ? e.target.closest('a') : null;
        if (!a) return;
        var href = a.getAttribute('href') || '';
        e.preventDefault();
        if (href.indexOf('/inv/') !== -1) {
          var m = href.match(/\\/inv\\/([0-9a-fA-F\\-]+)/);
          try {
            window.parent.postMessage(
              { type: 'fail2pay:paynow', emailId: ${JSON.stringify(emailId)}, caseId: m ? m[1] : null },
              '*'
            );
          } catch (_) {}
        }
      }
      document.addEventListener('click', handle, true);
    })();
  </script>`

  if (rawHtml.toLowerCase().includes("</body>")) {
    return rawHtml.replace("</body>", `${bridge}</body>`)
  }
  return rawHtml + bridge
}

/**
 * Sandboxed iframe that renders the email HTML and bridges "Pay Now" clicks to
 * the parent. `allow-scripts` lets the injected interceptor run, while omitting
 * `allow-same-origin` (opaque origin) and all `allow-top-navigation` flags keeps
 * the preview unable to escape or navigate the parent window.
 */
function Previews({
  srcDoc,
  onPayNow,
  iframeKey,
}: {
  srcDoc: string
  onPayNow?: (caseId: string) => void
  iframeKey: string
}) {
  const [caseId, setCaseId] = useState<string>("")

  useEffect(() => {
    if (!onPayNow) return

    const handler = (e: MessageEvent) => {
      if (
        e.data &&
        e.data.type === "fail2pay:paynow" &&
        e.data.emailId === iframeKey &&
        e.data.caseId
      ) {
        setCaseId(e.data.caseId)
        onPayNow(e.data.caseId)
      }
    }
    window.addEventListener("message", handler)
    return () => window.removeEventListener("message", handler)
  }, [onPayNow, iframeKey])

  return (
    <div className="relative">
      <iframe
        title={`email-preview-${iframeKey}`}
        srcDoc={srcDoc}
        sandbox="allow-scripts"
        className="h-[420px] w-full bg-white"
      />
      {caseId && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-center gap-1.5 bg-emerald-600/90 px-3 py-2 text-xs font-medium text-white">
          <CheckCircle2 className="h-3.5 w-3.5" />
          Payment flow triggered for case #{caseId.slice(0, 8)}
        </div>
      )}
    </div>
  )
}
