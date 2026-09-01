import { memo, useMemo, type CSSProperties, type ReactNode } from "react"
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
import {
  Filter,
  Radio,
  TrendingUp,
  ShieldAlert,
  Languages,
  CalendarClock,
  Handshake,
  Wallet,
  AlertTriangle,
} from "lucide-react"
import type { RevenueMap, RecoveryCost } from "../../types/analytics"
import { formatINR, formatINRFull } from "../../lib/format"

interface Props {
  data: RevenueMap
}

const TOOLTIP_STYLE: CSSProperties = {
  backgroundColor: "#111827",
  border: "1px solid #27272a",
  borderRadius: "8px",
  color: "#e4e4e7",
  fontSize: "12px",
  boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
}

const FUNNEL_COLORS: Record<string, string> = {
  "Expected Revenue": "#71717a",
  "Entered Recovery": "#f59e0b",
  "Verified Recovered": "#10b981",
  "Still At Risk": "#f43f5e",
  "Lost Revenue": "#3f3f46",
}

const CHANNEL_COLORS: Record<string, string> = {
  whatsapp: "#10b981",
  email: "#60a5fa",
  payment_plan: "#a78bfa",
  unknown: "#52525b",
}

const RISK_COLORS: Record<string, string> = {
  high: "#f43f5e",
  medium: "#f59e0b",
  low: "#10b981",
}

const CHART_TICK = { fill: "#71717a", fontSize: 11 }
const CHART_TICK_Y = { fill: "#71717a", fontSize: 11 }

const TODAY_ISO = "2026-08-29"

export default memo(function RevenueMapAnalytics({ data }: Props) {
  // Clamp the timeline to today so no future dates render on the axis.
  const timeline = useMemo(
    () =>
      data.recovery_timeline
        .filter((p) => (p.label || "") <= TODAY_ISO)
        .slice(-45),
    [data.recovery_timeline],
  )

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Conversion Funnel */}
        <Card icon={<Filter className="h-4 w-4 text-zinc-400" />} title="Conversion Funnel">
          <RevenueFunnel stages={data.funnel} />
        </Card>

        {/* Recovery by Channel */}
        <Card icon={<Radio className="h-4 w-4 text-zinc-400" />} title="Recovery by Channel">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data.recovery_by_channel}
                  dataKey="amount"
                  nameKey="name"
                  innerRadius="45%"
                  outerRadius="70%"
                  paddingAngle={2}
                  stroke="#111827"
                >
                  {data.recovery_by_channel.map((slice) => (
                    <Cell key={slice.channel} fill={CHANNEL_COLORS[slice.channel] ?? "#52525b"} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value) => [formatINRFull(Number(value)), "Verified recovered"]}
                  contentStyle={TOOLTIP_STYLE}
                />
                <Legend formatter={(value) => <span className="text-xs text-zinc-400">{value}</span>} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Recovery Velocity Timeline */}
      <Card icon={<TrendingUp className="h-4 w-4 text-zinc-400" />} title="Recovery Velocity Timeline">
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={timeline} margin={{ top: 10, right: 16, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="gradSettled" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#111827" vertical={false} />
              <XAxis
                dataKey="label"
                tick={CHART_TICK}
                axisLine={{ stroke: "#1e293b" }}
                tickLine={false}
                minTickGap={32}
                tickFormatter={(v: string) =>
                  v.slice(5)?.replace("-", "/") ?? v
                }
              />
              <YAxis
                tick={CHART_TICK_Y}
                axisLine={{ stroke: "#1e293b" }}
                tickLine={false}
                tickFormatter={(v: number) => formatINR(v)}
                width={68}
              />
              <Tooltip
                content={<SettledTooltip />}
                cursor={{ stroke: "#334155", strokeDasharray: "3 3" }}
              />
              <Area
                type="monotone"
                dataKey="cumulative"
                name="Settled revenue"
                stroke="#10b981"
                strokeWidth={2}
                fill="url(#gradSettled)"
                dot={false}
                activeDot={{ r: 4, fill: "#10b981", stroke: "#111827" }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Recovery by Risk Category */}
        <Card icon={<ShieldAlert className="h-4 w-4 text-zinc-400" />} title="Recovery by Risk Category">
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.recovery_by_risk_level} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#18181b" vertical={false} />
                <XAxis dataKey="risk_level" tick={CHART_TICK} axisLine={{ stroke: "#27272a" }} tickLine={false} />
                <YAxis tick={CHART_TICK_Y} axisLine={{ stroke: "#27272a" }} tickLine={false} tickFormatter={(v: number) => formatINR(v)} width={68} />
                <Tooltip
                  formatter={(value) => [formatINRFull(Number(value)), "Verified recovered"]}
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "#18181b" }}
                />
                <Bar dataKey="amount" name="Verified recovered" radius={[4, 4, 0, 0]}>
                  {data.recovery_by_risk_level.map((slice) => (
                    <Cell key={slice.risk_level} fill={RISK_COLORS[slice.risk_level] ?? "#52525b"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* Outreach Language Distribution */}
        <Card icon={<Languages className="h-4 w-4 text-zinc-400" />} title="Outreach by Language">
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                layout="vertical"
                data={data.recovery_by_language}
                margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#18181b" horizontal={false} />
                <XAxis type="number" tick={CHART_TICK} axisLine={{ stroke: "#27272a" }} tickLine={false} tickFormatter={(v: number) => formatINR(v)} />
                <YAxis type="category" dataKey="name" tick={CHART_TICK} axisLine={{ stroke: "#27272a" }} tickLine={false} width={82} />
                <Tooltip
                  formatter={(value) => [formatINRFull(Number(value)), "Verified recovered"]}
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "#18181b" }}
                />
                <Bar dataKey="amount" name="Verified recovered" radius={[0, 4, 4, 0]} fill="#60a5fa" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* Recovery by Failure Reason */}
        <Card icon={<AlertTriangle className="h-4 w-4 text-zinc-400" />} title="Recovery by Root Cause">
          <div className="h-60">
            {data.recovery_by_failure_reason && data.recovery_by_failure_reason.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  layout="vertical"
                  data={data.recovery_by_failure_reason}
                  margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#18181b" horizontal={false} />
                  <XAxis type="number" tick={CHART_TICK} axisLine={{ stroke: "#27272a" }} tickLine={false} tickFormatter={(v: number) => formatINR(v)} />
                  <YAxis type="category" dataKey="name" tick={CHART_TICK} axisLine={{ stroke: "#27272a" }} tickLine={false} width={100} />
                  <Tooltip
                    formatter={(value) => [formatINRFull(Number(value)), "Verified recovered"]}
                    contentStyle={TOOLTIP_STYLE}
                    cursor={{ fill: "#18181b" }}
                  />
                  <Bar dataKey="amount" name="Verified recovered" radius={[0, 4, 4, 0]} fill="#f59e0b" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="flex h-full items-center justify-center text-sm text-zinc-500">No failure reason data yet.</p>
            )}
          </div>
        </Card>
      </div>

      {/* Bottom analytics grid */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card icon={<CalendarClock className="h-4 w-4 text-zinc-400" />} title="Structured Payment Plans">
          <PlanProgress
            collected={data.payment_plan_recovery.recovered_amount}
            scheduled={data.payment_plan_recovery.total_amount}
            rate={data.payment_plan_recovery.recovery_rate}
            plans={data.payment_plan_recovery.plans_count}
            emptyText="No payment plans yet."
          />
        </Card>

        <Card icon={<Handshake className="h-4 w-4 text-zinc-400" />} title="Promise-to-Pay Realization">
          <PlanProgress
            collected={data.promise_to_pay_recovery.recovered_amount}
            scheduled={data.promise_to_pay_recovery.promised_amount}
            rate={data.promise_to_pay_recovery.recovery_rate}
            plans={data.promise_to_pay_recovery.promised_cases}
            emptyText="No promised payments yet."
          />
        </Card>
      </div>

      {/* Cost of Recovery */}
      <Card icon={<Wallet className="h-4 w-4 text-zinc-400" />} title="Cost of Recovery">
        <CostOfRecovery cost={data.recovery_cost} />
      </Card>
    </div>
  )
})

