import { useEffect, useRef, useState, useCallback } from "react"
import type { Conversation, ConversationMessage } from "../../types/analytics"
import type { LiveRealtimeMessage, LiveQuickReply } from "../../services/realtime"
import {
  ArrowLeft,
  Phone,
  Video,
  MoreVertical,
  Paperclip,
  Camera,
  Mic,
  Send,
  Smile,
  Globe,
  Download,
  Lock,
  Zap,
  ArrowRight,
  Calendar,
} from "lucide-react"

/* ── Types ───────────────────────────────────────────────────── */

interface ConversationHistoryProps {
  conversations: Conversation[]
  liveMessages?: LiveRealtimeMessage[]
  liveQuickReplies?: LiveQuickReply[] | null
  liveStatus?: "connecting" | "open" | "closed" | "error"
  isTyping?: boolean
  customerName?: string | null
  customerPhone?: string | null
  hideHeader?: boolean
  onQuickReply?: (trigger: string, options?: { message?: string; promiseDate?: string }) => void
  onSendMessage?: (text: string) => void
  quickRepliesDisabled?: boolean
  attemptCount?: number
  maxAttempts?: number
  currentLanguage?: string
}

type ThreadMessage = ConversationMessage & {
  _convId: string
  _live?: boolean
}

/* ── Helpers ──────────────────────────────────────────────────── */

function asStr(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v)
}

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {}
}

function extId(msg: ThreadMessage): string {
  return asStr(asRecord(msg.extra_data).external_message_id)
}

function msgId(msg: ThreadMessage): string {
  return asStr(msg.id)
}

