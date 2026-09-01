import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { useParams, Link } from "react-router-dom"
import {
  ArrowLeft,
  ChevronRight,
  ShieldCheck,
  ScrollText,
  Cpu,
  PauseCircle,
  Download,
  MoreHorizontal,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  CalendarCheck,
  BarChart3,
  XCircle,
  Ban,
  Calendar,
  Activity,
  CreditCard,
  Clock,
  Zap,
  Hand,
  MessageCircle,
  CalendarRange,
  CornerDownRight,
  Boxes,
  Gauge,
  Landmark,
  Mail,
} from "lucide-react"
import type {
  RecoveryCaseDetail,
  PaymentPromise,
  Conversation,
  PolicyTrace,
  CaseSchedule,
  SentEmail,
} from "../types/analytics"
import {
  fetchRecoveryCaseDetail,
  fetchCasePromises,
  fetchCaseConversations,
  fetchCasePolicyTrace,
  fetchCaseSchedule,
  fetchCaseEmails,
  runAutonomousScheduler,
} from "../services/analytics"
import { simulateCustomerMessage, generateCaseEmail } from "../services/operations"
import ConversationHistory from "../components/dashboard/ConversationHistory"
import EmailHistory from "../components/dashboard/EmailHistory"
import PolicyTraceInspector from "../components/dashboard/PolicyTraceInspector"
import AgentThoughtStream from "../components/dashboard/AgentThoughtStream"
import ComplianceDrawer from "../components/dashboard/ComplianceDrawer"
import AuditEventDrawer from "../components/dashboard/AuditEventDrawer"
import { useLiveCaseStream } from "../services/realtime"
import type { LiveCaseEvent } from "../services/realtime"
import { initials } from "../lib/format"
import { caseMeta } from "../lib/status"

// ── Helpers ────────────────────────────────────────────────────

function fmt(paise: number): string {
  return `₹${Math.round(Number(paise) / 100).toLocaleString("en-IN")}`
}

function fmtTime(s: string | null): string {
  if (!s) return ""
  return new Date(s).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })
}