/* ---------- Building blocks ---------- */

function SectionHeading({
  icon,
  title,
}: {
  icon: ReactNode
  title: string
}) {
  return (
    <div className="flex items-center gap-2">
      {icon}
      <h2 className="text-sm font-semibold tracking-tight text-zinc-100">{title}</h2>
    </div>
  )
}

function Card({
  icon,
  title,
  children,
}: {
  icon: ReactNode
  title: string
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-5 transition-colors duration-150 hover:border-zinc-700">
      <SectionHeading icon={icon} title={title} />
      <div className="mt-4">{children}</div>
    </section>
  )
}

function PlanProgress({
  collected,
  scheduled,
  rate,
  plans,
  emptyText,
}: {
  collected: number
  scheduled: number
  rate: number
  plans: number
  emptyText: string
}) {
  if (scheduled <= 0 || plans <= 0) {
    return <p className="text-sm text-zinc-500">{emptyText}</p>
  }
  const pct = Math.min(rate * 100, 100)
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <p className="text-xs text-zinc-400">
          <span className="font-semibold text-emerald-400">{formatINRFull(collected)}</span>{" "}
          collected of{" "}
          <span className="font-medium text-zinc-200">{formatINRFull(scheduled)}</span>{" "}
          {plans === 1 ? "plan" : "plans"}
        </p>
        <span className="font-mono text-xs font-semibold tabular-nums text-emerald-400">
          {pct.toFixed(1)}%
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-zinc-800">
        <div
          className="h-full rounded-full bg-emerald-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-1.5 font-mono text-[11px] tabular-nums text-zinc-500">
        across {plans} {plans === 1 ? "case" : "cases"}
      </p>
    </div>
  )
}

