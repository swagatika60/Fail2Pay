import { useEffect, useState } from "react"
import { useParams, Link } from "react-router-dom"
import {
  Terminal,
  CheckCircle2,
  Clock,
  FileText,
  CalendarCheck,
  CreditCard,
  MessageSquare,
  Mail,
  ShieldAlert,
  Info,
  AlertTriangle,
  RefreshCw,
  Calendar,
  BarChart3,
  XCircle,
  Ban,
  ArrowLeft,
} from "lucide-react"
import type {
  RecoveryCaseDetail,
  PaymentPromise,
  PaymentPlan,
  Conversation,
  SentEmail,
  HardStop,
  RecoveryTimeline as TimelineData,
} from "../types/analytics"
import {
  fetchRecoveryCaseDetail,
  fetchCasePromises,
  fetchCasePaymentPlans,
  fetchCaseConversations,
  fetchCaseEmails,
  fetchCaseHardStops,
  fetchCaseTimeline,
} from "../services/analytics"
import {
  simulateCustomerMessage,
  generateAgentInitial,
  generateCaseEmail,
} from "../services/operations"
import { formatCurrency } from "../components/dashboard/MetricCard"
import PromiseTimeline from "../components/dashboard/PromiseTimeline"
import PaymentPlanView from "../components/dashboard/PaymentPlanView"
import ConversationHistory from "../components/dashboard/ConversationHistory"
import EmailHistory from "../components/dashboard/EmailHistory"
import HardStopLog from "../components/dashboard/HardStopLog"
import RecoveryTimelineView from "../components/dashboard/RecoveryTimeline"
import PolicyTraceInspector from "../components/dashboard/PolicyTraceInspector"
import SimulateMessageControls from "../components/dashboard/SimulateMessageControls"

const STATUS_COLORS: Record<string, string> = {
  AT_RISK: "bg-red-500/20 text-red-400 border-red-500/30",
  RECOVERY_IN_PROGRESS: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  PROMISED: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  SCHEDULED: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  PARTIALLY_RECOVERED: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  RECOVERED: "bg-green-500/20 text-green-400 border-green-500/30",
  LOST: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  STOPPED: "bg-gray-500/20 text-gray-400 border-gray-500/30",
}

const STATUS_ICONS: Record<string, typeof AlertTriangle> = {
  AT_RISK: AlertTriangle,
  RECOVERY_IN_PROGRESS: RefreshCw,
  PROMISED: CalendarCheck,
  SCHEDULED: Calendar,
  PARTIALLY_RECOVERED: BarChart3,
  RECOVERED: CheckCircle2,
  LOST: XCircle,
  STOPPED: Ban,
}

const TABS = [
  { id: "timeline", label: "Timeline", icon: Clock },
  { id: "overview", label: "Details", icon: FileText },
  { id: "promises", label: "Promises", icon: CalendarCheck },
  { id: "plans", label: "Payment Plans", icon: CreditCard },
  { id: "conversation", label: "Conversation", icon: MessageSquare },
  { id: "emails", label: "Emails", icon: Mail },
  { id: "hardstops", label: "Hard Stops", icon: ShieldAlert },
]

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

