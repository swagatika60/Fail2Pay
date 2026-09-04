import { PhoneIncoming, PhoneOutgoing, PhoneCall } from "lucide-react"
import type { VoiceCall } from "../../types/analytics"

interface VoiceCallsPanelProps {
  calls: VoiceCall[]
  canInitiate: boolean
  busy: boolean
  onInitiate?: () => void
  message?: string | null
}

const INTENT_LABELS: Record<string, string> = {
  PAY_NOW: "Pay now",
  SPLIT_EMI: "Split / EMI",
  PAY_LATER: "Pay later",
  PROMISE_TO_PAY: "Promise to pay",
  PAYMENT_PLAN_REQUEST: "Payment plan",
  STOP_REQUEST: "Opt-out",
  SUPPORT: "Human support",
  UNCLEAR: "Unclear",
  TIMEOUT: "Timeout",
}

const DIRECTION_META: Record<string, { label: string; cls: string }> = {
  inbound: {
    label: "Inbound",
    cls: "bg-sky-500/20 text-sky-400",
  },
  outbound: {
    label: "Outbound",
    cls: "bg-violet-500/20 text-violet-400",
  },
}

const STATUS_LABELS: Record<string, string> = {
  initiated: "Initiated",
  completed: "Completed",
  blocked: "Blocked",
  stopped_case_ack: "Opt-out ack",
  "in-progress": "In progress",
}

function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return "—"
  return new Date(dateStr).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function VoiceCallsPanel({
  calls,
  canInitiate,
  busy,
  onInitiate,
  message,
}: VoiceCallsPanelProps) {
  const note = (
    <p className="mt-3 text-[10px] leading-relaxed text-slate-600">
      Production voice calls require Twilio credentials (
      <code className="font-mono">TWILIO_ACCOUNT_SID</code>,{" "}
      <code className="font-mono">TWILIO_AUTH_TOKEN</code>,{" "}
      <code className="font-mono">TWILIO_PHONE_NUMBER</code>). Until configured,
      calls are logged here honestly — no real calls are placed.
    </p>
  )

  if (calls.length === 0) {
    return (
      <div className="space-y-3">
        {message && <CallMessageBanner text={message} />}
        <div className="rounded-lg bg-slate-800/50 p-4 text-center">
          <p className="text-sm text-slate-500">No voice calls recorded yet</p>
          {canInitiate && (
            <p className="mt-1 text-xs text-slate-600">
              Outbound recovery calls and inbound IVR interactions will appear here.
            </p>
          )}
        </div>
        {canInitiate && onInitiate && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-center">
            <p className="mb-2 text-sm text-emerald-300">
              Initiate an outbound recovery call for this case.
            </p>
            <button
              type="button"
              onClick={onInitiate}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <PhoneCall className="h-3.5 w-3.5" aria-hidden="true" />
              {busy ? "Initiating…" : "Initiate outbound call"}
            </button>
          </div>
        )}
        {note}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {message && <CallMessageBanner text={message} />}
      {calls.map((call) => {
        const direction = DIRECTION_META[call.direction] || {
          label: call.direction || "Call",
          cls: "bg-slate-600/30 text-slate-400",
        }
        const DirectionIcon =
          call.direction === "inbound" ? PhoneIncoming : PhoneOutgoing
        const intentLabel = INTENT_LABELS[call.intent] || call.intent || "—"
        const statusLabel = STATUS_LABELS[call.status] || call.status || "—"
        const transcript = call.transcription?.trim()

        return (
          <div
            key={call.id}
            className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <DirectionIcon
                  className="h-3.5 w-3.5 shrink-0 text-slate-500"
                  aria-hidden="true"
                />
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${direction.cls}`}
                >
                  {direction.label}
                </span>
                <span className="truncate text-xs font-medium text-slate-200">
                  {intentLabel}
                </span>
                <span className="shrink-0 rounded-full bg-slate-600/30 px-2 py-0.5 text-[10px] text-slate-400">
                  {statusLabel}
                </span>
              </div>
              <span className="shrink-0 text-xs text-slate-500">
                {formatDateTime(call.created_at)}
              </span>
            </div>

            {transcript ? (
              <p className="rounded bg-slate-900/50 px-3 py-2 text-xs text-slate-300">
                “{transcript}”
              </p>
            ) : call.dtmf_input ? (
              <p className="rounded bg-slate-900/50 px-3 py-2 text-xs text-slate-400">
                DTMF input: {call.dtmf_input}
              </p>
            ) : null}

            <div className="mt-1 flex items-center justify-between text-[10px] text-slate-600">
              <span>
                {call.language ? `Language: ${call.language}` : ""}
                {call.duration_seconds
                  ? ` · Duration: ${call.duration_seconds}s`
                  : ""}
              </span>
              {call.call_sid && (
                <span className="font-mono">SID: {call.call_sid}</span>
              )}
            </div>
          </div>
        )
      })}
      {note}
    </div>
  )
}

function CallMessageBanner({ text }: { text: string }) {
  const isError =
    text.toLowerCase().includes("blocked") ||
    text.toLowerCase().includes("failed") ||
    text.toLowerCase().includes("error")
  return (
    <div
      className={`rounded-lg px-3 py-2 text-xs ${
        isError
          ? "bg-red-900/20 text-red-400"
          : "bg-emerald-500/10 text-emerald-300"
      }`}
    >
      {text}
    </div>
  )
}