function CostOfRecovery({ cost }: { cost: RecoveryCost }) {
  const spent = cost.total_cost_paise
  const recovered = cost.recovered_revenue
  const ratio = cost.cost_of_recovery_ratio ?? (spent > 0 && recovered > 0 ? spent / recovered : 0)
  const pct = Math.min(ratio * 100, 100)
  const warn = pct > 5

  if (spent <= 0 && cost.whatsapp_messages <= 0 && cost.emails <= 0) {
    return <p className="text-sm text-zinc-500">No outreach costs tracked yet.</p>
  }

  return (
    <div>
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400">Outreach mix</p>
          <p className="mt-1 text-sm font-semibold text-zinc-200">
            {cost.whatsapp_messages} WhatsApp
          </p>
          <p className="text-sm font-semibold text-zinc-200">{cost.emails} email</p>
          <p className="mt-1 font-mono text-[10px] tabular-nums text-zinc-500">
            ₹{cost.whatsapp_cost_paise / 100} + ₹{cost.email_cost_paise / 100} in cost
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-400">Spend vs recovered</p>
          <p className="mt-1 font-mono text-lg font-semibold tabular-nums text-amber-400">{formatINR(spent)}</p>
          <p className="font-mono text-xs tabular-nums text-emerald-400">{formatINR(recovered)} recovered</p>
        </div>
      </div>
      <div className="mt-3">
        <div className="flex items-baseline justify-between">
          <p className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">Cost of recovery</p>
          <span className={`font-mono text-xs font-semibold tabular-nums ${warn ? "text-amber-400" : "text-emerald-400"}`}>
            {pct.toFixed(2)}%
          </span>
        </div>
        <div className="mt-1 h-2 overflow-hidden rounded-full bg-zinc-800">
          <div
            className={`h-full rounded-full ${warn ? "bg-amber-500" : "bg-emerald-500"}`}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
        <p className="mt-1.5 text-[10px] text-zinc-600">
          {ratio >= 1
            ? "Spend exceeds recovered value — outreach density too high."
            : "Outreach cost is a small fraction of verified recovered revenue."}
        </p>
      </div>
    </div>
  )
}

function SettledTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ value: number }>
  label?: string | number
}) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-zinc-500">
        {String(label)}
      </p>
      <p className="mt-0.5 font-mono text-sm font-semibold tabular-nums text-emerald-400">
        {formatINRFull(Number(payload[0].value))}
      </p>
    </div>
  )
}

const BAND_HEIGHT = 46
const BAND_GAP = 10
const PAD_TOP = 6
const PAD_BOTTOM = 8
const VIEW_W = 360

function RevenueFunnel({ stages }: { stages: { name: string; amount: number }[] }) {
  const hasData = !!stages && stages.length > 0

  const bands = useMemo(() => {
    if (!hasData) return []
    const maxAmount = Math.max(...stages.map((s) => s.amount), 1)
    const sidePad = 26
    const usable = VIEW_W - sidePad * 2
    let y = PAD_TOP

    const widths = stages.map((s) => (s.amount / maxAmount) * usable)

    return stages.map((stage, i) => {
      const topW = Math.max(widths[i], 10)
      const botW = i < stages.length - 1 ? Math.max(widths[i + 1], 10) : topW * 0.72
      const yTop = y
      const yBot = y + BAND_HEIGHT
      y += BAND_HEIGHT + BAND_GAP
      const cx = VIEW_W / 2
      const pts = [
        `${cx - topW / 2},${yTop}`,
        `${cx + topW / 2},${yTop}`,
        `${cx + botW / 2},${yBot}`,
        `${cx - botW / 2},${yBot}`,
      ].join(" ")
      return {
        stage,
        pts,
        cy: (yTop + yBot) / 2,
        fill: FUNNEL_COLORS[stage.name] ?? "#475569",
      }
    })
  }, [stages, hasData])

  if (!hasData) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-zinc-800/80 bg-zinc-950/40 text-sm text-zinc-500">
        No funnel data yet
      </div>
    )
  }

  const viewH = PAD_TOP + stages.length * (BAND_HEIGHT + BAND_GAP) + PAD_BOTTOM

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${viewH}`}
      className="h-auto w-full"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Revenue funnel"
    >
      {bands.map((b) => (
        <g key={b.stage.name}>
          <polygon points={b.pts} fill={b.fill} fillOpacity={0.32} stroke={b.fill} strokeWidth={1.5} />
          <text x={VIEW_W / 2} y={b.cy - 1} textAnchor="middle" fill="#e4e4e7" fontSize={12} fontWeight={600}>
            {b.stage.name}
          </text>
          <text x={VIEW_W / 2} y={b.cy + 13} textAnchor="middle" fill={b.fill} fontSize={12} fontWeight={700}>
            {formatINR(b.stage.amount)}
          </text>
        </g>
      ))}
    </svg>
  )
}
