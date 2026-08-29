import { memo, useMemo } from "react"
import { Link } from "react-router-dom"
import {
  CheckCircle2,
  Clock,
  Zap,
} from "lucide-react"
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { useDashboardStore } from "../hooks/dashboardStore"
import { Card, CardHeader } from "../components/ui/Card"
import { PageHeader } from "../components/ui/PageHeader"
import { StatCard } from "../components/ui/StatCard"
import { EmptyState } from "../components/ui/EmptyState"
import { Skeleton, SkeletonTable } from "../components/ui/Skeleton"
import { StatusBadge } from "../components/ui/Badge"
import { caseMeta } from "../lib/status"
import { formatINR, formatINRFull, formatPercent, formatDate, timeAgo, initials } from "../lib/format"
import type { CSSProperties } from "react"

const TOOLTIP_STYLE: CSSProperties = {
  backgroundColor: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "8px",
  color: "#e2e8f0",
  fontSize: "13px",
}

const CHART_TICK = { fill: "#94a3b8", fontSize: 10.5 }
const CHART_TICK_Y = { fill: "#94a3b8", fontSize: 11 }

const CHANNEL_COLORS: Record<string, string> = {
  whatsapp: "#22d3ee",
  email: "#60a5fa",
  payment_plan: "#a78bfa",
  unknown: "#64748b",
}

const FUNNEL_COLORS: Record<string, string> = {
  "Expected Revenue": "#3b82f6",
  "Entered Recovery": "#f59e0b",
  "Verified Recovered": "#34d399",
  "Still At Risk": "#f87171",
  "Lost Revenue": "#64748b",
}

const OPEN_STATUSES = new Set([
  "AT_RISK",
  "RECOVERY_IN_PROGRESS",
  "PROMISED",
  "SCHEDULED",
  "PARTIALLY_RECOVERED",
])

const RISK_ORDER: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 }

const RISK_BADGES: Record<string, string> = {
  LOW: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  MEDIUM: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  HIGH: "bg-rose-500/10 text-rose-400 border-rose-500/20",
}