export default function RecoveryCasePage() {
  const { caseId } = useParams<{ caseId: string }>()
  const [detail, setDetail] = useState<RecoveryCaseDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState("timeline")

  // Tab data
  const [promises, setPromises] = useState<PaymentPromise[]>([])
  const [plans, setPlans] = useState<PaymentPlan[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [emails, setEmails] = useState<SentEmail[]>([])
  const [hardStops, setHardStops] = useState<HardStop[]>([])
  const [timelineData, setTimelineData] = useState<TimelineData | null>(null)
  const [tabLoading, setTabLoading] = useState(false)
  const [showPolicyTrace, setShowPolicyTrace] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [typing, setTyping] = useState(false)

  const refreshConversations = () => {
    if (!caseId) return
    fetchCaseConversations(caseId).then(setConversations).catch(console.error)
  }

  const refreshEmails = () => {
    if (!caseId) return
    fetchCaseEmails(caseId).then(setEmails).catch(console.error)
  }

  const handleQuickReply = async (payloadId: string) => {
    if (!caseId || typing) return
    let trigger = payloadId
    if (payloadId.startsWith("lang:")) {
      const code = payloadId.replace(/^lang:/, "") === "hi" ? "hi" : "en"
      trigger = `language_${code}`
    } else {
      const map: Record<string, string> = {
        pay_now: "pay_link",
        split_emi: "installments",
        activate_plan: "installments",
        split_2: "split_2",
        split_4: "split_4",
      }
      trigger = map[payloadId] || payloadId
    }
    setTyping(true)
    try {
      await simulateCustomerMessage(caseId, trigger)
      refreshConversations()
    } finally {
      setTyping(false)
    }
  }

  const handleGenerateEmail = async () => {
    if (!caseId) return
    try {
      await generateCaseEmail(caseId)
      refreshEmails()
    } catch (err) {
      console.error("Failed to generate email:", err)
    }
  }

  const handleEmailPayNow = async (payCaseId: string) => {
    if (!payCaseId || typing) return
    setTyping(true)
    try {
      await simulateCustomerMessage(payCaseId, "pay_link")
      refreshConversations()
      refreshEmails()
    } catch (err) {
      console.error("Failed to process pay now:", err)
    } finally {
      setTyping(false)
    }
  }

  const startConversation = async () => {
    if (!caseId) return
    try {
      await generateAgentInitial(caseId)
      setReloadKey((k) => k + 1)
      if (activeTab === "conversation") refreshConversations()
      if (activeTab === "emails") refreshEmails()
    } catch (err) {
      console.error("Failed to start conversation:", err)
    }
  }

  // Load case detail
  useEffect(() => {
    if (!caseId) return
    setLoading(true)
    fetchRecoveryCaseDetail(caseId, { bypass: reloadKey > 0 })
      .then(setDetail)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setLoading(false))
  }, [caseId, reloadKey])

  // Load tab data on demand
  useEffect(() => {
    if (!caseId) return
    setTabLoading(true)

    const loadData = async () => {
      try {
        switch (activeTab) {
          case "promises":
            setPromises(await fetchCasePromises(caseId))
            break
          case "plans":
            setPlans(await fetchCasePaymentPlans(caseId))
            break
          case "conversation":
            setConversations(await fetchCaseConversations(caseId))
            break
          case "emails":
            setEmails(await fetchCaseEmails(caseId))
            break
          case "hardstops":
            setHardStops(await fetchCaseHardStops(caseId))
            break
          case "timeline":
            setTimelineData(await fetchCaseTimeline(caseId))
            break
        }
      } catch (err) {
        console.error("Failed to load tab data:", err)
      } finally {
        setTabLoading(false)
      }
    }
    loadData()
  }, [caseId, activeTab])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <div className="flex flex-col items-center gap-4">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
          <p className="text-slate-400">Loading recovery case...</p>
        </div>
      </div>
    )
  }

  if (error || !detail) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <div className="rounded-xl border border-red-800 bg-red-900/20 p-6 text-center">
          <p className="text-lg font-semibold text-red-400">Case not found</p>
          <p className="mt-2 text-sm text-slate-400">{error || "Invalid case ID"}</p>
          <Link
            to="/dashboard"
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-200 hover:bg-slate-700"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  const recoveredPercent =
    detail.original_amount > 0
      ? Math.round((detail.recovered_amount / detail.original_amount) * 100)
      : 0

  // Find stop reason from hard stops or audit trail
  const stopReason = detail.audit_events?.find(
    (ae) =>
      ae.action?.includes("stop") ||
      ae.action?.includes("STOPPED") ||
      ae.entity_type === "hard_stop",
  )

  return (
    <div className="space-y-6 text-slate-100">
      {/* Back link */}
      <div className="mb-4">
        <Link
          to="/cases"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Recovery Cases
        </Link>
      </div>

      {/* Header */}
      <div className="mb-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              Recovery Case
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              {detail.customer_name || "Unknown Customer"}
              {detail.customer_email && ` • ${detail.customer_email}`}
              {detail.customer_phone && ` • ${detail.customer_phone}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowPolicyTrace(true)}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 transition-colors"
            >
              <Terminal className="w-3.5 h-3.5 text-indigo-400" />
              Policy &amp; Decision Trace
            </button>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium ${
                STATUS_COLORS[detail.status] || "bg-slate-700 text-slate-300 border-slate-600"
              }`}
            >
              {(() => {
                const Icon = STATUS_ICONS[detail.status] || Info
                return <Icon className={"w-4 h-4"} />
              })()}
              {detail.status.replace(/_/g, " ")}
            </span>
          </div>
        </div>
      </div>

      {/* Key Metrics Row */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs text-slate-400">Original Amount</p>
          <p className="text-xl font-bold text-slate-100">
            {formatCurrency(detail.original_amount)}
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs text-slate-400">Recovered</p>
          <p className="text-xl font-bold text-green-400">
            {formatCurrency(detail.recovered_amount)}
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs text-slate-400">Remaining</p>
          <p className="text-xl font-bold text-amber-400">
            {formatCurrency(detail.remaining_amount)}
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs text-slate-400">Recovery Rate</p>
          <p className="text-xl font-bold text-emerald-400">{recoveredPercent}%</p>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mb-6 rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="mb-2 flex justify-between text-xs text-slate-400">
          <span>Recovery Progress</span>
          <span>{recoveredPercent}%</span>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-green-500 to-emerald-400 transition-all"
            style={{ width: `${recoveredPercent}%` }}
          />
        </div>
        <div className="mt-2 flex justify-between text-xs text-slate-500">
          <span>{formatCurrency(0)}</span>
          <span>{formatCurrency(detail.original_amount)}</span>
        </div>
      </div>

      {/* Info Cards Row */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-5">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
          <p className="text-[10px] text-slate-500">Risk Level</p>
          <p
            className={`text-sm font-semibold ${
              detail.risk_level === "HIGH"
                ? "text-red-400"
                : detail.risk_level === "MEDIUM"
                  ? "text-yellow-400"
                  : "text-green-400"
            }`}
          >
            {detail.risk_level}
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
          <p className="text-[10px] text-slate-500">Attempts</p>
          <p className="text-sm font-semibold text-slate-200">
            {detail.attempt_count} / {detail.max_attempts}
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
          <p className="text-[10px] text-slate-500">Event Type</p>
          <p className="text-sm font-semibold text-slate-200">
            {detail.event_type || "—"}
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
          <p className="text-[10px] text-slate-500">Source</p>
          <p className="text-sm font-semibold text-slate-200">{detail.source || "—"}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
          <p className="text-[10px] text-slate-500">Created</p>
          <p className="text-sm font-semibold text-slate-200">
            {formatDateTime(detail.created_at)}
          </p>
        </div>
      </div>

      {/* Stop Reason (if stopped) */}
      {detail.status === "STOPPED" && (
        <div className="mb-6 rounded-xl border border-red-500/40 bg-red-500/10 p-4">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-red-400" />
            <div>
              <p className="text-sm font-semibold text-red-400">
                STOPPED (User Opt-Out)
              </p>
              <p className="mt-1 text-xs text-red-300">
                Policy Guardrail: Opt-out detected. All automated outreach and
                retries halted immediately.
              </p>
              {stopReason && (
                <p className="mt-1 text-xs text-slate-400">
                  {stopReason.new_value &&
                    (String(stopReason.new_value.reason ?? "") ||
                      String(stopReason.new_value.stop_condition ?? "") ||
                      stopReason.action)}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Simulate customer reply (only while recovery is active) */}
      {caseId && !["RECOVERED", "LOST", "STOPPED"].includes(detail.status) && (
        <div className="mb-6">
          <SimulateMessageControls
            caseId={caseId}
            amount={detail.original_amount}
            onApplied={() => setReloadKey((k) => k + 1)}
            onTyping={setTyping}
          />
        </div>
      )}

      {/* Tabs */}
      <div className="mb-6 border-b border-slate-800">
        <div className="flex gap-1 overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`whitespace-nowrap rounded-t-lg px-4 py-2.5 text-sm font-medium transition-colors inline-flex items-center gap-2 ${
                activeTab === tab.id
                  ? "border-b-2 border-blue-500 bg-slate-900 text-slate-100"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900/50"
              }`}
            >
              <tab.icon
                className={`w-3.5 h-3.5 ${
                  tab.id === "hardstops" ? "text-rose-400" : ""
                }`}
              />
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      <div className="min-h-[300px]">
        {tabLoading && (
          <div className="flex items-center justify-center py-12">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
          </div>
        )}

        {!tabLoading && activeTab === "timeline" && (
          <RecoveryTimelineView timeline={timelineData} loading={false} />
        )}

        {!tabLoading && activeTab === "overview" && (
          <div className="space-y-6">
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
              <h3 className="mb-4 text-sm font-semibold text-slate-300">
                Case Details
              </h3>
              <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
                <div>
                  <p className="text-xs text-slate-500">Risk Reason</p>
                  <p className="text-slate-200">{detail.risk_reason || "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Failure Reason</p>
                  <p className="text-slate-200">{detail.failure_reason || "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Recovery Started</p>
                  <p className="text-slate-200">
                    {formatDateTime(detail.recovery_started_at)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Deadline</p>
                  <p className="text-slate-200">
                    {formatDateTime(detail.recovery_deadline)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Closed At</p>
                  <p className="text-slate-200">{formatDateTime(detail.closed_at)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Last Updated</p>
                  <p className="text-slate-200">{formatDateTime(detail.updated_at)}</p>
                </div>
              </div>
            </div>

            {/* Audit Trail */}
            {detail.audit_events && detail.audit_events.length > 0 && (
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
                <h3 className="mb-4 text-sm font-semibold text-slate-300">
                  Audit Trail ({detail.audit_events.length} events)
                </h3>
                <div className="max-h-96 space-y-2 overflow-y-auto">
                  {detail.audit_events.map((ae) => (
                    <div
                      key={ae.id}
                      className="rounded-lg bg-slate-800/50 px-4 py-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-slate-300">
                          {ae.action}
                        </span>
                        <span className="text-xs text-slate-500">
                          {formatDateTime(ae.created_at)}
                        </span>
                      </div>
                      {ae.new_value && (
                        <pre className="mt-1 overflow-x-auto text-xs text-slate-400">
                          {JSON.stringify(ae.new_value, null, 2)}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {!tabLoading && activeTab === "promises" && (
          <PromiseTimeline promises={promises} />
        )}

        {!tabLoading && activeTab === "plans" && (
          <PaymentPlanView plans={plans} />
        )}

        {!tabLoading && activeTab === "conversation" && (
          <div className="space-y-3">
            <div className="flex items-center justify-end">
              <button
                onClick={startConversation}
                className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20"
              >
                <MessageSquare className="w-3.5 h-3.5" />
                Start first-touch message
              </button>
            </div>
            <ConversationHistory
              conversations={conversations}
              onQuickReply={handleQuickReply}
              typing={typing}
            />
          </div>
        )}

        {!tabLoading && activeTab === "emails" && (
          <EmailHistory
            emails={emails}
            onGenerateEmail={handleGenerateEmail}
            onPayNow={handleEmailPayNow}
          />
        )}

        {!tabLoading && activeTab === "hardstops" && (
          <HardStopLog hardStops={hardStops} />
        )}
      </div>

      {showPolicyTrace && caseId && (
        <PolicyTraceInspector
          caseId={caseId}
          onClose={() => setShowPolicyTrace(false)}
        />
      )}
    </div>
  )
}
