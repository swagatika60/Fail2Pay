import { useEffect } from "react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import type { CSSProperties } from "react"
import { CalendarDays, Handshake, Radio } from "lucide-react"
import { useDashboardStore } from "../hooks/dashboardStore"
import { PageHeader } from "../components/ui/PageHeader"
import { Card, CardHeader } from "../components/ui/Card"
import { StatCard } from "../components/ui/StatCard"
import { EmptyState } from "../components/ui/EmptyState"
import { ProgressBar } from "../components/ui/ProgressBar"
import { Skeleton } from "../components/ui/Skeleton"
import { formatINR, formatPercent } from "../lib/format"

const TOOLTIP_STYLE: CSSProperties = {
  backgroundColor: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "8px",
  color: "#e2e8f0",
  fontSize: "13px",
}

const CHART_TICK = { fill: "#94a3b8", fontSize: 10.5 }
const CHART_TICK_Y = { fill: "#94a3b8", fontSize: 11 }

const FUNNEL_COLORS: Record<string, string> = {
  "Expected Revenue": "#3b82f6",
  "Entered Recovery": "#f59e0b",
  "Verified Recovered": "#34d399",
  "Still At Risk": "#f87171",
  "Lost Revenue": "#64748b",
}

const RISK_COLORS: Record<string, string> = {
  HIGH: "#f87171",
  MEDIUM: "#fbbf24",
  LOW: "#34d399",
}

const CHANNEL_COLORS: Record<string, string> = {
  whatsapp: "#22d3ee",
  email: "#60a5fa",
  payment_plan: "#a78bfa",
  unknown: "#64748b",
}

