import { useState } from "react"
import {
  MessageSquare,
  ShieldCheck,
  TrendingUp,
  RotateCw,
  Zap,
  ChevronRight,
  Check,
  X,
  User,
} from "lucide-react"
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { formatINR } from "../lib/format"

/**
 * Live Demo Sandbox — a 3-column interactive recovery console.
 *
 *  Left:  Live WhatsApp Audit Feed
 *  Center: AI Diagnosis & Guardrail Reasoning
 *  Right: Recovery Metrics & Settlement Pipeline
 *
 * Purely presentational demo state; real chats stream over WhatsApp, so the
 * left panel is a read-only sync view with a manual demo trigger.
 */

const CUSTOMER = {
  name: "Devanand Verma",
  phone: "+91 98765 43210",
}

interface ChatMessage {
  id: number
  direction: "inbound" | "outbound"
  text: string
  card?: "split" | "razorpay" | null
  time?: string
}

const SEED_CONVERSATION: ChatMessage[] = [
  {
    id: 1,
    direction: "inbound",
    text: "Payment failed kyun hua? WhatsApp se pay karne ki koshish ki thi.",
    card: null,
  },
  {
    id: 2,
    direction: "outbound",
    text: "Sorry for the trouble Devanand ji. Your UPI of ₹11,999 was declined — the gateway flagged a transaction limit. I can split it into 2 easy parts.",
    card: "split",
  },
  {
    id: 3,
    direction: "inbound",
    text: "Haan theek hai, dono part kar dete hain. First aaj, second kal.",
    card: null,
  },
]

const FOLLOW_UP: ChatMessage = {
  id: 4,
  direction: "outbound",
  text: "Done! Part 1 confirmed. Part 2 is scheduled for +24h. Settlement link below — tap to complete. 🙏",
  card: "razorpay",
}

const MINI_TREND = [
  { day: "Mon", amount: 214000 },
  { day: "Tue", amount: 286000 },
  { day: "Wed", amount: 231000 },
  { day: "Thu", amount: 318000 },
  { day: "Fri", amount: 297000 },
  { day: "Sat", amount: 341000 },
  { day: "Today", amount: 312000 },
]

const SETTLEMENTS = [
  { id: 1, name: "Shobha Kulkarni", amount: "₹4,999", channel: "WhatsApp UPI" },
  { id: 2, name: "Ramesh Patil", amount: "₹7,200", channel: "Razorpay Link" },
  { id: 3, name: "Kavita Nambiar", amount: "₹11,999", channel: "EMI Part 2" },
  { id: 4, name: "Arjun Deshmukh", amount: "₹3,850", channel: "WhatsApp UPI" },
]

