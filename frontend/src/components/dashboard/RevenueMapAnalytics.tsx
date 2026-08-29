import { memo, useMemo, type CSSProperties } from "react"
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
import type { RevenueMap } from "../../types/analytics"
import { formatINR } from "../../lib/format"

interface Props {
  data: RevenueMap
}

const TOOLTIP_STYLE: CSSProperties = {
  backgroundColor: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "8px",
  color: "#e2e8f0",
  fontSize: "13px",
}

const FUNNEL_COLORS: Record<string, string> = {
  "Expected Revenue": "#60a5fa",
  "Entered Recovery": "#f59e0b",
  "Verified Recovered": "#34d399",
  "Still At Risk": "#f87171",
  "Lost Revenue": "#64748b",
}

const CHANNEL_COLORS: Record<string, string> = {
  whatsapp: "#22d3ee",
  email: "#60a5fa",
  payment_plan: "#a78bfa",
  unknown: "#64748b",
}

const RISK_COLORS: Record<string, string> = {
  high: "#f87171",
  medium: "#fbbf24",
  low: "#34d399",
}

const CHART_TICK = { fill: "#94a3b8", fontSize: 10.5 }
const CHART_TICK_Y = { fill: "#94a3b8", fontSize: 11 }

export default memo(function RevenueMapAnalytics({ data }: Props) {
  const empty = data.cases_count === 0
  const attemptedUnfulfilled = Math.max(
    data.attempted_recovery - data.recovered_revenue,
    0,
  )

  return (
    <div className="space-y-6">
      {/* Key metrics */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
        <Stat title="Total Revenue" value={formatINR(data.total_revenue)} color="text-blue-400" subtitle="All failed payments" />
        <Stat title="At-Risk Revenue" value={formatINR(data.at_risk_revenue)} color="text-red-400" subtitle="Outstanding on open cases" />
        <Stat title="Verified Recovered" value={formatINR(data.recovered_revenue)} color="text-green-400" subtitle="Captured payments" highlight />
        <Stat title="Lost Revenue" value={formatINR(data.lost_revenue)} color="text-gray-400" subtitle="Lost / opted out" />
        <Stat title="Recovery Rate" value={`${(data.recovery_rate * 100).toFixed(1)}%`} color="text-emerald-400" subtitle="Recovered ÷ Total" />
        <Stat title="Avg Recovery Time" value={`${data.avg_recovery_time_days.toFixed(1)} days`} color="text-cyan-400" subtitle="Creation → payment" />
        <Stat title="Avg Attempts Before Recovery" value={data.avg_attempts_before_recovery.toFixed(1)} color="text-amber-400" subtitle="Per recovered case" />
      </div>

      <EmptyNotice hidden={!empty} />

      {/* Attempted vs Verified */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <h2 className="text-lg font-semibold text-slate-100">
          ⚖️ Attempted Recovery vs Verified Recovered Revenue
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Attempting to contact a customer is NOT collecting money. Only
          captured payments count as recovered revenue — never messages,
          reminders, or promises.
        </p>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-400">
              Attempted Recovery
            </p>
            <p className="mt-1 text-2xl font-bold text-amber-300">{formatINR(data.attempted_recovery)}</p>
            <p className="mt-1 text-xs text-slate-400">Money recovery engaged with outbound attempts</p>
          </div>
          <div className="rounded-lg border border-green-500/30 bg-green-500/10 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-green-400">
              Verified Recovered
            </p>
            <p className="mt-1 text-2xl font-bold text-green-300">{formatINR(data.recovered_revenue)}</p>
            <p className="mt-1 text-xs text-slate-400">
              {data.payments_count} captured payments — actual money collected
            </p>
          </div>
          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Attempted, not yet collected
            </p>
            <p className="mt-1 text-2xl font-bold text-slate-200">
              {formatINR(attemptedUnfulfilled)}
            </p>
            <p className="mt-1 text-xs text-slate-400">Engaged but money has not arrived</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Revenue Funnel */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-lg font-semibold text-slate-100">🔻 Revenue Funnel</h2>
          <p className="mt-1 text-sm text-slate-400">
            Expected → Recovery → Recovered. Each stage is real money;
            "Entered Recovery" is the pool recovery engaged, while "Verified
            Recovered" is only captured payments.
          </p>
          <div className="mt-4">
            <RevenueFunnel stages={data.funnel} />
          </div>
          <p className="mt-2 text-xs text-slate-500">
            "Attempted" is the money pool contacted during recovery; "Verified
            Recovered" is only captured payments.
          </p>
        </div>

        {/* Recovery by Channel */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-lg font-semibold text-slate-100">📡 Recovery by Channel</h2>
          <p className="mt-1 text-sm text-slate-400">
            Verified recovered revenue, grouped by how the money came back.
          </p>
          <div className="mt-4 h-72">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data.recovery_by_channel}
                  dataKey="amount"
                  nameKey="name"
                  innerRadius="45%"
                  outerRadius="70%"
                  paddingAngle={2}
                  stroke="#0f172a"
                >
                  {data.recovery_by_channel.map((slice) => (
                    <Cell key={slice.channel} fill={CHANNEL_COLORS[slice.channel] ?? "#64748b"} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value) => [formatINR(Number(value)), "Verified recovered"]}
                  contentStyle={TOOLTIP_STYLE}
                />
                <Legend formatter={(value) => <span className="text-xs text-slate-300">{value}</span>} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Recovery Timeline */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <h2 className="text-lg font-semibold text-slate-100">
          📈 Recovery Timeline <span className="text-sm font-normal text-slate-400">— At Risk → Recovered</span>
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Cumulative verified recovered revenue over time from when cases went
          at risk to when money was actually captured.
        </p>
        <div className="mt-4 h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data.recovery_timeline} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="gradRecovered" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22c55e" stopOpacity={0.6} />
                  <stop offset="95%" stopColor="#22c55e" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" tick={CHART_TICK} axisLine={{ stroke: "#334155" }} tickLine={false} minTickGap={24} />
              <YAxis tick={CHART_TICK_Y} axisLine={{ stroke: "#334155" }} tickLine={false} tickFormatter={(v: number) => formatINR(v)} width={84} />
              <Tooltip formatter={(value) => [formatINR(Number(value)), "Verified recovered"]} contentStyle={TOOLTIP_STYLE} />
              <Area
                type="monotone"
                dataKey="cumulative"
                name="Verified recovered"
                stroke="#22c55e"
                strokeWidth={2}
                fill="url(#gradRecovered)"
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Recovery by Risk Level */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-lg font-semibold text-slate-100">🎯 Recovery by Risk Level</h2>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.recovery_by_risk_level} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="risk_level" tick={CHART_TICK} axisLine={{ stroke: "#334155" }} tickLine={false} />
                <YAxis tick={CHART_TICK_Y} axisLine={{ stroke: "#334155" }} tickLine={false} tickFormatter={(v: number) => formatINR(v)} width={84} />
                <Tooltip formatter={(value) => [formatINR(Number(value)), "Verified recovered"]} contentStyle={TOOLTIP_STYLE} />
                <Bar dataKey="amount" name="Verified recovered" radius={[6, 6, 0, 0]}>
                  {data.recovery_by_risk_level.map((slice) => (
                    <Cell key={slice.risk_level} fill={RISK_COLORS[slice.risk_level] ?? "#64748b"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Recovery by Language */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-lg font-semibold text-slate-100">🗣️ Recovery by Language</h2>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                layout="vertical"
                data={data.recovery_by_language}
                margin={{ top: 10, right: 20, left: 16, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                <XAxis type="number" tick={CHART_TICK} axisLine={{ stroke: "#334155" }} tickLine={false} tickFormatter={(v: number) => formatINR(v)} />
                <YAxis type="category" dataKey="name" tick={CHART_TICK} axisLine={{ stroke: "#334155" }} tickLine={false} width={84} />
                <Tooltip formatter={(value) => [formatINR(Number(value)), "Verified recovered"]} contentStyle={TOOLTIP_STYLE} />
                <Bar dataKey="amount" name="Verified recovered" radius={[0, 6, 6, 0]}>
                  {data.recovery_by_language.map((slice) => (
                    <Cell key={slice.language} fill="#5b8def" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Payment Plan Recovery */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-lg font-semibold text-slate-100">📅 Payment Plan Recovery</h2>
          <p className="mt-1 text-sm text-slate-400">
            Money agreed to be paid back in installments — and how much has
            actually been collected so far.
          </p>
          {data.payment_plan_recovery.plans_count > 0 ? (
            <>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <PanelStat label="Active Plans" value={String(data.payment_plan_recovery.plans_count)} color="text-fuchsia-400" />
                <PanelStat label="Planned Revenue" value={formatINR(data.payment_plan_recovery.total_amount)} color="text-blue-400" />
                <PanelStat label="Verified Collected" value={formatINR(data.payment_plan_recovery.recovered_amount)} color="text-green-400" />
                <PanelStat label="Still Scheduled" value={formatINR(data.payment_plan_recovery.remaining_amount)} color="text-amber-400" />
              </div>
              <ProgressBar
                value={data.payment_plan_recovery.recovered_amount}
                total={data.payment_plan_recovery.total_amount}
                label={`${(data.payment_plan_recovery.recovery_rate * 100).toFixed(1)}% of planned money collected`}
              />
            </>
          ) : (
            <p className="mt-4 text-sm text-slate-500">No payment plans yet.</p>
          )}
        </div>

        {/* Promise-to-Pay Recovery */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-lg font-semibold text-slate-100">🤝 Promise-to-Pay Recovery</h2>
          <p className="mt-1 text-sm text-slate-400">
            Customers who said they would pay. A promise is not a payment — this
            shows how many promised ₹ ever became captured payments.
          </p>
          {data.promise_to_pay_recovery.promised_cases > 0 ? (
            <>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <PanelStat label="Promised Cases" value={String(data.promise_to_pay_recovery.promised_cases)} color="text-blue-400" />
                <PanelStat label="Promised Amount" value={formatINR(data.promise_to_pay_recovery.promised_amount)} color="text-purple-400" />
                <PanelStat label="Verified Collected" value={formatINR(data.promise_to_pay_recovery.recovered_amount)} color="text-green-400" />
                <PanelStat label="Still Outstanding" value={formatINR(data.promise_to_pay_recovery.outstanding_amount)} color="text-red-400" />
              </div>
              <ProgressBar
                value={data.promise_to_pay_recovery.recovered_amount}
                total={data.promise_to_pay_recovery.promised_amount}
                label={`${(data.promise_to_pay_recovery.recovery_rate * 100).toFixed(1)}% of promised money became real payments`}
              />
            </>
          ) : (
            <p className="mt-4 text-sm text-slate-500">No promised payments yet.</p>
          )}
        </div>
      </div>
    </div>
  )
})

const BAND_HEIGHT = 46
const BAND_GAP = 10
const PAD_TOP = 6
const PAD_BOTTOM = 8
const VIEW_W = 360

/**
 * A dependency-light SVG revenue funnel.
 *
 * Each stage renders as a centered trapezoid whose width is proportional to its
 * amount relative to the largest stage. The stage name and its formatted amount
 * are drawn mid-band with `textAnchor="middle"` so they always sit centered
 * inside the polygon. A `viewBox` + `preserveAspectRatio=meet` keeps the whole
 * figure responsive (scales to the card width) without clipping, and the height
 * is derived from the stage count so tall funnels grow vertically.
 */
function RevenueFunnel({ stages }: { stages: { name: string; amount: number }[] }) {
  const hasData = !!stages && stages.length > 0

  const bands = useMemo(() => {
    if (!hasData) return []
    const maxAmount = Math.max(...stages.map((s) => s.amount), 1)
    const sidePad = 26
    const usable = VIEW_W - sidePad * 2
    let y = PAD_TOP

    const widths = stages.map((s) =>
      (s.amount / maxAmount) * usable,
    )

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
      <div className="flex h-40 items-center justify-center rounded-lg bg-slate-800/40 text-sm text-slate-500">
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
          <polygon
            points={b.pts}
            fill={b.fill}
            fillOpacity={0.32}
            stroke={b.fill}
            strokeWidth={1.5}
          />
          <text
            x={VIEW_W / 2}
            y={b.cy - 1}
            textAnchor="middle"
            fill="#e2e8f0"
            fontSize={12}
            fontWeight={600}
          >
            {b.stage.name}
          </text>
          <text
            x={VIEW_W / 2}
            y={b.cy + 13}
            textAnchor="middle"
            fill={b.fill}
            fontSize={12}
            fontWeight={700}
          >
            {formatINR(b.stage.amount)}
          </text>
        </g>
      ))}
    </svg>
  )
}

function Stat({
  title,
  value,
  color,
  subtitle,
  highlight,
}: {
  title: string
  value: string
  color: string
  subtitle?: string
  highlight?: boolean
}) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        highlight
          ? "border-green-500/40 bg-gradient-to-br from-green-950/40 to-emerald-900/20"
          : "border-slate-800 bg-slate-900"
      }`}
    >
      <p className="text-xs text-slate-400">{title}</p>
      <p className={`mt-1 text-xl font-bold ${color}`}>{value}</p>
      {subtitle && <p className="mt-0.5 text-[10px] text-slate-500">{subtitle}</p>}
    </div>
  )
}

function PanelStat({
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

function ProgressBar({
  value,
  total,
  label,
}: {
  value: number
  total: number
  label: string
}) {
  const pct = total > 0 ? Math.min((value / total) * 100, 100) : 0
  return (
    <div className="mt-4">
      <div className="mb-1 text-xs text-slate-400">{label}</div>
      <div className="h-2.5 overflow-hidden rounded-full bg-slate-800">
        <div className="h-full rounded-full bg-green-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function EmptyNotice({ hidden }: { hidden: boolean }) {
  if (hidden) return null
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm text-slate-400">
      No recovery cases yet — run the{" "}
      <span className="font-medium text-blue-400">Batch Simulation</span> or wait
      for real failed payments to build the Revenue Map.
    </div>
  )
}