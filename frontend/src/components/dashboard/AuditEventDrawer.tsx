import { useEffect, useState } from "react"
import {
  X,
  ScrollText,
  Clock,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Ban,
  CreditCard,
  MessageSquare,
  Brain,
  ShieldCheck,
  Send,
  CalendarCheck,
  FileText,
  RefreshCw,
  Zap,
} from "lucide-react"
import type { RecoveryTimeline, TimelineEvent } from "../../types/analytics"
import { fetchCaseTimeline } from "../../services/analytics"

/* ── Event-type → icon / tint / label mapping ─────────────────── */

const EVENT_META: Record<
  string,
  { icon: typeof Clock; tint: string; label: string; layer: string }
> = {
  REVENUE_DETECTED:        { icon: AlertTriangle,  tint: "border-rose-500/20 bg-rose-500/10 text-rose-400",   label: "Revenue Detected",    layer: "Gateway" },
  RISK_DETECTED:           { icon: ShieldCheck,    tint: "border-amber-500/20 bg-amber-500/10 text-amber-400", label: "Risk Assessed",        layer: "Diagnosis" },
  RECOVERY_STARTED:        { icon: RefreshCw,      tint: "border-blue-500/20 bg-blue-500/10 text-blue-400",    label: "Recovery Started",     layer: "System" },
  STRATEGY_SELECTED:       { icon: Brain,           tint: "border-violet-500/20 bg-violet-500/10 text-violet-400", label: "Strategy Selected", layer: "Decision" },
  ACTION_SCHEDULED:        { icon: CalendarCheck,   tint: "border-indigo-500/20 bg-indigo-500/10 text-indigo-400", label: "Action Scheduled",  layer: "System" },
  ACTION_CANCELLED:        { icon: Ban,             tint: "border-rose-500/20 bg-rose-500/10 text-rose-400",    label: "Action Cancelled",     layer: "System" },
  MESSAGE_SENT:            { icon: Send,            tint: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400", label: "Message Sent",    layer: "Channel" },
  MESSAGE_FAILED:          { icon: XCircle,         tint: "border-rose-500/20 bg-rose-500/10 text-rose-400",    label: "Message Failed",       layer: "Channel" },
  CUSTOMER_REPLIED:        { icon: MessageSquare,   tint: "border-cyan-500/20 bg-cyan-500/10 text-cyan-400",    label: "Customer Reply",       layer: "Channel" },
  INTENT_DETECTED:         { icon: Brain,           tint: "border-violet-500/20 bg-violet-500/10 text-violet-400", label: "Intent Detected",   layer: "Decision" },
  PROMISE_CREATED:         { icon: CalendarCheck,   tint: "border-blue-500/20 bg-blue-500/10 text-blue-400",    label: "Promise Created",      layer: "Engagement" },
  PAYMENT_PLAN_PROPOSED:   { icon: FileText,        tint: "border-indigo-500/20 bg-indigo-500/10 text-indigo-400", label: "Plan Proposed",    layer: "Engagement" },
  PAYMENT_PLAN_ACCEPTED:   { icon: CheckCircle2,    tint: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400", label: "Plan Accepted",  layer: "Engagement" },
  INSTALLMENT_CREATED:     { icon: FileText,        tint: "border-slate-500/20 bg-slate-500/10 text-slate-400",  label: "Installment Due",      layer: "System" },
  INSTALLMENT_PAID:        { icon: CreditCard,      tint: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400", label: "Installment Paid",  layer: "Gateway" },
  INVOICE_REQUESTED:       { icon: FileText,        tint: "border-slate-500/20 bg-slate-500/10 text-slate-400",  label: "Invoice Requested",    layer: "Channel" },
  INVOICE_SENT:            { icon: Send,            tint: "border-blue-500/20 bg-blue-500/10 text-blue-400",     label: "Invoice Sent",         layer: "Channel" },
  PAYMENT_RETRIED:         { icon: RefreshCw,       tint: "border-amber-500/20 bg-amber-500/10 text-amber-400",  label: "Payment Retried",      layer: "Gateway" },
  PAYMENT_RECOVERED:       { icon: CheckCircle2,    tint: "border-emerald-500/30 bg-emerald-500/15 text-emerald-400", label: "Payment Recovered", layer: "Outcome" },
  RECOVERY_STOPPED:        { icon: Ban,             tint: "border-rose-500/20 bg-rose-500/10 text-rose-400",     label: "Recovery Stopped",     layer: "Outcome" },
  RECOVERY_EXPIRED:        { icon: Clock,           tint: "border-slate-500/20 bg-slate-500/10 text-slate-400",  label: "Recovery Expired",     layer: "Outcome" },
  AI_ERROR:                { icon: Zap,             tint: "border-amber-500/20 bg-amber-500/10 text-amber-400",  label: "AI Error",             layer: "System" },
  EXTERNAL_API_ERROR:      { icon: Zap,             tint: "border-rose-500/20 bg-rose-500/10 text-rose-400",     label: "API Error",            layer: "System" },
  // Simulate-path events
  created:                 { icon: AlertTriangle,   tint: "border-rose-500/20 bg-rose-500/10 text-rose-400",    label: "Case Created",         layer: "Gateway" },
  customer_replied:        { icon: MessageSquare,   tint: "border-cyan-500/20 bg-cyan-500/10 text-cyan-400",     label: "Customer Reply",       layer: "Channel" },
  intent_classified:       { icon: Brain,           tint: "border-violet-500/20 bg-violet-500/10 text-violet-400", label: "Intent Classified",  layer: "Decision" },
  promise_missed:          { icon: XCircle,         tint: "border-amber-500/20 bg-amber-500/10 text-amber-400",  label: "Promise Missed",       layer: "Outcome" },
  payment_plan_proposed:   { icon: FileText,        tint: "border-indigo-500/20 bg-indigo-500/10 text-indigo-400", label: "Plan Proposed",     layer: "Engagement" },
  expiry_reminder_sent:    { icon: Send,            tint: "border-amber-500/20 bg-amber-500/10 text-amber-400",  label: "Expiry Reminder",      layer: "Channel" },
  payment_recovered:       { icon: CheckCircle2,    tint: "border-emerald-500/30 bg-emerald-500/15 text-emerald-400", label: "Payment Recovered", layer: "Outcome" },
  recovery_initiated:      { icon: RefreshCw,       tint: "border-blue-500/20 bg-blue-500/10 text-blue-400",     label: "Recovery Initiated",   layer: "System" },
}

function getMeta(eventType: string) {
  return (
    EVENT_META[eventType] || {
      icon: Clock,
      tint: "border-slate-600/20 bg-slate-700/20 text-slate-400",
      label: eventType.replace(/_/g, " "),
      layer: "Other",
    }
  )
}

const LAYER_TINTS: Record<string, string> = {
  Gateway:   "border-rose-500/20 bg-rose-500/10 text-rose-400",
  Diagnosis: "border-amber-500/20 bg-amber-500/10 text-amber-400",
  Decision:  "border-violet-500/20 bg-violet-500/10 text-violet-400",
  Channel:   "border-cyan-500/20 bg-cyan-500/10 text-cyan-400",
  Engagement:"border-blue-500/20 bg-blue-500/10 text-blue-400",
  System:    "border-indigo-500/20 bg-indigo-500/10 text-indigo-400",
  Outcome:   "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
  Other:     "border-slate-600/20 bg-slate-700/20 text-slate-400",
}

/* ── Helpers ──────────────────────────────────────────────────── */

function fmtTs(s: string | null) {
  if (!s) return ""
  const d = new Date(s)
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

function fmtAmount(paise: number | null) {
  if (paise == null) return ""
  return `₹${Math.round(paise / 100).toLocaleString("en-IN")}`
}

function eventTitle(ev: TimelineEvent) {
  const meta = getMeta(ev.event_type)
  if (ev.amount != null) return `${meta.label} · ${fmtAmount(ev.amount)}`
  return meta.label
}

function MetadataTable({ data }: { data: Record<string, unknown> | null }) {
  if (!data || Object.keys(data).length === 0) return null
  // Filter out noisy/large keys
  const skip = new Set(["amount_formatted", "event_type", "description"])
  const entries = Object.entries(data).filter(
    ([k, v]) => !skip.has(k) && v != null && v !== ""
  )
  if (entries.length === 0) return null
  return (
    <div className="mt-1.5 rounded-md border border-edge bg-panel-2 p-2">
      {entries.slice(0, 8).map(([k, v]) => (
        <div key={k} className="flex items-start justify-between gap-3 py-0.5">
          <span className="shrink-0 text-[10px] font-medium text-slate-500">
            {k.replace(/_/g, " ")}
          </span>
          <span className="min-w-0 truncate text-right text-[10px] font-mono text-slate-300">
            {typeof v === "object" ? JSON.stringify(v).slice(0, 80) : String(v).slice(0, 80)}
          </span>
        </div>
      ))}
    </div>
  )
}

/* ── Root Cause Card ─────────────────────────────────────────── */

const ROOT_CAUSE_LABELS: Record<string, { label: string; desc: string; tint: string }> = {
  TECHNICAL_RETRY:      { label: "Technical Glitch",        desc: "Gateway timeout / network blip — transient, retried automatically.", tint: "border-amber-500/20 bg-amber-500/10 text-amber-400" },
  LIQUIDITY_CONSTRAINT: { label: "Liquidity Constraint",    desc: "Insufficient funds — customer wants to pay but cannot today.", tint: "border-blue-500/20 bg-blue-500/10 text-blue-400" },
  USER_HESITATION:      { label: "User Hesitation",         desc: "Checkout abandoned or payment declined — gentle nudge converts best.", tint: "border-cyan-500/20 bg-cyan-500/10 text-cyan-400" },
  MANDATE_EXPIRY:       { label: "Mandate Expiry",          desc: "Recurring mandate expired or declined — re-setup required.", tint: "border-violet-500/20 bg-violet-500/10 text-violet-400" },
  ACCOUNT_ISSUE:        { label: "Account Issue",           desc: "Account frozen/blocked — not recoverable via automation.", tint: "border-rose-500/20 bg-rose-500/10 text-rose-400" },
  FRAUD_RISK:           { label: "Fraud Risk",              desc: "Transaction flagged — automated recovery halted.", tint: "border-rose-500/30 bg-rose-500/20 text-rose-400" },
}

function RootCauseCard({ rootCause }: { rootCause: string | null }) {
  if (!rootCause) return null
  const rc = ROOT_CAUSE_LABELS[rootCause]
  const label = rc?.label || rootCause.replace(/_/g, " ")
  const desc = rc?.desc || ""
  const tint = rc?.tint || LAYER_TINTS.Other
  return (
    <div className={`rounded-lg border p-3 ${tint}`}>
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
        <span className="text-xs font-semibold">Root Cause</span>
      </div>
      <p className="mt-1 text-sm font-bold">{label}</p>
      {desc && <p className="mt-0.5 text-[11px] opacity-80">{desc}</p>}
    </div>
  )
}

/* ── Single Event Row ────────────────────────────────────────── */

function EventRow({ ev, isFirst }: { ev: TimelineEvent; isFirst: boolean }) {
  const meta = getMeta(ev.event_type)
  const Icon = meta.icon
  const layerTint = LAYER_TINTS[meta.layer] || LAYER_TINTS.Other

  return (
    <div className="relative flex gap-3 pb-4 last:pb-0">
      {/* Vertical connector */}
      {!isFirst && (
        <div className="absolute left-[11px] top-6 bottom-0 w-px bg-slate-800/60" />
      )}

      {/* Dot */}
      <div className={`relative z-10 mt-1 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border ${meta.tint}`}>
        <Icon className="h-2.5 w-2.5" />
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold text-slate-200">
            {eventTitle(ev)}
          </span>
          <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-medium ${layerTint}`}>
            {meta.layer}
          </span>
        </div>

        {ev.reason && (
          <p className="mt-0.5 text-[11px] leading-relaxed text-slate-400">
            {ev.reason}
          </p>
        )}

        {/* State change */}
        {ev.old_value && ev.new_value && (
          <div className="mt-1 flex items-center gap-1.5 text-[10px]">
            <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-slate-400">
              {JSON.stringify(ev.old_value).slice(0, 30)}
            </span>
            <span className="text-slate-600">→</span>
            <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-slate-300">
              {JSON.stringify(ev.new_value).slice(0, 30)}
            </span>
          </div>
        )}

        {/* Metadata */}
        <MetadataTable data={ev.metadata as Record<string, unknown>} />

        {/* Timestamp */}
        <div className="mt-1 flex items-center gap-1.5 text-[10px] text-slate-600">
          <Clock className="h-2.5 w-2.5" />
          {fmtTs(ev.timestamp)}
        </div>
      </div>
    </div>
  )
}

/* ── Main Drawer ─────────────────────────────────────────────── */

export default function AuditEventDrawer({
  open,
  onClose,
  caseId,
  rootCause,
}: {
  open: boolean
  onClose: () => void
  caseId: string
  rootCause?: string | null
}) {
  const [timeline, setTimeline] = useState<RecoveryTimeline | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [layerFilter, setLayerFilter] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !caseId) return
    setLoading(true)
    setError(null)
    fetchCaseTimeline(caseId)
      .then(setTimeline)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err))
      )
      .finally(() => setLoading(false))
  }, [open, caseId])

  if (!open) return null

  const events = timeline?.timeline || []
  const summary = timeline?.summary
  const layers = Array.from(new Set(events.map((ev) => getMeta(ev.event_type).layer)))
  const filtered = layerFilter
    ? events.filter((ev) => getMeta(ev.event_type).layer === layerFilter)
    : events

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <button
        aria-label="Close audit drawer"
        className="absolute inset-0 cursor-default bg-black/60 backdrop-blur-[2px]"
        onClick={onClose}
      />

      {/* Drawer panel */}
      <aside className="relative flex h-full w-full max-w-lg flex-col border-l border-edge bg-panel shadow-2xl">
        {/* Header */}
        <header className="flex items-center justify-between border-b border-edge px-5 py-4">
          <div className="flex items-center gap-2.5">
            <ScrollText className="h-5 w-5 text-emerald-400" />
            <div>
              <h2 className="text-sm font-semibold text-slate-100">
                Audit Trail
              </h2>
              <p className="text-[11px] text-slate-500">
                {summary
                  ? `${summary.total_events} events · ${summary.messages_sent} messages · ${summary.payments_recovered} recovered`
                  : "Loading…"}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-slate-700 p-1.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {/* Root cause card */}
        {rootCause && (
          <div className="border-b border-edge px-5 py-3">
            <RootCauseCard rootCause={rootCause} />
          </div>
        )}

        {/* Layer filter chips */}
        {layers.length > 1 && (
          <div className="flex flex-wrap gap-1.5 border-b border-edge px-5 py-2.5">
            <button
              onClick={() => setLayerFilter(null)}
              className={`rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors ${
                layerFilter === null
                  ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                  : "border-slate-700 bg-panel-2 text-slate-400 hover:bg-slate-800"
              }`}
            >
              All
            </button>
            {layers.map((l) => (
              <button
                key={l}
                onClick={() => setLayerFilter(l === layerFilter ? null : l)}
                className={`rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors ${
                  layerFilter === l
                    ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                    : "border-slate-700 bg-panel-2 text-slate-400 hover:bg-slate-800"
                }`}
              >
                {l}
              </button>
            ))}
          </div>
        )}

        {/* Event list */}
        <div className="flex-1 overflow-y-auto px-5 py-4 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-700 border-t-emerald-500" />
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 p-4 text-center">
              <p className="text-xs text-rose-400">{error}</p>
            </div>
          )}

          {!loading && !error && filtered.length === 0 && (
            <p className="py-12 text-center text-xs text-slate-500">
              No audit events recorded yet.
            </p>
          )}

          {!loading && !error && filtered.length > 0 && (
            <div>
              {filtered.map((ev, i) => (
                <EventRow key={ev.id || i} ev={ev} isFirst={i === 0} />
              ))}
            </div>
          )}
        </div>

        {/* Summary footer */}
        {summary && (
          <footer className="border-t border-edge px-5 py-3">
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <div className="text-[10px] font-medium text-slate-500">Sent</div>
                <div className="text-sm font-semibold font-mono text-emerald-400">
                  {summary.messages_sent}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-medium text-slate-500">Replies</div>
                <div className="text-sm font-semibold font-mono text-cyan-400">
                  {summary.customer_replies}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-medium text-slate-500">Recovered</div>
                <div className="text-sm font-semibold font-mono text-emerald-400">
                  {fmtAmount(summary.recovered_amount)}
                </div>
              </div>
            </div>
          </footer>
        )}
      </aside>
    </div>
  )
}