export default function AnalyticsPage() {
  const { map, loading, error, ensureLoaded } = useDashboardStore()

  useEffect(() => {
    ensureLoaded()
  }, [ensureLoaded])

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-72 rounded-xl" />
      </div>
    )
  }

  if (error || !map) {
    return (
      <div className="rounded-xl border border-red-800 bg-red-900/20 p-6 text-center text-red-400">
        {error ?? "Failed to load analytics"}
      </div>
    )
  }

  const plan = map.payment_plan_recovery
  const promise = map.promise_to_pay_recovery

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics"
        subtitle="Performance of the recovery engine — measured in cash actually collected."
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Conversion rate" value={formatPercent(map.recovery_rate)} sub={`${formatINR(map.recovered_revenue)} of ${formatINR(map.at_risk_revenue + map.recovered_revenue)} at risk`} tone="success" />
        <StatCard label="Avg recovery time" value={`${map.avg_recovery_time_days.toFixed(1)} days`} sub="risk → captured payment" tone="info" />
        <StatCard label="Attempts per recovery" value={map.avg_attempts_before_recovery.toFixed(1)} sub="average touches before paying" tone="warning" />
        <StatCard label="Paid via plan" value={formatINR(plan.recovered_amount)} sub={`${plan.plans_count} payment plans`} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="p-6">
          <CardHeader title="Revenue funnel" subtitle="Each stage is real money on the books." />
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={map.funnel} dataKey="amount" nameKey="tooltip" innerRadius="40%" outerRadius="72%" paddingAngle={3} stroke="#0f172a" isAnimationActive={false}>
                  {map.funnel.map((stage) => (
                    <Cell key={stage.name} fill={FUNNEL_COLORS[stage.name] ?? "#475569"} />
                  ))}
                </Pie>
                <Tooltip formatter={(value, name) => [formatINR(Number(value)), String(name)]} contentStyle={TOOLTIP_STYLE} />
                <Legend formatter={(value) => <span className="text-xs text-slate-300">{value}</span>} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 space-y-1.5">
            {map.funnel.map((stage) => (
              <div key={stage.name} className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 text-slate-400">
                  <span className="h-2 w-2 rounded-full" style={{ background: FUNNEL_COLORS[stage.name] ?? "#475569" }} />
                  {stage.name}
                </span>
                <span className="font-medium text-slate-300">{formatINR(stage.amount)}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-6">
          <CardHeader title="Recovery by risk level" subtitle="Where the recovered rupees came from." />
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={map.recovery_by_risk_level} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="risk_level" tick={CHART_TICK} axisLine={{ stroke: "#334155" }} tickLine={false} />
                <YAxis tick={CHART_TICK_Y} axisLine={{ stroke: "#334155" }} tickLine={false} tickFormatter={(v: number) => formatINR(v)} width={80} />
                <Tooltip formatter={(value) => [formatINR(Number(value)), "Recovered"]} contentStyle={TOOLTIP_STYLE} />
                <Bar dataKey="amount" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                  {map.recovery_by_risk_level.map((slice) => (
                    <Cell key={slice.risk_level} fill={RISK_COLORS[slice.risk_level] ?? "#64748b"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card className="p-6">
        <CardHeader title="Cumulative recovery trend" subtitle="Verified captured revenue over time from case inception." />
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={map.recovery_timeline} margin={{ top: 10, right: 16, left: 0, bottom: 5 }}>
              <defs>
                <linearGradient id="analyticsGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#34d399" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" tick={CHART_TICK} axisLine={{ stroke: "#334155" }} tickLine={false} minTickGap={24} />
              <YAxis tick={CHART_TICK_Y} axisLine={{ stroke: "#334155" }} tickLine={false} tickFormatter={(v: number) => formatINR(v)} width={84} />
              <Tooltip formatter={(value) => [formatINR(Number(value)), "Recovered"]} contentStyle={TOOLTIP_STYLE} />
              <Area type="monotone" dataKey="cumulative" stroke="#34d399" strokeWidth={2} fill="url(#analyticsGrad)" dot={false} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="p-6">
          <CardHeader title="Payment plan recovery" subtitle="Installment revenue agreed and collected." />
          {plan.plans_count === 0 ? (
            <EmptyState icon={CalendarDays} title="No payment plans" description="Plans created during recovery appear here." />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <MetricCell label="Active plans" value={String(plan.plans_count)} color="text-blue-400" />
                <MetricCell label="Planned revenue" value={formatINR(plan.total_amount)} color="text-slate-200" />
                <MetricCell label="Collected" value={formatINR(plan.recovered_amount)} color="text-green-400" />
                <MetricCell label="Still scheduled" value={formatINR(plan.remaining_amount)} color="text-amber-400" />
              </div>
              <ProgressBar value={plan.recovered_amount} total={plan.total_amount} className="mt-4" />
              <p className="mt-2 text-xs text-slate-500">
                {formatPercent(plan.recovery_rate)} of planned money collected
              </p>
            </>
          )}
        </Card>

        <Card className="p-6">
          <CardHeader title="Promise-to-pay recovery" subtitle="Promises made vs. cash collected." />
          {promise.promised_cases === 0 ? (
            <EmptyState icon={Handshake} title="No promises" description="Customer payment promises appear here." />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <MetricCell label="Promised cases" value={String(promise.promised_cases)} color="text-blue-400" />
                <MetricCell label="Promised amount" value={formatINR(promise.promised_amount)} color="text-slate-200" />
                <MetricCell label="Collected" value={formatINR(promise.recovered_amount)} color="text-green-400" />
                <MetricCell label="Still outstanding" value={formatINR(promise.outstanding_amount)} color="text-red-400" />
              </div>
              <ProgressBar value={promise.recovered_amount} total={promise.promised_amount} className="mt-4" />
              <p className="mt-2 text-xs text-slate-500">
                {formatPercent(promise.recovery_rate)} of promised money became real payments
              </p>
            </>
          )}
        </Card>
      </div>

      <Card className="p-6">
        <CardHeader title="Recovery by channel" subtitle="How collected money came back to you." />
        {map.recovery_by_channel.length === 0 ? (
          <EmptyState icon={Radio} title="No channel data" description="Channel attribution appears once payments are captured." />
        ) : (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={map.recovery_by_channel} dataKey="amount" nameKey="name" innerRadius="48%" outerRadius="78%" paddingAngle={3} stroke="#0f172a" isAnimationActive={false}>
                    {map.recovery_by_channel.map((slice) => (
                      <Cell key={slice.channel} fill={CHANNEL_COLORS[slice.channel] ?? "#64748b"} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value, name) => [formatINR(Number(value)), String(name)]} contentStyle={TOOLTIP_STYLE} />
                  <Legend formatter={(value) => <span className="text-xs text-slate-300">{value}</span>} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="space-y-2">
              {map.recovery_by_channel.map((slice) => (
                <div key={slice.channel} className="flex items-center justify-between rounded-lg bg-slate-800/40 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-200">{slice.name}</span>
                    <span className="text-xs text-slate-500">{slice.count} payments</span>
                  </div>
                  <span className="font-semibold text-slate-200">{formatINR(slice.amount)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

function MetricCell({
  label,
  value,
  color,
}: {
  label: string
  value: string
  color: string
}) {
  return (
    <div className="rounded-lg bg-slate-800/50 p-3 text-center">
      <p className={`text-lg font-bold ${color}`}>{value}</p>
      <p className="text-[11px] text-slate-500">{label}</p>
    </div>
  )
}