export default function DashboardPage() {
  const { map, summary, cases, loading, error, simulatePaymentFailure } =
    useDashboardStore()

  const needsAttention = useMemo(() => {
    return cases
      .filter((c) => OPEN_STATUSES.has(c.status))
      .sort((a, b) => {
        const riskDiff =
          (RISK_ORDER[a.risk_level] ?? 9) - (RISK_ORDER[b.risk_level] ?? 9)
        if (riskDiff !== 0) return riskDiff
        return b.remaining_amount - a.remaining_amount
      })
      .slice(0, 6)
  }, [cases])

  const recentRecovered = useMemo(() => {
    return cases
      .filter((c) => c.status === "RECOVERED")
      .slice()
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
      .slice(0, 5)
  }, [cases])

  const openCaseCount = useMemo(
    () => cases.filter((c) => OPEN_STATUSES.has(c.status)).length,
    [cases],
  )

  const channelData = map?.recovery_by_channel ?? []

  const triggerMockFailureWebhook = () => {
    const base = Math.max(map?.at_risk_revenue ?? 0, 500000)
    const amount = Math.round(base * 0.1) + Math.floor(Math.random() * 300000)
    simulatePaymentFailure(amount)
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
        <SkeletonTable rows={6} />
      </div>
    )
  }

  if (error || !map || !summary) {
    return (
      <div className="rounded-xl border border-red-800 bg-red-900/20 p-6 text-center">
        <p className="text-lg font-semibold text-red-400">Failed to load dashboard</p>
        <p className="mt-2 text-sm text-slate-400">{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        subtitle="Revenue recovery command center — verified money only."
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={triggerMockFailureWebhook}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500 hover:bg-emerald-400 text-slate-950 transition-colors shadow-sm"
            >
              <Zap className="w-3.5 h-3.5 fill-current" />
              Simulate Failure Webhook
            </button>
            <Link
              to="/revenue-map"
              className="rounded-lg bg-slate-800 px-3 py-1.5 text-sm font-medium text-slate-200 hover:bg-slate-700"
            >
              View Revenue Map
            </Link>
          </div>
        }
      />

      {/* KPIs — directly answers the money questions */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        <StatCard
          label="Revenue at Risk"
          value={formatINR(map.at_risk_revenue)}
          sub={`across ${openCaseCount} open cases`}
          tone="danger"
          icon={<svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 17l6-6 4 4 8-8M15 7h6v6" /></svg>}
        />
        <StatCard
          label="Recovered by Fail2Pay"
          value={formatINR(map.recovered_revenue)}
          sub={`${map.payments_count} verified captured payments`}
          tone="success"
          icon={<svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>}
        />
        <StatCard
          label="In Recovery"
          value={formatINR(summary.recovery_in_progress + summary.promised_revenue + summary.scheduled_revenue)}
          sub="attempted but money not yet collected"
          tone="warning"
        />
        <StatCard
          label="Recovery Rate"
          value={formatPercent(map.recovery_rate)}
          sub={`${formatINR(map.attempted_recovery)} engaged`}
          tone="info"
        />
        <StatCard
          label="Avg Recovery Time"
          value={`${map.avg_recovery_time_days.toFixed(1)}d`}
          sub={`${map.avg_attempts_before_recovery.toFixed(1)} attempts avg`}
        />
      </div>

      {/* Row: funnel + attention */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="p-6 lg:col-span-2">
          <CardHeader
            title="Revenue flow"
            subtitle="Expected → entered recovery → verified recovered. Only captured payments count."
          />
          <div className="h-64">
            <FunnelPieChart data={map.funnel} />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {map.funnel.map((stage) => (
              <span key={stage.name} className="flex items-center gap-1.5 text-xs text-slate-400">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{
                    background: FUNNEL_COLORS[stage.name] ?? "#475569",
                  }}
                />
                {stage.name}: {formatINR(stage.amount)}
              </span>
            ))}
          </div>
        </Card>

        {/* Needs attention */}
        <Card className="p-6">
          <CardHeader
            title="Requires attention"
            subtitle={`${needsAttention.length} open cases`}
            action={
              <Link to="/cases" className="text-xs font-medium text-blue-400 hover:text-blue-300">
                View all →
              </Link>
            }
          />
          {needsAttention.length === 0 ? (
            <p className="text-sm text-slate-500">No cases require attention right now.</p>
          ) : (
            <ul className="space-y-2">
              {needsAttention.map((c) => (
                <li key={c.id}>
                  <Link
                    to={`/case/${c.id}`}
                    className="group flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-800/40 p-3 transition-colors hover:border-slate-700 hover:bg-slate-800"
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-700 text-xs font-bold text-slate-200">
                      {initials(c.customer_name)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block break-words text-sm font-medium leading-snug text-slate-200">
                        {c.customer_name || "Unknown customer"}
                      </span>
                      <span className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                        <Clock className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                        {timeAgo(c.updated_at)}
                      </span>
                      <span className="block text-xs text-slate-500">
                        {formatINR(c.remaining_amount)} outstanding
                      </span>
                    </span>
                    <span className="flex shrink-0 flex-col items-end gap-1.5">
                      <StatusBadge meta={caseMeta(c.status)} />
                      <span
                        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                          RISK_BADGES[c.risk_level] ?? RISK_BADGES.MEDIUM
                        }`}
                      >
                        {c.risk_level === "LOW"
                          ? "Low risk"
                          : c.risk_level === "HIGH"
                            ? "High risk"
                            : "Medium risk"}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* Row: timeline + channel mix */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="p-6 lg:col-span-2">
          <CardHeader
            title="Cumulative recovery over time"
            subtitle="Verified captured revenue after a payment failure enters recovery."
          />
          <div className="h-56">
            <RecoveryAreaChart data={map.recovery_timeline} />
          </div>
        </Card>

        {/* Channel mix */}
        <Card className="p-6">
          <CardHeader title="Recovery by channel" subtitle="How recovered money came back." />
          {channelData.length === 0 ? (
            <p className="text-sm text-slate-500">No recovered payments yet.</p>
          ) : (
            <>
              <div className="h-40">
                <ChannelPieChart data={channelData} />
              </div>
              <div className="mt-2 space-y-1.5">
                {channelData.map((slice) => (
                  <div key={slice.channel} className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5 text-slate-400">
                      <span className="h-2 w-2 rounded-full" style={{ background: CHANNEL_COLORS[slice.channel] ?? "#64748b" }} />
                      {slice.name}
                    </span>
                    <span className="font-medium text-slate-300">{formatINR(slice.amount)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
      </div>

      {/* Recently recovered */}
      <Card className="p-6">
        <CardHeader
          title="Recently recovered"
          subtitle="Money captured in the last completed cases."
          action={
            <Link to="/cases" className="text-xs font-medium text-blue-400 hover:text-blue-300">
              Manage cases →
            </Link>
          }
        />
        {recentRecovered.length === 0 && !map.recovered_revenue ? (
          <EmptyState
            icon="💰"
            title="No verified recoveries yet"
            description="Recovered revenue counts only captured payments, in real time. Run the batch simulation to see it in action."
            action={
              <Link to="/simulation" className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500">
                Open simulation
              </Link>
            }
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {recentRecovered.map((c) => (
              <Link
                key={c.id}
                to={`/case/${c.id}`}
                className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-800/40 p-3 transition-colors hover:border-slate-700 hover:bg-slate-800"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-green-500/15 text-xs font-bold text-green-400">
                  {initials(c.customer_name)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block break-words text-sm font-medium leading-snug text-slate-200">
                    {c.customer_name || "Unknown customer"}
                  </span>
                  <span className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                    Recovered {formatDate(c.updated_at)} · {formatINRFull(c.recovered_amount)}
                  </span>
                </span>
                <span className="text-sm font-bold text-green-400">{formatINR(c.recovered_amount)}</span>
              </Link>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

const FunnelPieChart = memo(function FunnelPieChart({
  data,
}: {
  data: { name: string; amount: number; tooltip: string }[]
}) {
  const enriched = data.map((f) => ({ ...f, name: f.tooltip || f.name }))
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={enriched}
          dataKey="amount"
          nameKey="name"
          innerRadius="46%"
          outerRadius="76%"
          paddingAngle={3}
          stroke="#0f172a"
          isAnimationActive={false}
        >
          {data.map((stage) => (
            <Cell key={stage.name} fill={FUNNEL_COLORS[stage.name] ?? "#475569"} />
          ))}
        </Pie>
        <Tooltip
          formatter={(value, name) => [formatINR(Number(value)), String(name)]}
          contentStyle={TOOLTIP_STYLE}
        />
      </PieChart>
    </ResponsiveContainer>
  )
})

const RecoveryAreaChart = memo(function RecoveryAreaChart({
  data,
}: {
  data: { label: string; recovered: number; cumulative: number }[]
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="dashGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#34d399" stopOpacity={0.35} />
            <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis dataKey="label" tick={CHART_TICK} axisLine={{ stroke: "#334155" }} tickLine={false} minTickGap={20} />
        <YAxis tick={CHART_TICK_Y} axisLine={{ stroke: "#334155" }} tickLine={false} tickFormatter={(v: number) => formatINR(v)} width={76} />
        <Tooltip content={<TimelineTooltip />} />
        <Area type="monotone" dataKey="cumulative" name="Recovered" stroke="#34d399" strokeWidth={2} fill="url(#dashGrad)" dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
})

interface TimelineTooltipProps {
  active?: boolean
  payload?: { payload: { label: string; recovered: number; cumulative: number } }[]
}

function TimelineTooltip({ active, payload }: TimelineTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  const d = payload[0].payload
  return (
    <div style={TOOLTIP_STYLE} className="rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="mb-1.5 font-semibold text-slate-200">{d.label}</p>
      <p className="flex items-center justify-between gap-5">
        <span className="text-slate-400">Period recovered</span>
        <span className="font-medium tabular-nums text-emerald-400">
          {formatINRFull(d.recovered)}
        </span>
      </p>
      <p className="mt-0.5 flex items-center justify-between gap-5">
        <span className="text-slate-400">Cumulative</span>
        <span className="font-medium tabular-nums text-emerald-300">
          {formatINRFull(d.cumulative)}
        </span>
      </p>
    </div>
  )
}

const ChannelPieChart = memo(function ChannelPieChart({
  data,
}: {
  data: { channel: string; name: string; amount: number; count: number }[]
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie data={data} dataKey="amount" nameKey="name" innerRadius="52%" outerRadius="80%" paddingAngle={3} stroke="#0f172a" isAnimationActive={false}>
          {data.map((slice) => (
            <Cell key={slice.channel} fill={CHANNEL_COLORS[slice.channel] ?? "#64748b"} />
          ))}
        </Pie>
        <Tooltip formatter={(value, name) => [formatINR(Number(value)), String(name)]} contentStyle={TOOLTIP_STYLE} />
      </PieChart>
    </ResponsiveContainer>
  )
})