function normalizeTs(s: string | null): string {
  if (!s) return ""
  try {
    const d = new Date(s)
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}-${d.getHours()}-${d.getMinutes()}-${d.getSeconds()}`
  } catch {
    return s
  }
}

function formatWhatsAppTime(dateStr: string | null): string {
  if (!dateStr) return ""
  const d = new Date(dateStr)
  return d.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  }).toLowerCase()
}

function getDateLabel(dateStr: string | null): string {
  if (!dateStr) return ""
  const d = new Date(dateStr)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const msgDate = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diffMs = today.getTime() - msgDate.getTime()
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffDays === 0) return "TODAY"
  if (diffDays === 1) return "YESTERDAY"
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).toUpperCase()
}

function getDateKey(dateStr: string | null): string {
  if (!dateStr) return ""
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

function dedupe(messages: ThreadMessage[]): ThreadMessage[] {
  const seen = new Set<string>()
  const out: ThreadMessage[] = []
  for (const msg of messages) {
    const ext = extId(msg)
    if (ext && seen.has(`ext:${ext}`)) continue
    if (ext) { seen.add(`ext:${ext}`); out.push(msg); continue }

    const dbId = msgId(msg)
    if (dbId && seen.has(`db:${dbId}`)) continue
    if (dbId) { seen.add(`db:${dbId}`); out.push(msg); continue }

    const composite = [
      msg._convId,
      msg.direction,
      msg.content,
      normalizeTs(msg.created_at),
    ].join("\u0000")
    if (seen.has(composite)) continue
    seen.add(composite)
    out.push(msg)
  }
  return out
}

function getInitials(name: string | null | undefined): string {
  if (!name) return "SP"
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2)
}

/* ── Agent Payload Types ─────────────────────────────────────── */

interface AgentPayload {
  payment_card?: PaymentCard | null
  split_options?: SplitOption[]
  quick_replies?: Array<{ id: string; label: string }>
  invoice_card?: InvoiceData | null
  email_dispatch?: EmailDispatchData | null
  intent?: string
  recovered?: boolean
}

interface PaymentCard {
  url?: string
  amount?: number
  amount_formatted?: string
  label?: string
  gateway?: string
  invoice_id?: string
  installment?: boolean
  installment_no?: number
  total_installments?: number
  remaining_amount?: number
}

interface SplitOption {
  id?: string
  count?: number
  label?: string
  amounts_formatted?: string[]
}

interface InvoiceData {
  invoice_id?: string
  invoice_number?: string
  customer_name?: string
  amount?: number
  amount_formatted?: string
  due_date?: string
  status?: string
  secure_url?: string
  pdf_url?: string
}

interface EmailDispatchData {
  recipient_email?: string
  subject?: string
  status?: string
  delivery_status?: string
  sent_at?: string
  email_type?: string
}

function agentPayload(msg: ThreadMessage): AgentPayload | null {
  const payload = asRecord(asRecord(msg.extra_data).agent_payload)
  if (!Object.keys(payload).length) return null
  return payload as unknown as AgentPayload
}

/* ── WhatsApp Document Media Card ────────────────────────────── */

function WhatsAppDocumentCard({ invoice }: { invoice: InvoiceData }) {
  const invoiceNumber = invoice.invoice_number || invoice.invoice_id || "INV"
  const amount = invoice.amount_formatted || (invoice.amount != null ? `₹${(invoice.amount / 100).toLocaleString("en-IN")}` : "")
  const displayNumber = invoiceNumber.length > 20 ? invoiceNumber.slice(0, 20) : invoiceNumber

  return (
    <div className="mt-1 overflow-hidden rounded-lg border border-white/10 bg-[#1a2730]">
      {/* Left-aligned: PDF badge + file details + right-aligned action icon */}
      <div className="flex items-center gap-3 px-3 py-2.5">
        {/* Red PDF icon badge */}
        <div className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-lg bg-[#e53e3e]">
          <FileTextIcon />
        </div>
        {/* File name + subtitle */}
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium text-white leading-tight">
            Invoice_{displayNumber}.pdf
          </p>
          <p className="text-[11px] text-[#8696a0] mt-0.5">
            PDF • 145 KB
          </p>
        </div>
        {/* Right-side download/preview action icon */}
        {(invoice.pdf_url || invoice.secure_url) && (
          <a
            href={invoice.pdf_url || invoice.secure_url || "#"}
            target="_blank"
            rel="noopener noreferrer"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#2a3942] text-[#00a884] transition-colors hover:bg-[#364150]"
            title="Download / Preview"
          >
            <Download className="h-4 w-4" />
          </a>
        )}
      </div>
      {/* Caption below the document card */}
      {amount && (
        <div className="border-t border-white/5 px-3 py-2">
          <p className="text-[12px] text-[#d1d7db] leading-snug">
            Here is your invoice for #{invoiceNumber}.
          </p>
        </div>
      )}
    </div>
  )
}

/* Small inline PDF icon for the document card */
function FileTextIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  )
}

/* ── WhatsApp Payment Card ───────────────────────────────────── */

function WhatsAppPaymentCard({ card }: { card: PaymentCard }) {
  const amount = card.amount_formatted || (card.amount != null ? `₹${(card.amount / 100).toLocaleString("en-IN")}` : "")
  const total = card.remaining_amount != null ? `₹${Math.round(card.remaining_amount / 100).toLocaleString("en-IN")}` : null
  const emiPills = card.installment && card.total_installments && card.installment_no
    ? Array.from({ length: card.total_installments }, (_, i) => i + 1).map((n) => ({
        n,
        active: n === card.installment_no,
      }))
    : null

  return (
    <div className="mt-1 overflow-hidden rounded-lg border border-white/10 bg-[#1a2730]">
      <div className="flex items-center gap-2 border-b border-white/5 px-3 py-2">
        <Zap className="h-3.5 w-3.5 text-[#00a884]" />
        <span className="text-[11px] font-semibold text-[#00a884]">Secure Checkout</span>
        <span className="ml-auto text-[10px] font-mono text-[#8696a0]">
          via {card.gateway || "Razorpay"}
        </span>
      </div>
      <div className="px-3 py-2">
        <div className="flex items-baseline justify-between">
          <span className="text-[11px] text-[#8696a0]">Total payable</span>
          <span className="font-mono text-sm font-semibold text-[#00a884]">{amount}</span>
        </div>
        {total && card.installment && (
          <div className="mt-0.5 flex items-baseline justify-between">
            <span className="text-[11px] text-[#8696a0]">Remaining on plan</span>
            <span className="font-mono text-[11px] text-[#8696a0]">{total}</span>
          </div>
        )}
        {emiPills && (
          <div className="mt-2 flex items-center gap-1">
            <span className="mr-1 text-[9px] uppercase tracking-wide text-[#8696a0]">EMI</span>
            {emiPills.map((p) => (
              <span
                key={p.n}
                className={`inline-flex h-5 min-w-5 items-center justify-center rounded-md border px-1 text-[9px] font-semibold ${
                  p.active
                    ? "border-[#00a884]/50 bg-[#00a884]/15 text-[#00a884]"
                    : "border-white/10 bg-[#222d34] text-[#8696a0]"
                }`}
              >
                {p.n}
              </span>
            ))}
            <span className="ml-1.5 text-[10px] text-[#8696a0]">
              Part {card.installment_no} of {card.total_installments}
            </span>
          </div>
        )}
        <div className="mt-2 flex items-center justify-between border-t border-white/5 pt-2">
          <span className="flex items-center gap-1 text-[10px] text-[#8696a0]">
            <Lock className="h-3 w-3" />
            Secure · PCI-DSS
          </span>
          <a
            href={card.url || "#"}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a884] px-3 py-1.5 text-xs font-semibold text-[#111b21] transition-colors hover:bg-[#06cf9c]"
          >
            Pay Now
            <ArrowRight className="h-3.5 w-3.5" />
          </a>
        </div>
      </div>
    </div>
  )
}

/* ── WhatsApp Split Card ─────────────────────────────────────── */

function WhatsAppSplitCard({
  option,
  parts,
  onChoose,
}: {
  option: SplitOption
  parts: string[]
  onChoose?: (partIndex: number, amount: string, splitCount: number) => void
}) {
  return (
    <div className="mt-1">
      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#8696a0]">
        {option.label || `Split into ${option.count || parts.length}`}
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        {parts.map((label, i) => (
          <button
            key={i}
            onClick={() => onChoose?.(i, label, option.count || parts.length)}
            className="cursor-pointer rounded-lg border border-white/10 bg-[#1a2730] px-2 py-1.5 text-center text-[11px] font-medium text-[#d1d7db] transition-all hover:border-[#00a884]/40 hover:bg-[#00a884]/10 hover:text-[#00a884] active:scale-95"
          >
            <span className="block text-[9px] uppercase tracking-wide opacity-60">
              Part {i + 1} of {parts.length}
            </span>
            <span className="mt-0.5 flex items-center justify-center gap-1 font-semibold">
              {label}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

/* ── WhatsApp Email Card ─────────────────────────────────────── */

function WhatsAppEmailCard({ email }: { email: EmailDispatchData }) {
  const status = email.delivery_status || email.status || "sent"
  return (
    <div className="mt-1 overflow-hidden rounded-lg border border-white/10 bg-[#1a2730]">
      <div className="flex items-center gap-2 border-b border-white/5 px-3 py-1.5">
        <span className="text-[11px] font-semibold text-[#53bdeb]">📧 Email Dispatched</span>
        <span className={`ml-auto rounded border px-1.5 py-0.5 text-[9px] font-semibold ${
          status === "delivered" ? "text-[#00a884] border-[#00a884]/30 bg-[#00a884]/10"
            : status === "failed" ? "text-[#ea4335] border-[#ea4335]/30 bg-[#ea4335]/10"
              : "text-[#53bdeb] border-[#53bdeb]/30 bg-[#53bdeb]/10"
        }`}>{status}</span>
      </div>
      <div className="space-y-1 px-3 py-2 text-[11px]">
        {email.recipient_email && (
          <div className="flex items-center gap-1.5 text-[#8696a0]">
            <span className="truncate text-[#d1d7db]">{email.recipient_email}</span>
          </div>
        )}
        {email.subject && (
          <div className="flex items-center gap-1.5 text-[#8696a0]">
            <span className="truncate text-[#d1d7db]">{email.subject}</span>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Checkmark SVGs ──────────────────────────────────────────── */

function SingleTick() {
  return (
    <svg viewBox="0 0 16 11" width="16" height="11" className="inline-block ml-0.5">
      <path
        d="M11.071.653a.457.457 0 0 0-.304-.102.493.493 0 0 0-.381.178l-6.19 7.636-2.011-2.095a.463.463 0 0 0-.659-.003.453.453 0 0 0-.003.66l2.37 2.47a.457.457 0 0 0 .337.137.458.458 0 0 0 .354-.172l6.554-8.083a.452.452 0 0 0-.067-.628z"
        fill="currentColor"
      />
    </svg>
  )
}

function DoubleTick({ read }: { read?: boolean }) {
  return (
    <svg viewBox="0 1 16 11" width="16" height="11" className="inline-block ml-0.5">
      <path
        d="M11.071.653a.457.457 0 0 0-.304-.102.493.493 0 0 0-.381.178l-6.19 7.636-2.011-2.095a.463.463 0 0 0-.659-.003.453.453 0 0 0-.003.66l2.37 2.47a.457.457 0 0 0 .337.137.458.458 0 0 0 .354-.172l6.554-8.083a.452.452 0 0 0-.067-.628z"
        fill={read ? "#53bdeb" : "currentColor"}
      />
      <path
        d="M15.071.653a.457.457 0 0 0-.304-.102.493.493 0 0 0-.381.178l-6.19 7.636-1.2-1.25-.334.413 1.2 1.25a.457.457 0 0 0 .337.137.458.458 0 0 0 .354-.172l6.554-8.083a.452.452 0 0 0-.067-.628z"
        fill={read ? "#53bdeb" : "currentColor"}
        transform="translate(-3.5, 0)"
      />
    </svg>
  )
}

/* ── Message Content Renderer ────────────────────────────────── */

function renderMessageContent(
  content: string,
  payload: AgentPayload | null,
  splitToggle: { option: SplitOption; parts: string[] } | null,
  onChooseSplit?: (partIndex: number, amount: string, splitCount: number) => void,
) {
  const hasCard = Boolean(payload?.payment_card) || Boolean(splitToggle) || Boolean(payload?.invoice_card) || Boolean(payload?.email_dispatch)
  if (!hasCard) return <span className="whitespace-pre-wrap">{content}</span>

  return (
    <>
      <span className="whitespace-pre-wrap">{content}</span>
      {payload?.payment_card && <WhatsAppPaymentCard card={payload.payment_card} />}
      {payload?.invoice_card && <WhatsAppDocumentCard invoice={payload.invoice_card} />}
      {payload?.email_dispatch && <WhatsAppEmailCard email={payload.email_dispatch} />}
      {splitToggle && (
        <WhatsAppSplitCard option={splitToggle.option} parts={splitToggle.parts} onChoose={onChooseSplit} />
      )}
    </>
  )
}

/* ── Quick Reply Chips ───────────────────────────────────────── */

const DEFAULT_QUICK_REPLIES_EN: Array<{ id: string; label: string }> = [
  { id: "pay_now", label: "Pay Now" },
  { id: "installments", label: "Split into 2" },
  { id: "split_4", label: "Split into 4" },
  { id: "promise", label: "I'll pay tomorrow" },
  { id: "pay_later", label: "Pay Later" },
  { id: "language_hi", label: "हिंदी / Hinglish" },
  { id: "language_en", label: "English" },
  { id: "support", label: "Need Support" },
]

const DEFAULT_QUICK_REPLIES_HI: Array<{ id: string; label: string }> = [
  { id: "pay_now", label: "Abhi Pay Karein" },
  { id: "installments", label: "2 Kishton mein baantein" },
  { id: "split_4", label: "4 Kishton mein baantein" },
  { id: "promise", label: "Kal pakka karunga" },
  { id: "pay_later", label: "Baad Mein Pay Karein" },
  { id: "language_hi", label: "हिंदी / Hinglish" },
  { id: "language_en", label: "English" },
  { id: "support", label: "Support Se Baat Karein" },
]

function ContextualQuickReplies({
  messages,
  onReply,
  liveConnected,
  language = "en",
  liveReplies = null,
}: {
  messages: ThreadMessage[]
  onReply?: (trigger: string, options?: { message?: string; promiseDate?: string }) => void
  liveConnected: boolean
  language?: string
  liveReplies?: LiveQuickReply[] | null
}) {
  const latestAgent = [...messages].reverse().find((m) => m.direction !== "inbound")
  const embedded = latestAgent ? agentPayload(latestAgent)?.quick_replies : null
  const isHinglish = language === "hi" || language === "hi-en"
  const defaults = isHinglish ? DEFAULT_QUICK_REPLIES_HI : DEFAULT_QUICK_REPLIES_EN
  const replies = liveReplies?.length ? liveReplies : embedded?.length ? embedded : defaults

  const [customDate, setCustomDate] = useState(() => {
    const d = new Date(Date.now() + 86400_000)
    return d.toISOString().slice(0, 10)
  })
  const tomorrow = new Date(Date.now() + 86400_000).toISOString().slice(0, 10)
  const showDatePicker = replies.some((r) => r.id === "promise_custom")

  const handleReply = (id: string) => {
    if (!onReply) return
    if (id === "promise_custom") {
      onReply(id, { promiseDate: `${customDate}T00:00:00` })
    } else {
      onReply(id)
    }
  }

  return (
    <div className="flex flex-col items-center gap-1.5 pt-2 pb-1">
      <span className="text-[9px] font-semibold uppercase tracking-widest text-[#8696a0]/60">
        {liveReplies?.length || embedded?.length ? "Agent suggested replies" : "Quick reply"}
      </span>
      <div className="flex flex-wrap justify-center gap-1.5">
        {replies.map((r) => (
          <button
            key={r.id}
            onClick={() => handleReply(r.id)}
            className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-[#1a2730] px-3 py-1 text-[11px] font-medium text-[#d1d7db] transition-colors hover:border-[#00a884]/40 hover:bg-[#00a884]/10 hover:text-[#00a884]"
          >
            {r.label}
          </button>
        ))}
      </div>
      {showDatePicker && (
        <label className="inline-flex items-center gap-1.5 rounded-full border border-[#53bdeb]/30 bg-[#53bdeb]/10 px-3 py-1 text-[10px] font-medium text-[#53bdeb]">
          <Calendar className="h-3 w-3" />
          <span>Custom date</span>
          <input
            type="date"
            value={customDate}
            min={tomorrow}
            onChange={(e) => setCustomDate(e.target.value || tomorrow)}
            className="bg-transparent text-[10px] text-[#53bdeb] outline-none [color-scheme:dark]"
          />
        </label>
      )}
      <span className={`text-[9px] ${liveConnected ? "text-[#00a884]/70" : "text-[#8696a0]/40"}`}>
        {liveConnected ? "live · routed to intent engine" : "demo · routed to intent engine"}
      </span>
    </div>
  )
}

/* ── WhatsApp Bottom Input Bar ────────────────────────────────── */

function WhatsAppInputBar({
  onSend,
  onLanguageToggle,
  disabled,
}: {
  onSend: (text: string) => void
  onLanguageToggle?: () => void
  disabled?: boolean
}) {
  const [text, setText] = useState("")
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  const handleSend = useCallback(() => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText("")
    if (inputRef.current) inputRef.current.style.height = "auto"
  }, [text, disabled, onSend])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    const el = e.target
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 80)}px`
  }, [])

  return (
    <div className="bg-[#202c33] p-2.5 flex items-center gap-2">
      {/* Language toggle */}
      <button
        onClick={onLanguageToggle}
        className="mb-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#2a3942] text-[#8696a0] transition-colors hover:bg-[#364150]"
        title="Toggle language"
      >
        <Globe className="h-4 w-4" />
      </button>

      {/* Emoji */}
      <button className="flex items-center justify-center text-[#8696a0] hover:text-[#d1d7db] transition-colors">
        <Smile className="h-6 w-6" />
      </button>

      {/* Paperclip attachment */}
      <button className="flex items-center justify-center text-[#8696a0] hover:text-[#d1d7db] transition-colors">
        <Paperclip className="h-6 w-6 rotate-45" />
      </button>

      {/* Text input */}
      <div className="relative flex-1">
        <textarea
          ref={inputRef}
          value={text}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Type a message"
          disabled={disabled}
          rows={1}
          className="w-full resize-none rounded-lg bg-[#2a3942] px-3 py-2 text-[14px] text-[#d1d7db] placeholder-[#8696a0] transition-colors focus:outline-none disabled:opacity-40"
          style={{ minHeight: "36px", maxHeight: "80px" }}
        />
      </div>

      {/* Camera */}
      <button className="flex items-center justify-center text-[#8696a0] hover:text-[#d1d7db] transition-colors">
        <Camera className="h-6 w-6" />
      </button>

      {/* Mic / Send */}
      {text.trim() ? (
        <button
          onClick={handleSend}
          disabled={disabled}
          className="flex items-center justify-center bg-[#00a884] text-white p-2.5 rounded-full transition-colors hover:bg-[#06cf9c] disabled:opacity-40"
        >
          <Send className="h-5 w-5" />
        </button>
      ) : (
        <button
          disabled
          className="flex items-center justify-center bg-[#00a884] text-white p-2.5 rounded-full opacity-60"
          title="Voice input"
        >
          <Mic className="h-5 w-5" />
        </button>
      )}
    </div>
  )
}