function fmtTimeFull(s: string | null): string {
  if (!s) return ""
  return new Date(s).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

function countdown(scheduledFor: string | null): string {
  if (!scheduledFor) return "not scheduled"
  const diff = new Date(scheduledFor).getTime() - Date.now()
  if (diff <= 0) return "Due now"
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `in ${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 48) return `in ${hrs}h ${mins % 60}m`
  const days = Math.floor(hrs / 24)
  return days === 1 ? "tomorrow" : `in ${days}d`
}

function stageFromStatus(status: string): string | null {
  const map: Record<string, string> = {
    AT_RISK: "FAILED",
    RECOVERY_IN_PROGRESS: "CONTACTED",
    ENGAGED: "ENGAGED",
    PARTIALLY_RECOVERED: "ENGAGED",
    PROMISED: "PROMISED",
    PAYMENT_PLAN: "PAYMENT_PLAN",
    SCHEDULED: "PROMISED",
    RECOVERED: "RECOVERED",
    LOST: "HARD_DROPPED",
    STOPPED: "HARD_DROPPED",
  }
  return map[status] ?? null
}

// ═══════════════════════════════════════════════════════════════
// STATUS ICON / TOKEN MAPS
// ═══════════════════════════════════════════════════════════════

const STATUS_ICONS: Record<string, typeof AlertTriangle> = {
  AT_RISK: AlertTriangle,
  RECOVERY_IN_PROGRESS: RefreshCw,
  PROMISED: CalendarCheck,
  ENGAGED: MessageCircle,
  PAYMENT_PLAN: CalendarRange,
  SCHEDULED: Calendar,
  PARTIALLY_RECOVERED: BarChart3,
  RECOVERED: CheckCircle2,
  LOST: XCircle,
  STOPPED: Ban,
}

// ═══════════════════════════════════════════════════════════════
// 1. HEADER BAR
// ═══════════════════════════════════════════════════════════════

function Breadcrumb({ name, invoiceId }: { name: string; invoiceId: string }) {
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-[12px] text-ink-faint">
      <Link to="/dashboard" className="transition-colors hover:text-ink-muted">
        Dashboard
      </Link>
      <ChevronRight className="h-3 w-3" aria-hidden="true" />
      <Link to="/cases" className="transition-colors hover:text-ink-muted">
        Cases
      </Link>
      <ChevronRight className="h-3 w-3" aria-hidden="true" />
      <span className="truncate font-medium text-ink-muted">
        {name} <span className="font-mono text-ink-faint">({invoiceId})</span>
      </span>
    </nav>
  )
}

function StatusTag({ status }: { status: string }) {
  const meta = caseMeta(status)
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold tracking-wide ${meta.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden="true" />
      {meta.label}
    </span>
  )
}

function HeaderBar({ detail }: { detail: RecoveryCaseDetail }) {
  const Icon = STATUS_ICONS[detail.status] || AlertTriangle
  const name = detail.customer_name || "Unknown"
  const invoiceId = detail.revenue_event_id?.slice(0, 12).toUpperCase() || "INV"

  return (
    <header className="flex flex-col gap-4 border-b border-edge pb-6">
      <Breadcrumb name={name} invoiceId={invoiceId} />

      <div className="flex flex-wrap items-start justify-between gap-4">
        {/* Identity */}
        <div className="flex min-w-0 items-center gap-3.5">
          <div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-edge bg-panel-2 shadow-inner">
            <span className="text-[13px] font-semibold tracking-tight text-ink">
              {initials(detail.customer_name)}
            </span>
            {detail.status === "PROMISED" && (
              <span className="absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full border-2 border-canvas bg-amber-400">
                <Icon className="h-2.5 w-2.5 text-amber-950" aria-hidden="true" />
              </span>
            )}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="truncate text-lg font-semibold tracking-tight text-ink">
                {name}
              </h1>
              <StatusTag status={detail.status} />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[12px] text-ink-muted">
              {detail.customer_email && <span className="max-w-[240px] truncate">{detail.customer_email}</span>}
              {detail.customer_phone && (
                <>
                  <span className="text-edge-strong" aria-hidden="true">·</span>
                  <span className="font-mono">{detail.customer_phone}</span>
                </>
              )}
              <span className="text-edge-strong" aria-hidden="true">·</span>
              <span className="font-mono text-ink-faint">#{invoiceId}</span>
            </div>
          </div>
        </div>

        {/* Quick actions */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg border border-edge bg-panel px-3 py-1.5 text-[12px] font-medium text-ink-muted transition-colors hover:border-edge-strong hover:bg-elevated hover:text-ink"
          >
            <PauseCircle className="h-3.5 w-3.5" aria-hidden="true" />
            Pause Automation
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg border border-edge bg-panel px-3 py-1.5 text-[12px] font-medium text-ink-muted transition-colors hover:border-edge-strong hover:bg-elevated hover:text-ink"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Export Case
          </button>
          <button
            type="button"
            aria-label="More actions"
            className="inline-flex items-center justify-center rounded-lg border border-edge bg-panel p-1.5 text-ink-faint transition-colors hover:border-edge-strong hover:bg-elevated hover:text-ink"
          >
            <MoreHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>
  )
}

// ═══════════════════════════════════════════════════════════════
// 2. KEY METRICS BAR
// ═══════════════════════════════════════════════════════════════

function MetricTile({
  icon,
  label,
  value,
  sub,
  tone = "neutral",
}: {
  icon: ReactNode
  label: string
  value: string
  sub: string
  tone?: "neutral" | "amber" | "emerald"
}) {
  const valueTone =
    tone === "amber" ? "text-amber-400"
      : tone === "emerald" ? "text-emerald-400"
        : "text-ink"
  return (
    <div className="card-sheen flex min-w-0 flex-col rounded-xl p-4">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-faint">
          {label}
        </p>
        <span className="shrink-0 text-ink-faint" aria-hidden="true">{icon}</span>
      </div>
      <p className={`mt-2 font-mono text-lg font-semibold leading-tight tabular-nums ${valueTone}`}>
        {value}
      </p>
      <p className="mt-1 truncate text-[11px] text-ink-muted">{sub}</p>
    </div>
  )
}

function MetricsBar({ detail }: { detail: RecoveryCaseDetail }) {
  const rate = detail.original_amount > 0
    ? Math.round((detail.recovered_amount / detail.original_amount) * 100)
    : 0

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricTile
        icon={<Landmark className="h-3.5 w-3.5" aria-hidden="true" />}
        label="Total Invoiced"
        value={fmt(detail.original_amount)}
        sub="Original failure amount"
      />
      <MetricTile
        icon={<Gauge className="h-3.5 w-3.5" aria-hidden="true" />}
        label="Current At-Risk"
        value={fmt(detail.remaining_amount)}
        sub={`Risk level ${detail.risk_level || "—"} · ${detail.risk_reason || "—"}`}
        tone="amber"
      />
      <MetricTile
        icon={<CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />}
        label="Recovered to Date"
        value={fmt(detail.recovered_amount)}
        sub="Verified captured revenue"
        tone="emerald"
      />
      <div className="card-sheen flex min-w-0 flex-col rounded-xl p-4">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-faint">
            Recovery Progress
          </p>
          <span className="flex items-center gap-1.5 text-[11px] text-ink-faint">
            <Activity className="h-3.5 w-3.5" aria-hidden="true" />
            Attempt {detail.attempt_count} of {detail.max_attempts}
          </span>
        </div>
        <div className="mt-2 flex items-baseline justify-between">
          <span className="font-mono text-lg font-semibold leading-tight tabular-nums text-emerald-400">
            {rate}%
          </span>
          <span className="text-[11px] text-ink-muted">recovered</span>
        </div>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
          <div
            className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-emerald-400 transition-all"
            style={{ width: `${rate}%` }}
          />
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 3. PIPELINE STEPPER (sleek node stepper, left column)
// ═══════════════════════════════════════════════════════════════

const STEPS = ["FAILED", "CONTACTED", "ENGAGED", "PROMISED", "PAYMENT_PLAN", "RECOVERED"] as const

const STEP_LABEL: Record<string, string> = {
  FAILED: "Failed",
  CONTACTED: "Contacted",
  ENGAGED: "Engaged",
  PROMISED: "Promised",
  PAYMENT_PLAN: "Payment Plan",
  RECOVERED: "Recovered",
}

function RecoveryStepper({ current }: { current: string | null }) {
  const currentIdx = current ? STEPS.indexOf(current as (typeof STEPS)[number]) : -1
  const stopped = current === "HARD_DROPPED"
  const doneThrough = stopped ? Math.max(0, currentIdx - 1) : currentIdx

  return (
    <div className="card-sheen rounded-xl px-5 py-4">
      <div className="flex items-center" role="list" aria-label="Recovery pipeline">
        {STEPS.map((stage, i) => {
          const isDone = i < doneThrough
          const isActive = i === currentIdx && !stopped
          const isStopped = stopped && i >= currentIdx && i > 0
          const nodeTone = isDone
            ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-400"
            : isActive
              ? "border-royal/60 bg-royal-soft text-royal ring-4 ring-royal/10"
              : isStopped
                ? "border-danger/50 bg-danger-soft text-danger"
                : "border-edge bg-panel-2 text-ink-faint"
          return (
            <div key={stage} className="flex flex-1 items-center last:flex-none">
              <div className="flex flex-col items-center gap-1.5 min-w-0">
                <div
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border font-semibold transition-colors ${nodeTone}`}
                  role="listitem"
                  aria-current={isActive ? "step" : undefined}
                >
                  {isDone ? (
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                  ) : isStopped && i === currentIdx ? (
                    <Ban className="h-3 w-3" aria-hidden="true" />
                  ) : (
                    <span className="text-[10px]">{i + 1}</span>
                  )}
                </div>
                <span
                  className={`text-center text-[10px] font-medium leading-none ${
                    isActive ? "text-ink" : isDone ? "text-emerald-400/80" : isStopped ? "text-danger/80" : "text-ink-faint"
                  }`}
                >
                  {STEP_LABEL[stage]}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div className="mx-1.5 mb-4 h-px flex-1 bg-white/[0.07] min-w-2" aria-hidden="true">
                  <div
                    className={`h-px transition-all ${
                      i < doneThrough
                        ? "w-full bg-emerald-500/50"
                        : isActive
                          ? "w-full bg-gradient-to-r from-emerald-500/50 to-emerald-500/10"
                          : "w-0"
                    }`}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
      {stopped && (
        <p className="mt-3 border-t border-edge pt-2.5 text-[11px] text-danger">
          Recovery stopped / opted out — all scheduled outreach cancelled.
        </p>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 4. CONVERSATION PANEL (left column)
// ═══════════════════════════════════════════════════════════════

function ConversationPanel({
  conversations,
  liveMessages,
  liveQuickReplies,
  liveStatus,
  isTyping,
  customerName,
  customerPhone,
  terminal,
  attemptCount,
  maxAttempts,
  onQuickReply,
  onSendMessage,
}: {
  conversations: Conversation[]
  liveMessages: ReturnType<typeof useLiveCaseStream>["liveMessages"]
  liveQuickReplies: ReturnType<typeof useLiveCaseStream>["liveQuickReplies"]
  liveStatus: ReturnType<typeof useLiveCaseStream>["status"]
  isTyping: boolean
  customerName: string | null | undefined
  customerPhone: string | null | undefined
  terminal: boolean
  attemptCount: number
  maxAttempts: number
  onQuickReply: (trigger: string, options?: { message?: string; promiseDate?: string }) => void
  onSendMessage: (text: string) => void
}) {
  return (
    <section aria-label="Customer conversation">
      <ConversationHistory
        conversations={conversations}
        liveMessages={liveMessages}
        liveQuickReplies={liveQuickReplies}
        liveStatus={liveStatus}
        isTyping={isTyping}
        customerName={customerName}
        customerPhone={customerPhone}
        hideHeader={false}
        onQuickReply={onQuickReply}
        onSendMessage={onSendMessage}
        quickRepliesDisabled={terminal}
        attemptCount={attemptCount}
        maxAttempts={maxAttempts}
        currentLanguage="en"
      />
    </section>
  )
}

// ═══════════════════════════════════════════════════════════════
// 5. RIGHT COLUMN — AGENT THOUGHT STREAM (accordion)
// ═══════════════════════════════════════════════════════════════

function SectionHeader({
  icon,
  title,
  badge,
  action,
}: {
  icon: ReactNode
  title: string
  badge?: string
  action?: ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-md border border-edge bg-panel-2 text-ink-muted">
          {icon}
        </span>
        <h3 className="text-[12px] font-semibold text-ink">{title}</h3>
      </div>
      {badge ? (
        <span className="font-mono text-[10px] text-ink-faint">{badge}</span>
      ) : action}
    </div>
  )
}

function ThoughtStreamCard({
  detail,
  liveSteps,
  onOpen,
}: {
  detail: RecoveryCaseDetail
  liveSteps: ReturnType<typeof useLiveCaseStream>["liveSteps"]
  onOpen: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <section className="card-sheen rounded-xl" aria-label="Agent thought stream">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 p-4 text-left transition-colors hover:bg-white/[0.02]"
        aria-expanded={open}
      >
        <SectionHeader
          icon={<Cpu className="h-3.5 w-3.5" aria-hidden="true" />}
          title="Agent Thought Stream"
          badge={`${(detail.agent_steps?.length ?? 0) + liveSteps.length} steps`}
        />
        <span
          className={`text-ink-faint transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </span>
      </button>
      {open && (
        <div className="border-t border-edge p-4">
          <AgentThoughtStream persisted={detail.agent_steps} live={liveSteps} collapsed={false} />
        </div>
      )}
      <div className="border-t border-edge px-4 py-2.5">
        <button
          type="button"
          onClick={onOpen}
          className="text-[11px] font-medium text-royal transition-colors hover:text-ink"
        >
          Open full trace →
        </button>
      </div>
    </section>
  )
}

// ═══════════════════════════════════════════════════════════════
// 6. RIGHT COLUMN — DIAGNOSTIC & POLICY COMPLIANCE
// ═══════════════════════════════════════════════════════════════

function KVRow({
  label,
  value,
  mono = false,
  valueClassName = "text-ink",
}: {
  label: string
  value: ReactNode
  mono?: boolean
  valueClassName?: string
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-[11px] text-ink-muted">{label}</dt>
      <dd className={`min-w-0 truncate text-right text-[12px] font-medium ${mono ? "font-mono tabular-nums" : ""} ${valueClassName}`}>
        {value}
      </dd>
    </div>
  )
}

function DiagnosticsCard({
  detail,
  schedule,
}: {
  detail: RecoveryCaseDetail
  schedule: CaseSchedule | null
}) {
  const next = schedule?.next_action
  return (
    <section className="card-sheen rounded-xl" aria-label="Diagnostics and policy compliance">
      <div className="p-4">
        <SectionHeader
          icon={<ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />}
          title="Diagnostic & Policy Compliance"
          badge={detail.risk_level ? `Risk: ${detail.risk_level}` : undefined}
        />

        <dl className="mt-4 space-y-2.5">
          <KVRow label="Gateway" value={<span className="font-mono">{detail.source || "Razorpay"}</span>} />
          <KVRow
            label="Failure reason"
            value={detail.failure_reason ? (
              <span className="inline-flex items-center gap-1 text-amber-400">
                <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                {detail.failure_reason.replace(/_/g, " ")}
              </span>
            ) : "—"}
          />
          <KVRow
            label="Risk level"
            value={
              <span className={`font-mono ${detail.risk_level === "HIGH" ? "text-danger" : detail.risk_level === "MEDIUM" ? "text-amber-400" : "text-emerald-400"}`}>
                {detail.risk_level || "—"}
              </span>
            }
          />
          <KVRow
            label="Sentiment"
            value={`${String(detail.extra_data?.sentiment ?? "Neutral")}`}
            mono
            valueClassName="text-ink-muted"
          />
          <KVRow
            label="Event"
            value={<span className="font-mono">{detail.event_type || "payment.failed"}</span>}
            valueClassName="text-danger"
          />
          <KVRow
            label="Next action"
            value={
              next ? (
                <span className="inline-flex items-center gap-1.5">
                  <span className="capitalize">{next.action_type.replace(/_/g, " ")}</span>
                  <span className="rounded-md border border-royal/25 bg-royal-soft px-1.5 py-0.5 font-mono text-[10px] font-semibold text-royal">
                    {next.due ? "Due now" : countdown(next.scheduled_for)}
                  </span>
                </span>
              ) : (
                "—"
              )
            }
          />
        </dl>
      </div>
    </section>
  )
}

// ═══════════════════════════════════════════════════════════════
// 7. RIGHT COLUMN — AUDIT LOG & ACTIONS
// ═══════════════════════════════════════════════════════════════

function AuditLogCard({
  policyTrace,
  promises,
  schedule,
  terminal,
  isRecovered,
  generating,
  running,
  onSimulate,
  onRunScheduler,
  onOpenAudit,
  onOpenCompliance,
}: {
  policyTrace: PolicyTrace | null
  promises: PaymentPromise[]
  schedule: CaseSchedule | null
  terminal: boolean
  isRecovered: boolean
  generating: boolean
  running: boolean
  onSimulate: (trigger: string) => void
  onRunScheduler: () => void
  onOpenAudit: () => void
  onOpenCompliance: () => void
}) {
  const activePromise = promises.find((p) => p.status.toUpperCase() === "ACTIVE")
  const fulfilledPromise = promises.find((p) => p.status.toUpperCase() === "FULFILLED")
  const nodes = policyTrace?.chain ?? []

  const actionButtons = [
    { icon: <CreditCard className="h-3.5 w-3.5" aria-hidden="true" />, label: "Pay Now", trigger: "pay_now", c: "border-emerald-500/25 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/15" },
    { icon: <CalendarCheck className="h-3.5 w-3.5" aria-hidden="true" />, label: "Promise", trigger: "promise", c: "border-royal/25 bg-royal-soft text-royal hover:bg-royal/15" },
    { icon: <Boxes className="h-3.5 w-3.5" aria-hidden="true" />, label: "Split 2", trigger: "installments", c: "border-edge bg-panel-2 text-ink-muted hover:bg-elevated hover:text-ink" },
    { icon: <Hand className="h-3.5 w-3.5" aria-hidden="true" />, label: "Split 4", trigger: "split_4", c: "border-edge bg-panel-2 text-ink-muted hover:bg-elevated hover:text-ink" },
  ]

  return (
    <section className="card-sheen rounded-xl" aria-label="Audit log and actions">
      <div className="p-4">
        <div className="flex items-center justify-between">
          <SectionHeader
            icon={<ScrollText className="h-3.5 w-3.5" aria-hidden="true" />}
            title="Audit Log & Actions"
          />
          <button
            type="button"
            onClick={onOpenAudit}
            className="text-[11px] font-medium text-royal transition-colors hover:text-ink"
          >
            View all →
          </button>
        </div>

        {/* Active promise / next action banner */}
        {!terminal && (activePromise || schedule?.next_action) && (
          <div className="mt-3 flex flex-col gap-2">
            {activePromise && (
              <div className="flex items-center justify-between rounded-lg border border-royal/20 bg-royal-soft px-3 py-2">
                <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-royal">
                  <CalendarCheck className="h-3.5 w-3.5" aria-hidden="true" />
                  Active promise
                </span>
                <span className="font-mono text-[11px] text-ink-muted">{fmt(activePromise.amount_promised)}</span>
              </div>
            )}
            {isRecovered && fulfilledPromise && (
              <div className="flex items-center justify-between rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 py-2">
                <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                  Promise fulfilled
                </span>
                <span className="font-mono text-[11px] text-ink-muted">
                  {fmt(fulfilledPromise.fulfilled_amount || fulfilledPromise.amount_promised)}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Simulate actions */}
        {!terminal && (
          <div className="mt-3 grid grid-cols-2 gap-1.5">
            {actionButtons.map((a) => (
              <button
                key={a.trigger}
                type="button"
                onClick={() => onSimulate(a.trigger)}
                disabled={generating}
                className={`inline-flex items-center justify-start gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-medium transition-colors disabled:opacity-40 ${a.c}`}
              >
                {a.icon}
                {a.label}
              </button>
            ))}
          </div>
        )}

        {/* Chronological feed */}
        <div className="mt-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-faint">
            Recent activity
          </p>
          {nodes.length > 0 ? (
            <ol className="relative mt-2 space-y-2.5 border-l border-white/[0.07] pl-3">
              {nodes.slice(-6).reverse().map((node) => (
                <li key={node.id} className="relative">
                  <span
                    className={`absolute -left-[1.19rem] top-1.5 h-1.5 w-1.5 rounded-full ${
                      node.layer === "action"
                        ? "bg-emerald-400"
                        : node.layer === "policy"
                          ? "bg-royal"
                          : node.layer === "ai_judgment"
                            ? "bg-violet-400"
                            : "bg-ink-faint"
                    }`}
                    aria-hidden="true"
                  />
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-[11px] text-ink-muted">
                      {node.event_type.replace(/_/g, " ")}
                    </span>
                    <span className="shrink-0 font-mono text-[10px] text-ink-faint">
                      {fmtTime(node.timestamp)}
                    </span>
                  </div>
                  {node.result && (
                    <span className="mt-0.5 inline-flex items-center gap-1 text-[10px] text-ink-faint">
                      <CornerDownRight className="h-2.5 w-2.5" aria-hidden="true" />
                      {node.result}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-2 text-[11px] text-ink-faint">No audit events yet.</p>
          )}
        </div>
      </div>

      {/* Footer actions */}
      <div className="grid grid-cols-3 gap-px border-t border-edge bg-edge">
        {!terminal && (
          <button
            type="button"
            onClick={onRunScheduler}
            disabled={running}
            className="inline-flex items-center justify-center gap-1.5 bg-panel px-3 py-2.5 text-[11px] font-medium text-ink-muted transition-colors hover:bg-elevated hover:text-ink disabled:opacity-40"
          >
            <Zap className="h-3.5 w-3.5" aria-hidden="true" />
            {running ? "Running…" : "Run Scheduler"}
          </button>
        )}
        <button
          type="button"
          onClick={onOpenAudit}
          className="inline-flex items-center justify-center gap-1.5 bg-panel px-3 py-2.5 text-[11px] font-medium text-royal transition-colors hover:bg-elevated"
        >
          <ScrollText className="h-3.5 w-3.5" aria-hidden="true" />
          Audit Trail
        </button>
        <button
          type="button"
          onClick={onOpenCompliance}
          className="inline-flex items-center justify-center gap-1.5 bg-panel px-3 py-2.5 text-[11px] font-medium text-royal transition-colors hover:bg-elevated"
        >
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
          Compliance
        </button>
      </div>
    </section>
  )
}

// ═══════════════════════════════════════════════════════════════
// LIVE ACTIVITY FEED
// ═══════════════════════════════════════════════════════════════

const EVENT_META: Record<string, { label: string; tint: string; icon: ReactNode }> = {
  promise_created:        { label: "Promise", tint: "border-royal/25 bg-royal-soft text-royal", icon: <CalendarCheck className="h-2.5 w-2.5" /> },
  reminder_sent:          { label: "Reminder", tint: "border-amber-500/25 bg-amber-500/10 text-amber-400", icon: <Clock className="h-2.5 w-2.5" /> },
  case_status_changed:    { label: "Status", tint: "border-indigo-500/25 bg-indigo-500/10 text-indigo-400", icon: <RefreshCw className="h-2.5 w-2.5" /> },
  payment_captured:       { label: "Payment", tint: "border-emerald-500/25 bg-emerald-500/10 text-emerald-400", icon: <CreditCard className="h-2.5 w-2.5" /> },
  recovery_completed:     { label: "Recovered", tint: "border-emerald-500/30 bg-emerald-500/15 text-emerald-400", icon: <CheckCircle2 className="h-2.5 w-2.5" /> },
  scheduled_action_created: { label: "Scheduled", tint: "border-violet-500/25 bg-violet-500/10 text-violet-400", icon: <Calendar className="h-2.5 w-2.5" /> },
  scheduled_action_cancelled: { label: "Stopped", tint: "border-danger/25 bg-danger-soft text-danger", icon: <Ban className="h-2.5 w-2.5" /> },
  order_paid:             { label: "Paid", tint: "border-cyan-500/25 bg-cyan-500/10 text-cyan-400", icon: <Zap className="h-2.5 w-2.5" /> },
}

function LiveFeed({ events }: { events: LiveCaseEvent[] }) {
  if (!events.length) return null
  const byKey = Object.fromEntries(Object.entries(EVENT_META).map(([k, v]) => [k.toLowerCase(), v]))
  return (
    <div className="flex flex-wrap gap-1">
      {events.map((ev, i) => {
        const m = byKey[ev.event_type.toLowerCase()] || { label: ev.event_type.replace(/_/g, " "), tint: "border-edge bg-panel-2 text-ink-faint", icon: <Activity className="h-2.5 w-2.5" /> }
        return (
          <span key={`${ev.event_type}-${i}`} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${m.tint}`} title={fmtTimeFull(ev.occurred_at)}>
            {m.icon}{m.label}
            {ev.occurred_at && <span className="ml-0.5 font-mono opacity-60">{fmtTime(ev.occurred_at)}</span>}
          </span>
        )
      })}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// BANNERS
// ═══════════════════════════════════════════════════════════════

function StoppedBanner() {
  return (
    <div className="rounded-xl border border-danger/20 bg-danger-soft p-4">
      <div className="flex items-center gap-3">
        <Ban className="h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
        <div>
          <span className="text-[13px] font-semibold text-danger">Recovery stopped</span>
          <span className="ml-2 text-[12px] text-danger/70">Customer opted out · no further outreach</span>
        </div>
      </div>
      <p className="mt-1.5 text-[11px] text-danger/80">
        All scheduled actions cancelled. No payment links, reminders, or emails will be sent.
      </p>
    </div>
  )
}

function RecoveredBanner({ detail }: { detail: RecoveryCaseDetail }) {
  return (
    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] p-4">
      <div className="flex items-center gap-3">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
        <div>
          <span className="text-[13px] font-semibold text-emerald-400">Payment recovered</span>
          <span className="ml-2 text-[12px] text-emerald-400/70">
            {fmt(detail.recovered_amount)} verified captured
          </span>
        </div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-emerald-400/80">
        <span>Remaining {fmt(detail.remaining_amount)}</span>
        <span>No further outreach</span>
        <span>Case closed</span>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════

export default function RecoveryCasePage() {
  const { caseId } = useParams<{ caseId: string }>()
  const [detail, setDetail] = useState<RecoveryCaseDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [promises, setPromises] = useState<PaymentPromise[]>([])
  const [policyTrace, setPolicyTrace] = useState<PolicyTrace | null>(null)
  const [schedule, setSchedule] = useState<CaseSchedule | null>(null)
  const [emails, setEmails] = useState<SentEmail[]>([])

  const [showPolicyTrace, setShowPolicyTrace] = useState(false)
  const [showCompliance, setShowCompliance] = useState(false)
  const [showAuditTrail, setShowAuditTrail] = useState(false)
  const [running, setRunning] = useState(false)
  const [generating, setGenerating] = useState(false)

  const { liveMessages, liveCaseEvents, liveSteps, isTyping, caseStateUpdate, status, liveQuickReplies } = useLiveCaseStream(caseId)

  useEffect(() => {
    if (!caseId) return
    setLoading(true)
    fetchRecoveryCaseDetail(caseId, { bypass: true })
      .then(setDetail)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [caseId])

  useEffect(() => {
    if (!caseId) return
    fetchCaseConversations(caseId).then(setConversations).catch(console.error)
    fetchCasePromises(caseId).then(setPromises).catch(console.error)
    fetchCasePolicyTrace(caseId).then(setPolicyTrace).catch(console.error)
    fetchCaseSchedule(caseId).then(setSchedule).catch(console.error)
    fetchCaseEmails(caseId).then(setEmails).catch(console.error)
  }, [caseId])

  const refreshAll = useCallback((bypass: boolean) => {
    if (!caseId) return
    fetchRecoveryCaseDetail(caseId, { bypass }).then(setDetail).catch(console.error)
    fetchCaseConversations(caseId).then(setConversations).catch(console.error)
    fetchCasePromises(caseId).then(setPromises).catch(console.error)
    fetchCasePolicyTrace(caseId).then(setPolicyTrace).catch(console.error)
    fetchCaseSchedule(caseId).then(setSchedule).catch(console.error)
    fetchCaseEmails(caseId).then(setEmails).catch(console.error)
  }, [caseId])

  useEffect(() => { if (status === "open") refreshAll(false) }, [status, refreshAll])

  useEffect(() => {
    if (caseStateUpdate) refreshAll(true)
  }, [caseStateUpdate, refreshAll])

  const evCount = useRef(0)
  const msgCount = useRef(0)
  useEffect(() => {
    if (liveCaseEvents.length === evCount.current && liveMessages.length === msgCount.current) return
    evCount.current = liveCaseEvents.length
    msgCount.current = liveMessages.length
    const id = setTimeout(() => refreshAll(true), 350)
    return () => clearTimeout(id)
  }, [liveCaseEvents, liveMessages, refreshAll])

  const runNow = async () => {
    setRunning(true)
    try { await runAutonomousScheduler(); if (caseId) { const f = await fetchCaseSchedule(caseId); setSchedule(f) } }
    catch { /* non-fatal */ } finally { setRunning(false) }
  }

  const handleGenerateEmail = async () => {
    if (!caseId) return
    setGenerating(true)
    try {
      await generateCaseEmail(caseId)
      const f = await fetchCaseEmails(caseId)
      setEmails(f)
    } catch { /* non-fatal */ } finally { setGenerating(false) }
  }

  const simulate = async (trigger: string, options?: { message?: string; promiseDate?: string }) => {
    if (!caseId) return
    setGenerating(true)
    try {
      await simulateCustomerMessage(caseId, trigger, options?.message, { promiseDate: options?.promiseDate })
      refreshAll(true)
    } catch { /* non-fatal */ } finally { setGenerating(false) }
  }

  const handleFreeFormSend = useCallback(async (text: string) => {
    if (!caseId) return
    setGenerating(true)
    try {
      await simulateCustomerMessage(caseId, "custom", text)
      refreshAll(true)
    } catch { /* non-fatal */ } finally { setGenerating(false) }
  }, [caseId, refreshAll])

  if (loading) return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center bg-canvas">
      <div className="h-7 w-7 animate-spin rounded-full border-2 border-edge border-t-royal" />
      <span className="mt-3 text-xs text-ink-muted">Loading case…</span>
    </div>
  )

  if (error || !detail) return (
    <div className="flex min-h-[60vh] items-center justify-center bg-canvas">
      <div className="rounded-xl border border-danger/20 bg-danger-soft p-6 text-center">
        <p className="text-sm font-semibold text-danger">Case not found</p>
        <p className="mt-1 text-xs text-ink-faint">{error || "Invalid ID"}</p>
        <Link to="/dashboard" className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-edge bg-panel px-3 py-1.5 text-xs text-ink-muted transition-colors hover:bg-elevated hover:text-ink">
          <ArrowLeft className="h-3 w-3" />Dashboard
        </Link>
      </div>
    </div>
  )

  const terminal = ["RECOVERED", "LOST", "STOPPED"].includes(detail.status)
  const isRecovered = detail.status === "RECOVERED"
  const pipelineStage = detail.recovery_stage || stageFromStatus(detail.status)

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <div className="mx-auto max-w-[1400px]">
        <div className="pt-6">
          <HeaderBar detail={detail} />
        </div>

        {/* Key metrics bar */}
        <div className="mt-6">
          <MetricsBar detail={detail} />
        </div>

        {/* Banners */}
        {(detail.status === "STOPPED" || detail.status === "RECOVERED") && (
          <div className="mt-3">
            {detail.status === "STOPPED" && <StoppedBanner />}
            {detail.status === "RECOVERED" && <RecoveredBanner detail={detail} />}
          </div>
        )}

        {/* Two-column layout */}
        <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,60%)_minmax(0,40%)]">
          {/* ── LEFT COLUMN (60%) ── */}
          <div className="flex min-w-0 flex-col gap-5">
            <RecoveryStepper current={pipelineStage} />

            <ConversationPanel
              conversations={conversations}
              liveMessages={liveMessages}
              liveQuickReplies={liveQuickReplies}
              liveStatus={status}
              isTyping={isTyping}
              customerName={detail.customer_name}
              customerPhone={detail.customer_phone}
              terminal={terminal}
              attemptCount={detail.attempt_count}
              maxAttempts={detail.max_attempts}
              onQuickReply={simulate}
              onSendMessage={handleFreeFormSend}
            />

            {liveCaseEvents.length > 0 && (
              <div className="rounded-xl border border-edge bg-panel px-5 py-2.5">
                <LiveFeed events={liveCaseEvents} />
              </div>
            )}
          </div>

          {/* ── RIGHT COLUMN (40%) ── */}
          <div className="flex flex-col gap-5 lg:sticky lg:top-6 lg:self-start lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto lg:scrollbar-thin lg:scrollbar-thumb-slate-800 lg:scrollbar-track-transparent">
            <ThoughtStreamCard
              detail={detail}
              liveSteps={liveSteps}
              onOpen={() => setShowPolicyTrace(true)}
            />

            <DiagnosticsCard detail={detail} schedule={schedule} />

            <AuditLogCard
              policyTrace={policyTrace}
              promises={promises}
              schedule={schedule}
              terminal={terminal}
              isRecovered={isRecovered}
              generating={generating}
              running={running}
              onSimulate={(t) => simulate(t)}
              onRunScheduler={runNow}
              onOpenAudit={() => setShowAuditTrail(true)}
              onOpenCompliance={() => setShowCompliance(true)}
            />

            <section className="card-sheen rounded-xl" aria-label="Sent emails">
              <div className="flex items-center justify-between border-b border-edge px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <Mail className="h-3.5 w-3.5 text-blue-400" aria-hidden="true" />
                  <h2 className="text-[12px] font-medium text-ink">Emails</h2>
                  {emails.length > 0 && (
                    <span className="rounded-full bg-blue-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-blue-300">
                      {emails.length}
                    </span>
                  )}
                </div>
              </div>
              <div className="max-h-72 overflow-y-auto p-4 scrollbar-thin scrollbar-thumb-slate-800">
                <EmailHistory
                  emails={emails}
                  onGenerateEmail={handleGenerateEmail}
                />
              </div>
            </section>

            {!terminal && detail.root_cause && (
              <div className="flex items-start gap-2.5 rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-3.5">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" aria-hidden="true" />
                <div>
                  <p className="text-[11px] font-medium text-ink">Root cause</p>
                  <p className="text-[11px] text-amber-400/80">{detail.root_cause.replace(/_/g, " ")}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {showPolicyTrace && caseId && (
        <PolicyTraceInspector caseId={caseId} onClose={() => setShowPolicyTrace(false)} />
      )}

      <AuditEventDrawer
        open={showAuditTrail}
        onClose={() => setShowAuditTrail(false)}
        caseId={caseId || ""}
        rootCause={detail?.root_cause}
      />

      <ComplianceDrawer open={showCompliance} onClose={() => setShowCompliance(false)} detail={detail} />
    </div>
  )
}
