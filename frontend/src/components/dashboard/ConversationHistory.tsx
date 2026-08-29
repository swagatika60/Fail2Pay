import type {
  Conversation,
  ConversationMessage,
} from "../../types/analytics"

interface ConversationHistoryProps {
  conversations: Conversation[]
  onQuickReply?: (payloadId: string) => void
  typing?: boolean
}

interface AgentPayload {
  text?: unknown
  quick_replies?: { id?: unknown; label?: unknown }[]
  payment_card?: {
    amount?: unknown
    amount_formatted?: unknown
    invoice_id?: unknown
    gateway?: unknown
    url?: unknown
    label?: unknown
  }
  language_options?: { code?: unknown; label?: unknown }[]
}

function asStr(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v)
}

function getPayload(msg: ConversationMessage): AgentPayload | null {
  const extra = msg.extra_data
  if (!extra || typeof extra !== "object") return null
  const payload = (extra as Record<string, unknown>).agent_payload
  if (!payload || typeof payload !== "object") return null
  return payload as AgentPayload
}

function formatTime(dateStr: string | null): string {
  if (!dateStr) return ""
  return new Date(dateStr).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function ConversationHistory({
  conversations,
  onQuickReply,
  typing = false,
}: ConversationHistoryProps) {
  // Flatten all conversations into one chronological WhatsApp thread.
  const allMessages = conversations.flatMap((conv) =>
    conv.messages.map((m) => ({ ...m, _convId: conv.id })),
  )
  allMessages.sort(
    (a, b) =>
      new Date(a.created_at || 0).getTime() -
      new Date(b.created_at || 0).getTime(),
  )

  if (allMessages.length === 0 && !typing) {
    return (
      <div className="rounded-lg bg-slate-800/50 p-4 text-center text-sm text-slate-500">
        No conversations yet
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-700/50 bg-slate-900">
      {/* WhatsApp Business thread header */}
      <div className="flex items-center gap-3 border-b border-slate-800 bg-slate-800/40 px-4 py-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-600 text-sm font-bold text-white">
          F2P
        </div>
        <div>
          <div className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
            Fail2Pay Support
            <svg
              viewBox="0 0 24 24"
              className="h-4 w-4 fill-emerald-400"
              aria-label="Verified"
            >
              <path d="M12 2l2.4 2.2 3.2-.4 1 3.1 2.8 1.6-1.2 3 1.2 3-2.8 1.6-1 3.1-3.2-.4L12 22l-2.4-2.2-3.2.4-1-3.1-2.8-1.6 1.2-3-1.2-3 2.8-1.6 1-3.1 3.2.4L12 2z" />
              <path
                className="fill-white"
                d="M10.6 15.2l-2.4-2.4 1.1-1.1 1.3 1.3 3.7-3.7 1.1 1.1-4.8 4.8z"
              />
            </svg>
          </div>
          <div className="text-xs text-emerald-400">
            ● Business Account — usually replies instantly
          </div>
        </div>
      </div>

      <div className="space-y-2 p-4">
        {allMessages.map((msg) => (
          <MessageBubble
            key={msg.id + msg._convId}
            msg={msg}
            onQuickReply={onQuickReply}
          />
        ))}

        {typing && <TypingIndicator />}
      </div>
    </div>
  )
}

function MessageBubble({
  msg,
  onQuickReply,
}: {
  msg: ConversationMessage & { _convId: string }
  onQuickReply?: (payloadId: string) => void
}) {
  const isInbound = msg.direction === "inbound"
  const payload = getPayload(msg)
  const delivery = msg.extra_data
    ? asStr((msg.extra_data as Record<string, unknown>).delivery_status)
    : ""
  const lang = msg.extra_data
    ? asStr((msg.extra_data as Record<string, unknown>).language)
    : ""

  return (
    <div
      className={`flex ${isInbound ? "justify-start" : "justify-end"}`}
    >
      <div
        className={`max-w-[85%] ${
          isInbound
            ? "bg-slate-700 text-slate-200"
            : "bg-[#075E54] text-white"
        }`}
        style={{ borderRadius: 12 }}
      >
        {/* Agent / Customer badge */}
        <div className="mb-1 flex items-center gap-1 px-3 pt-2">
          {!isInbound && (
            <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
              Agent
              <svg viewBox="0 0 24 24" className="h-3 w-3 fill-emerald-300">
                <path d="M12 2l2.4 2.2 3.2-.4 1 3.1 2.8 1.6-1.2 3 1.2 3-2.8 1.6-1 3.1-3.2-.4L12 22l-2.4-2.2-3.2.4-1-3.1-2.8-1.6 1.2-3-1.2-3 2.8-1.6 1-3.1 3.2.4L12 2z" />
                <path
                  className="fill-[#075E54]"
                  d="M10.6 15.2l-2.4-2.4 1.1-1.1 1.3 1.3 3.7-3.7 1.1 1.1-4.8 4.8z"
                />
              </svg>
            </span>
          )}
          {isInbound && (
            <span className="rounded-full bg-slate-600/60 px-1.5 py-0.5 text-[10px] font-semibold text-slate-300">
              Customer
            </span>
          )}
          <span className="ml-auto text-[10px] opacity-50">
            {formatTime(msg.created_at)}
          </span>
        </div>

        <div className="whitespace-pre-wrap px-3 pb-1 text-sm leading-relaxed">
          {msg.content}
        </div>

        {/* Rich payment link card */}
        {payload?.payment_card && (
          <PaymentCard
            card={payload.payment_card}
            accent={isInbound ? "bg-slate-600" : "bg-white/10"}
            text={isInbound ? "text-slate-200" : "text-white"}
          />
        )}

        {/* Language selection chips */}
        {payload?.language_options && payload.language_options.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-3 pb-2 pt-1">
            {payload.language_options.map((opt) => (
              <button
                key={asStr(opt.code)}
                onClick={() => onQuickReply?.(`lang:${asStr(opt.code)}`)}
                className={`rounded-full border px-2.5 py-1 text-xs ${
                  isInbound
                    ? "border-slate-500 text-slate-200 hover:bg-slate-600"
                    : "border-white/30 text-white hover:bg-white/10"
                }`}
              >
                {asStr(opt.label)}
              </button>
            ))}
          </div>
        )}

        {/* Quick reply buttons */}
        {payload?.quick_replies && payload.quick_replies.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-3 pb-2">
            {payload.quick_replies.map((qr) => (
              <button
                key={asStr(qr.id)}
                onClick={() => onQuickReply?.(asStr(qr.id))}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                  isInbound
                    ? "border-slate-500 text-slate-200 hover:bg-slate-600"
                    : "border-white/40 text-white hover:bg-white/15"
                }`}
              >
                {asStr(qr.label)}
              </button>
            ))}
          </div>
        )}

        {(delivery || lang) && (
          <div className="flex items-center justify-end gap-1 px-3 pb-1.5 text-[10px] opacity-50">
            {lang && <span>{lang}</span>}
            {delivery && <span>{delivery}</span>}
            <span className="inline-flex">
              {delivery === "read" || delivery === "delivered" ? "✓✓" : "✓"}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

function PaymentCard({
  card,
  accent,
  text,
}: {
  card: NonNullable<AgentPayload["payment_card"]>
  accent: string
  text: string
}) {
  const url = asStr(card.url)
  return (
    <div className={`mx-3 my-1.5 rounded-lg border ${accent} p-3`}>
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 flex-col items-center justify-center rounded-md bg-indigo-600 text-white">
          <span className="text-[8px] font-bold leading-none">rzp</span>
          <span className="text-[6px] opacity-80">Pay</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className={`text-[10px] opacity-70`}>Payment Request</div>
          <div className={`font-semibold ${text}`}>
            {asStr(card.label) ||
              `${asStr(card.amount_formatted)} · ${asStr(card.invoice_id)}`}
          </div>
          <div className={`text-[10px] opacity-70`}>
            {asStr(card.invoice_id)} · {asStr(card.gateway)}
          </div>
        </div>
      </div>
      {url && (
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className={`mt-2 block rounded-md py-1.5 text-center text-xs font-semibold ${
            accent.includes("white") ? "bg-emerald-500 text-white" : "bg-emerald-600 text-white"
          }`}
        >
          Pay Now {asStr(card.amount_formatted)}
        </a>
      )}
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 rounded-xl bg-slate-700 px-3 py-2">
        <span className="flex gap-1">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-300"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </span>
        <span className="ml-1 text-[10px] text-slate-400">Agent typing…</span>
      </div>
    </div>
  )
}