/* ── Attempt Limit Banner ─────────────────────────────────────── */

function AttemptLimitBanner({ attemptCount, maxAttempts }: { attemptCount: number; maxAttempts: number }) {
  if (attemptCount < maxAttempts) return null
  return (
    <div className="mx-auto max-w-[85%] my-1 rounded-lg bg-[#1a2730] border border-[#ea4335]/20 px-3 py-1.5 text-center">
      <span className="text-[11px] text-[#ea4335]">
        ⚠️ Max attempts reached ({attemptCount}/{maxAttempts}) · Monitor mode
      </span>
    </div>
  )
}

/* ── WhatsApp Message Bubble ──────────────────────────────────── */

function MessageBubble({
  msg,
  live,
  onChooseSplit,
}: {
  msg: ThreadMessage
  live: boolean
  onChooseSplit?: (partIndex: number, amount: string, splitCount: number) => void
}) {
  const isInbound = msg.direction === "inbound"
  const isSystem = msg.direction === "system"

  if (isSystem || msg.message_type === "scheduled_action") {
    const actionType = msg.extra_data
      ? asStr(asRecord(msg.extra_data).action_type)
      : asStr(msg.content)
    return (
      <div className="flex justify-center my-1">
        <div className="rounded-lg bg-[#182229] px-3 py-1 text-[11px] text-[#8696a0] shadow-sm">
          <span className="font-medium text-[#dcdcdc]">
            {actionType || "scheduled touchpoint"}
          </span>
          <span className="ml-1.5 opacity-60">{formatWhatsAppTime(msg.created_at)}</span>
        </div>
      </div>
    )
  }

  const delivery = msg.extra_data
    ? asStr(asRecord(msg.extra_data).delivery_status)
    : ""
  const payload = !isInbound ? agentPayload(msg) : null

  const splitToggle = (() => {
    const nonPaymentIntents = new Set([
      "SUPPORT", "QUESTION", "STOP_REQUEST", "LANGUAGE_SWITCHED",
      "NEGATIVE", "INVOICE_REQUEST", "ALREADY_PAID", "UNCLEAR",
    ])
    if (payload?.recovered) return null
    if (payload?.intent && nonPaymentIntents.has(payload.intent)) return null
    if (!payload?.split_options?.length) return null
    const preferred = payload.split_options.find((o) => o.count === 2) || payload.split_options[0]
    const parts = preferred?.amounts_formatted?.length ? preferred.amounts_formatted : []
    if (!parts.length) return null
    return { option: preferred, parts }
  })()

  // Delivery ticks
  const renderTicks = () => {
    if (isInbound) return null
    if (delivery === "read") return <DoubleTick read />
    if (delivery === "delivered") return <DoubleTick />
    if (delivery === "sent" || delivery) return <SingleTick />
    return <DoubleTick read />
  }

  return (
    <div className={`flex ${isInbound ? "justify-start" : "justify-end"} mb-[2px]`}>
      <div
        className={`relative max-w-[85%] rounded-lg px-[9px] pt-[6px] pb-[8px] text-[14.2px] leading-[19px] text-[#e9edef] ${
          isInbound
            ? "bg-[#202c33] rounded-tl-none"
            : "bg-[#005c4b] rounded-tr-none"
        }`}
      >
        {/* Bubble tail */}
        <div
          className={`absolute top-0 w-3 h-3 ${
            isInbound
              ? "-left-[5px] [clip-path:polygon(100%_0,0_0,100%_100%)] bg-[#202c33]"
              : "-right-[5px] [clip-path:polygon(0_0,100%_0,0_100%)] bg-[#005c4b]"
          }`}
        />

        {/* Agent badge (hidden in WhatsApp style, but useful for dashboard context) */}
        {!isInbound && (
          <span className="inline-block rounded bg-[#00a884]/20 px-1.5 py-px text-[10px] font-semibold text-[#00a884] mb-1">
            Agent
          </span>
        )}

        {/* Message content */}
        <div className="whitespace-pre-wrap leading-[19px]">
          {renderMessageContent(msg.content, payload, splitToggle, onChooseSplit)}
        </div>

        {/* Timestamp + ticks */}
        <div className="mt-0.5 flex items-center justify-end gap-1">
          {live && (
            <span className="rounded bg-[#00a884]/25 px-1 py-px text-[9px] font-bold text-[#00a884] uppercase">
              live
            </span>
          )}
          <span className="text-[11px] text-[#ffffff99] select-none">
            {formatWhatsAppTime(msg.created_at)}
          </span>
          <span className="text-[#ffffff99] select-none">
            {renderTicks()}
          </span>
        </div>
      </div>
    </div>
  )
}