export default function SimulationPage() {
  const [messages, setMessages] = useState<ChatMessage[]>(SEED_CONVERSATION)
  const [syncing, setSyncing] = useState(true)

  const loadLiveScenario = () => {
    setMessages(SEED_CONVERSATION)
    setSyncing(true)
  }

  const simulateReply = () => {
    setSyncing(false)
    setMessages((prev) =>
      prev.some((m) => m.card === "razorpay") ? prev : [...prev, FOLLOW_UP],
    )
    setSyncing(true)
  }

  return (
    <div className="min-h-screen bg-canvas text-slate-100">
      {/* Top bar */}
      <header className="border-b border-edge bg-panel">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-soft text-accent">
              <Zap className="h-4 w-4" />
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-tight text-white">
                Fail2Pay
              </h1>
              <p className="text-[11px] text-slate-500">
                Autonomous Payment Recovery Engine
              </p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent-soft px-3 py-1 text-[11px] font-medium text-accent">
            <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
            Live Sync Active
          </span>
        </div>
      </header>

      {/* 3-column console */}
      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-4 p-4 lg:grid-cols-12">
        {/* Column 1 — Live WhatsApp Audit Feed */}
        <section className="flex flex-col overflow-hidden rounded-xl border border-edge bg-panel lg:col-span-4">
        <PanelHeader
          title="WhatsApp Stream"
          subtitle={`${CUSTOMER.phone} · ${CUSTOMER.name}`}
          action={
            <button
              onClick={loadLiveScenario}
              className="inline-flex items-center gap-1 rounded-md border border-edge bg-panel-2 px-2 py-1 text-[11px] font-medium text-slate-300 transition-colors hover:bg-elevated"
            >
              <Zap className="h-3 w-3 text-amber-400" />
              Load Live Scenario
            </button>
          }
        />

        <div className="flex-1 space-y-3 overflow-y-auto p-3">
            {messages.map((m) => (
              <ChatBubble key={m.id} message={m} />
            ))}
          </div>

          <div className="border-t border-edge bg-panel p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-[11px] text-slate-500">
                <span className={`h-2 w-2 rounded-full ${syncing ? "bg-accent" : "bg-slate-600"}`} />
                {syncing
                  ? "Listening for incoming WhatsApp webhooks..."
                  : "Processing inbound webhook..."}
              </div>
              <button
                onClick={simulateReply}
                className="inline-flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent-soft px-2.5 py-1.5 text-[11px] font-medium text-accent hover:bg-accent/20"
              >
                <MessageSquare className="h-3 w-3" />
                Simulate Customer Reply
              </button>
            </div>
          </div>
        </section>

        {/* Column 2 — AI Diagnosis & Guardrails */}
        <section className="flex flex-col overflow-hidden rounded-xl border border-edge bg-panel lg:col-span-4">
          <PanelHeader
            title="Autonomous Reasoning & Guardrails"
            subtitle="Real-time state machine & deterministic execution"
            highlight
          />

          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {/* Failure ingestion */}
            <DiagnosisBlock
              label="Failure Ingestion"
              icon={<MessageSquare className="h-3.5 w-3.5 text-rose-400" />}
            >
              <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 p-2.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-mono text-rose-300">
                    GATEWAY_CODE: TRANSACTION_LIMIT_EXCEEDED
                  </span>
                  <span className="text-slate-500">(Razorpay UPI)</span>
                </div>
                <div className="mt-1 text-[11px] text-slate-400">
                  Failed amount: <span className="font-semibold text-slate-200">₹11,999</span> · source: webhook ingest
                </div>
              </div>
            </DiagnosisBlock>

            {/* Intent classification */}
            <DiagnosisBlock
              label="Intent Classification"
              icon={<User className="h-3.5 w-3.5 text-cyan-400" />}
            >
              <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-2.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-400">Sentiment</span>
                  <span className="font-mono text-cyan-300">INTENT: SPLIT_PAYMENT_REQUESTED</span>
                </div>
                <div className="mt-1 text-[11px] text-slate-500">
                  Customer willing to pay — requested installments. Confidence 0.94
                </div>
              </div>
            </DiagnosisBlock>

            {/* Guardrails as code */}
            <DiagnosisBlock
              label="Deterministic Policy Checks · Guardrails as Code"
              icon={<ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />}
            >
              <ul className="space-y-2">
                <Guardrail ok label="Attempt ceiling" detail="1 / 5 max attempts" />
                <Guardrail ok label="Discount check" detail="0% hallucinated discount enforced" />
                <Guardrail ok label="Dispute status" detail="No chargeback active" />
                <Guardrail ok label="Tone check" detail="Polite Hinglish · threshold (0.94)" />
              </ul>
            </DiagnosisBlock>

            {/* Action plan */}
            <DiagnosisBlock
              label="Generated Action Plan"
              icon={<ChevronRight className="h-3.5 w-3.5 text-amber-400" />}
            >
              <div className="space-y-2">
                <PlanRow
                  title="Part 1 · due now"
                  amount="₹5,999.50"
                  status="confirmed"
                  border="border-emerald-500/20"
                  dot="bg-emerald-400"
                />
                <PlanRow
                  title="Part 2 · scheduled +24h"
                  amount="₹5,999.50"
                  status="queued"
                  border="border-slate-700"
                  dot="bg-slate-500"
                />
              </div>
            </DiagnosisBlock>
          </div>
        </section>

        {/* Column 3 — Recovery Metrics */}
        <section className="flex flex-col overflow-hidden rounded-xl border border-edge bg-panel lg:col-span-4">
          <PanelHeader
            title="Recovery Dashboard"
            subtitle="Live settlement pipeline"
            action={
              <button
                onClick={loadLiveScenario}
                className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-slate-700 text-slate-400 hover:bg-slate-800"
              >
                <RotateCw className="h-3.5 w-3.5" />
              </button>
            }
          />

          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {/* KPI micro-cards */}
            <div className="grid grid-cols-3 gap-2.5">
              <KpiCard label="Cases Engaged" value="23" note="Active" tone="text-slate-100" />
              <KpiCard label="Yield Rate" value="49.3%" note="Settled" tone="text-emerald-400" />
              <KpiCard label="Recovered Revenue" value="₹3.12 L" note="Captured" tone="text-emerald-400" />
            </div>

            {/* Mini trend chart */}
            <div className="rounded-lg border border-edge bg-panel-2 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-300">
                  <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
                  Recovered Volume · last 7 days
                </span>
              </div>
              <div className="h-24">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={MINI_TREND} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                    <defs>
                      <linearGradient id="miniSettled" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="#10b981" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <XAxis
                      dataKey="day"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "#64748b", fontSize: 9 }}
                      interval="preserveStartEnd"
                    />
                    <YAxis hide domain={["dataMin - 20000", "dataMax + 20000"]} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#0F172A",
                        border: "1px solid #1E293B",
                        borderRadius: 8,
                        fontSize: 11,
                        color: "#e2e8f0",
                      }}
                      labelStyle={{ color: "#94a3b8" }}
                      formatter={(v) => [formatINR(Number(v)), "Settled"]}
                    />
                    <Area
                      type="monotone"
                      dataKey="amount"
                      stroke="#10b981"
                      strokeWidth={2}
                      fill="url(#miniSettled)"
                      dot={false}
                      activeDot={{ r: 3 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Settlement stream */}
            <div>
              <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-slate-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400" />
                Recent Verified Settlements
              </div>
              <div className="space-y-2">
                {SETTLEMENTS.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-center justify-between rounded-lg border border-edge bg-panel-2 px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium text-slate-200">{s.name}</p>
                      <p className="text-[10px] text-slate-500">{s.channel}</p>
                    </div>
                    <span className="ml-2 text-xs font-semibold text-emerald-400">{s.amount}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

/* ---------- Shared building blocks ---------- */

function PanelHeader({
  title,
  subtitle,
  action,
  highlight,
}: {
  title: string
  subtitle?: string
  action?: React.ReactNode
  highlight?: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-edge px-4 py-3">
      <div>
        <h2 className="inline-flex items-center gap-2 text-sm font-semibold tracking-tight text-white">
          {highlight && <span className="h-1.5 w-1.5 rounded-full bg-accent" />}
          {title}
        </h2>
        {subtitle && <p className="mt-0.5 text-[11px] text-slate-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const isInbound = message.direction === "inbound"
  return (
    <div className={`flex ${isInbound ? "justify-start" : "justify-end"}`}>
      <div
        className={`max-w-[85%] px-3 py-2 text-[13px] leading-relaxed ${
          isInbound
            ? "rounded-2xl rounded-tl-sm bg-slate-800 text-slate-200"
            : "rounded-2xl rounded-tr-sm border border-emerald-500/30 bg-slate-900 text-slate-100"
        }`}
      >
        <p className="whitespace-pre-wrap">{message.text}</p>

        {message.card === "split" && (
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            <div className="rounded-lg border border-edge bg-panel-2 p-2 text-center">
              <p className="text-[10px] text-slate-500">Part 1 · Today</p>
              <p className="text-sm font-bold text-emerald-400">₹5,999.50</p>
            </div>
            <div className="rounded-lg border border-edge bg-panel-2 p-2 text-center">
              <p className="text-[10px] text-slate-500">Part 2 · +24h</p>
              <p className="text-sm font-bold text-emerald-400">₹5,999.50</p>
            </div>
          </div>
        )}

        {message.card === "razorpay" && (
          <div className="mt-2 rounded-lg border border-emerald-500/30 bg-slate-800/60 p-2.5">
            <p className="text-[10px] text-slate-500">Razorpay Settlement</p>
            <p className="mt-0.5 text-sm font-semibold text-emerald-400">₹5,999.50 due</p>
            <button className="mt-2 w-full rounded-md bg-emerald-600 py-1.5 text-center text-xs font-semibold text-white hover:bg-emerald-500">
              Pay Now
            </button>
          </div>
        )}

        <p className="mt-1 text-right text-[9px] text-slate-600">
          {message.time ?? (isInbound ? "customer" : "AI agent")}
        </p>
      </div>
    </div>
  )
}

function DiagnosisBlock({
  label,
  icon,
  children,
}: {
  label: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        {icon}
        <span>{label}</span>
      </div>
      <div>{children}</div>
    </div>
  )
}

function Guardrail({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  return (
    <li className="flex items-center gap-2 rounded-md border border-edge bg-panel-2 px-2.5 py-2">
      {ok ? (
        <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
          <Check className="h-3 w-3" />
        </span>
      ) : (
        <span className="flex h-4 w-4 items-center justify-center rounded-full bg-rose-500/15 text-rose-400">
          <X className="h-3 w-3" />
        </span>
      )}
      <span className="text-xs text-slate-300">{label}</span>
      <span className="ml-auto text-[10px] text-slate-500">{detail}</span>
    </li>
  )
}

function PlanRow({
  title,
  amount,
  status,
  border,
  dot,
}: {
  title: string
  amount: string
  status: string
  border: string
  dot: string
}) {
  return (
    <div className={`flex items-center justify-between rounded-lg border bg-panel-2 p-2.5 ${border}`}>
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${dot}`} />
        <span className="text-xs text-slate-300">{title}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-slate-100">{amount}</span>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-slate-400">
          {status}
        </span>
      </div>
    </div>
  )
}

function KpiCard({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: string
  note: string
  tone: string
}) {
  return (
    <div className={`rounded-lg border border-edge bg-panel-2 p-2.5 text-center`}>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 text-lg font-bold ${tone}`}>{value}</p>
      <p className="mt-0.5 text-[10px] text-slate-600">{note}</p>
    </div>
  )
}