/* ── Date Divider ────────────────────────────────────────────── */

function DateDivider({ label }: { label: string }) {
  return (
    <div className="flex justify-center my-3">
      <div className="bg-[#182229] text-slate-400 text-xs px-3 py-1 rounded-md shadow-sm font-medium tracking-wide self-center uppercase select-none">
        {label}
      </div>
    </div>
  )
}

/* ── Typing Indicator ────────────────────────────────────────── */

function TypingIndicator() {
  return (
    <div className="flex justify-end mb-[2px]">
      <div className="relative rounded-lg rounded-tr-none bg-[#005c4b] px-3 py-2.5">
        <div className="absolute top-0 -right-[5px] w-3 h-3 [clip-path:polygon(0_0,100%_0,0_100%)] bg-[#005c4b]" />
        <div className="flex items-center gap-[5px]">
          <span className="inline-block h-[7px] w-[7px] rounded-full bg-[#ffffff99] animate-bounce" style={{ animationDuration: "800ms", animationDelay: "0ms" }} />
          <span className="inline-block h-[7px] w-[7px] rounded-full bg-[#ffffff99] animate-bounce" style={{ animationDuration: "800ms", animationDelay: "150ms" }} />
          <span className="inline-block h-[7px] w-[7px] rounded-full bg-[#ffffff99] animate-bounce" style={{ animationDuration: "800ms", animationDelay: "300ms" }} />
        </div>
      </div>
    </div>
  )
}

/* ── Main Component ───────────────────────────────────────────── */

export default function ConversationHistory({
  conversations,
  liveMessages = [],
  liveQuickReplies = null,
  liveStatus = "closed",
  isTyping = false,
  customerName,
  customerPhone,
  onQuickReply,
  onSendMessage,
  quickRepliesDisabled = false,
  attemptCount = 0,
  maxAttempts = 5,
  currentLanguage = "en",
}: ConversationHistoryProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [localLanguage, setLocalLanguage] = useState(currentLanguage)
  const [pending, setPending] = useState<ThreadMessage[]>([])
  const pendingSeq = useRef(0)

  useEffect(() => { setLocalLanguage(currentLanguage) }, [currentLanguage])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [conversations, liveMessages, isTyping])

  const persisted: ThreadMessage[] = conversations.flatMap((conv) =>
    conv.messages.map((m) => ({ ...m, _convId: conv.id })),
  )

  const live: ThreadMessage[] = liveMessages.map((m) => ({
    id: m.id,
    direction: m.direction,
    content: m.content,
    message_type: m.message_type,
    extra_data: m.extra_data || null,
    created_at: m.created_at,
    _convId: m.conversation_id,
    _live: true,
  }))

  const allMessages = dedupe(
    [...persisted, ...live].sort(
      (a, b) => new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime(),
    ),
  )

  const liveConnected = liveStatus === "open"

  useEffect(() => {
    setPending((prev) => {
      if (!prev.length) return prev
      const have = new Set(
        allMessages.filter((m) => m.direction === "inbound").map((m) => m.content),
      )
      const next = prev.filter((p) => !have.has(p.content))
      return next.length === prev.length ? prev : next
    })
  }, [allMessages])

  const handleSend = useCallback(
    (text: string) => {
      const lower = text.toLowerCase()
      if (lower.includes("hindi") || lower.includes("hinglish") || lower === "hi") {
        setLocalLanguage("hi")
        onQuickReply?.("language_hi")
        return
      }
      if (lower.includes("english") || lower === "en") {
        setLocalLanguage("en")
        onQuickReply?.("language_en")
        return
      }
      setPending((prev) => [
        ...prev,
        {
          id: `pending-${++pendingSeq.current}`,
          direction: "inbound",
          content: text,
          message_type: "text",
          extra_data: null,
          created_at: new Date().toISOString(),
          _convId: conversations[0]?.id ?? "pending",
        },
      ])
      onSendMessage?.(text)
    },
    [onSendMessage, onQuickReply, conversations],
  )

  const handleLanguageToggle = useCallback(() => {
    const newLang = localLanguage === "hi" || localLanguage === "hi-en" ? "en" : "hi"
    setLocalLanguage(newLang)
    onQuickReply?.(newLang === "hi" ? "language_hi" : "language_en")
  }, [localLanguage, onQuickReply])

  const handleChooseSplit = useCallback(
    (partIndex: number, amount: string, splitCount: number) => {
      const message = `I want to pay Part ${partIndex + 1} (${amount}) now in ${splitCount} installments`
      onSendMessage?.(message)
    },
    [onSendMessage],
  )

  // Group messages by date
  const groupedMessages: Array<{ dateKey: string; dateLabel: string; messages: ThreadMessage[] }> = []
  let currentGroup: { dateKey: string; dateLabel: string; messages: ThreadMessage[] } | null = null

  for (const msg of allMessages) {
    const dateKey = getDateKey(msg.created_at)
    if (!currentGroup || currentGroup.dateKey !== dateKey) {
      currentGroup = { dateKey, dateLabel: getDateLabel(msg.created_at), messages: [] }
      groupedMessages.push(currentGroup)
    }
    currentGroup.messages.push(msg)
  }

  const displayName = customerName || "Savita Pillai"
  const displayPhone = customerPhone || "+91 98765 43210"
  const initials = getInitials(displayName)

  const isEmpty = allMessages.length === 0 && pending.length === 0

  return (
    <div className="flex justify-center py-4">
      {/* ── Phone Frame ── */}
      <div className="relative w-full max-w-[400px] rounded-3xl border border-slate-700/60 shadow-2xl overflow-hidden flex flex-col h-[700px] bg-[#0b141a]">
        {/* ── WhatsApp Header ── */}
        <div className="bg-[#202c33] px-4 py-3 flex items-center justify-between text-slate-100 border-b border-slate-700/40">
          {/* Left side */}
          <div className="flex items-center gap-3">
            {/* Back arrow */}
            <button className="flex items-center justify-center text-[#aebac1] hover:text-[#e9edef] transition-colors">
              <ArrowLeft className="h-5 w-5" />
            </button>

            {/* Avatar */}
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#6b7b8a] text-[14px] font-bold text-[#cfd6dc]">
              {initials}
            </div>

            {/* Name + status */}
            <div className="min-w-0">
              <h2 className="truncate text-[16px] font-normal text-[#e9edef] leading-tight">
                {displayName}
              </h2>
              <p className="truncate text-[13px] leading-tight">
                <span style={{ color: "#00a884" }}>
                  {isTyping ? "typing..." : liveConnected ? "online" : displayPhone}
                </span>
              </p>
            </div>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-1">
            {/* Video call */}
            <button className="flex h-9 w-9 items-center justify-center rounded-full text-[#aebac1] hover:text-[#e9edef] transition-colors">
              <Video className="h-5 w-5" />
            </button>

            {/* Voice call */}
            <button className="flex h-9 w-9 items-center justify-center rounded-full text-[#aebac1] hover:text-[#e9edef] transition-colors">
              <Phone className="h-5 w-5" />
            </button>

            {/* 3-dot menu */}
            <button className="flex h-9 w-9 items-center justify-center rounded-full text-[#aebac1] hover:text-[#e9edef] transition-colors">
              <MoreVertical className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* ── Chat Area ── */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-[5%] py-2 scrollbar-thin scrollbar-thumb-[#374045] scrollbar-track-transparent"
          style={{
            backgroundColor: "#0b141a",
            backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.02'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
          }}
        >
          {isEmpty ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="h-16 w-16 rounded-full bg-[#1f2c34] flex items-center justify-center mb-3">
                <svg viewBox="0 0 212 212" width="44" height="44" className="text-[#00a884]">
                  <path
                    d="M106.251 0.5C164.653 0.5 212 47.846 212 106.25S164.653 212 106.25 212C47.846 212 0.5 164.654 0.5 106.25S47.846 0.5 106.251 0.5Z"
                    fill="currentColor" fillOpacity="0.15"
                  />
                  <path
                    d="M173.561 171.615a62.767 62.767 0 0 0-2.065-2.955 67.7 67.7 0 0 0-2.608-3.299 70.112 70.112 0 0 0-3.184-3.527 71.097 71.097 0 0 0-5.924-5.47 72.458 72.458 0 0 0-10.204-7.026 75.2 75.2 0 0 0-5.98-3.055c-.062-.028-.118-.059-.18-.087-9.792-4.44-22.106-7.529-37.416-7.529s-27.624 3.089-37.416 7.529c-.338.153-.653.318-.985.474a75.37 75.37 0 0 0-6.229 3.298 72.589 72.589 0 0 0-9.15 6.395 71.243 71.243 0 0 0-5.924 5.47 70.064 70.064 0 0 0-3.184 3.527 67.142 67.142 0 0 0-2.609 3.299 63.292 63.292 0 0 0-2.065 2.955 56.33 56.33 0 0 0-1.447 2.324c-.033.056-.073.119-.104.174a47.92 47.92 0 0 0-1.07 1.926c-.559 1.068-.818 1.678-.818 1.678v.398c18.285 17.927 43.322 28.985 70.945 28.985 27.678 0 52.761-11.103 71.055-29.095v-.289s-.619-1.21-1.73-3.241a47.77 47.77 0 0 0-.644-1.163 56.297 56.297 0 0 0-1.502-2.49ZM106.002 125.5c2.645 0 5.212-.253 7.68-.737a38.272 38.272 0 0 0 3.624-.896 37.124 37.124 0 0 0 5.12-1.958 36.307 36.307 0 0 0 6.15-3.67 35.923 35.923 0 0 0 9.489-10.48 36.558 36.558 0 0 0 2.422-4.84 37.051 37.051 0 0 0 1.716-5.25c.299-1.208.542-2.443.725-3.701.275-1.887.417-3.827.417-5.811s-.142-3.925-.417-5.811a38.734 38.734 0 0 0-.725-3.701 37.051 37.051 0 0 0-1.716-5.25 36.558 36.558 0 0 0-2.422-4.84 35.923 35.923 0 0 0-9.489-10.48 36.347 36.347 0 0 0-6.15-3.67 37.124 37.124 0 0 0-5.12-1.958 37.67 37.67 0 0 0-3.624-.896 39.875 39.875 0 0 0-7.68-.737c-21.162 0-37.345 16.183-37.345 37.345 0 21.159 16.183 37.342 37.345 37.342Z"
                    fill="currentColor"
                  />
                </svg>
              </div>
              <p className="text-[13px] text-[#8696a0]">No messages yet</p>
              <p className="text-[12px] text-[#8696a0]/60 mt-1">Waiting for WhatsApp activity</p>
            </div>
          ) : (
            <>
              {/* Attempt limit */}
              <AttemptLimitBanner attemptCount={attemptCount} maxAttempts={maxAttempts} />

              {/* Messages grouped by date */}
              {groupedMessages.map((group) => (
                <div key={group.dateKey}>
                  <DateDivider label={group.dateLabel} />
                  {group.messages.map((msg, i) => (
                    <MessageBubble
                      key={`${msg._convId}:${msg.id || i}`}
                      live={Boolean(msg._live)}
                      msg={msg}
                      onChooseSplit={handleChooseSplit}
                    />
                  ))}
                </div>
              ))}

              {/* Pending messages */}
              {pending.map((p) => (
                <MessageBubble key={p.id} live={false} msg={p} />
              ))}

              {/* Typing indicator */}
              {isTyping && <TypingIndicator />}
            </>
          )}        </div>

        {/* ── Quick Replies (outside scroll, always visible) ── */}
        {!isEmpty && (
          <ContextualQuickReplies
            messages={allMessages}
            onReply={onQuickReply}
            liveConnected={liveConnected}
            language={localLanguage}
            liveReplies={liveQuickReplies}
          />
        )}

        {/* ── Bottom Input Bar (always enabled) ── */}
        <WhatsAppInputBar
          onSend={handleSend}
          onLanguageToggle={handleLanguageToggle}
          disabled={false}
        />
      </div>
    </div>
  )
}
