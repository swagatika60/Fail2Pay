import {
  memo,
  useMemo,
  type ComponentType,
  type CSSProperties,
  type ReactNode,
} from "react"
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
  AlertTriangle,
  Ban,
  CalendarClock,
  FileSearch,
  Filter,
  Handshake,
  Languages,
  Radio,
  ShieldAlert,
  TrendingUp,
  Wallet,
} from "lucide-react"
import { EmptyState } from "../ui/EmptyState"
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

// Main conversion path only — leakages (lost / still at risk) render beside
// the funnel as side drop-offs, never as sequential bands.
const MAIN_FUNNEL_STAGES = ["Expected Revenue", "Entered Recovery", "Verified Recovered"]

const FUNNEL_COLORS: Record<string, string> = {
  "Expected Revenue": "#71717a",
  "Entered Recovery": "#f59e0b",
  "Verified Recovered": "#10b981",
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

// Clamp the timeline to the actual current date (never a hardcoded demo day),
// so the chart reflects today no matter when it's viewed.
const TODAY_ISO = (() => {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, "0")
  const d = String(now.getDate()).padStart(2, "0")
  return `${y}-${m}-${d}`
})()

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
          {data.recovery_by_failure_reason && data.recovery_by_failure_reason.length > 0 ? (
            <div className="h-60">
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
            </div>
          ) : (
            <EmptyState
              icon={FileSearch}
              title="No failure reason data yet"
              description="Reason analytics will appear once gateway failure codes are mapped to root causes."
            />
          )}
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
  // How many rupees of verified recovery every rupee of outreach buys back.
  const roi = spent > 0 && recovered > 0 ? Math.round(recovered / spent) : 0

  if (spent <= 0 && cost.whatsapp_messages <= 0 && cost.emails <= 0) {
    return <p className="text-sm text-zinc-500">No outreach costs tracked yet.</p>
  }

  // Tiny spends round down to a flat "0.00%" — surface them honestly as
  // "< 0.01%" and add an ROI multiple so the leverage stays legible.
  const pctLabel =
    recovered <= 0
      ? "—"
      : pct > 0 && pct < 0.01
        ? "< 0.01%"
        : `${pct.toFixed(2)}%`
  // Give the near-zero bar a visible sliver instead of an empty track.
  const barWidth = pct > 0 && pct < 0.5 ? 0.5 : Math.min(pct, 100)

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
          {roi >= 100 && (
            <p className="mt-1.5 inline-flex items-center rounded border border-emerald-900/60 bg-emerald-950/40 px-1.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-emerald-400">
              ≈ {formatRoiMultiple(roi)}x ROI
            </p>
          )}
        </div>
      </div>
      <div className="mt-3">
        <div className="flex items-baseline justify-between">
          <p className="text-[10px] uppercase tracking-[0.12em] text-zinc-500">Cost of recovery</p>
          <span className={`font-mono text-xs font-semibold tabular-nums ${warn ? "text-amber-400" : "text-emerald-400"}`}>
            {pctLabel}
          </span>
        </div>
        <div className="mt-1 h-2 overflow-hidden rounded-full bg-zinc-800">
          <div
            className={`h-full rounded-full ${warn ? "bg-amber-500" : "bg-emerald-500"}`}
            style={{ width: `${barWidth}%` }}
          />
        </div>
        <p className="mt-1.5 text-[10px] text-zinc-600">
          {recovered <= 0
            ? "Outreach was sent but nothing is verified recovered yet."
            : ratio >= 1
              ? "Spend exceeds recovered value — outreach density too high."
              : "Outreach cost is a small fraction of verified recovered revenue."}
        </p>
      </div>
    </div>
  )
}

function formatRoiMultiple(x: number): string {
  if (x >= 1_000_000) return `${(x / 1_000_000).toFixed(1)}M`
  if (x >= 1_000) return `${(x / 1_000).toFixed(1)}K`
  return x.toLocaleString("en-IN")
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

// ---- Conversion funnel geometry ----------------------------------------
// Standard funnel proportions: every band shares the same height, each band
// tapers from its own width (∝ amount) down to the *next* stage's width, and
// the final band narrows toward a point — so the silhouette reads as one
// continuous conversion path. Lost / Still At Risk are NOT bands here; they
// render beside the funnel as side leakages.
const BAND_HEIGHT = 46
const BAND_GAP = 22 // tall enough for the inter-stage conversion caption
const PAD_TOP = 8
const PAD_BOTTOM = 8
const VIEW_W = 360

// Side-leakage cards: colour-matched to the dark theme (rose = lost / exited,
// amber = still open / at risk) and dashed to signal they are drop-offs.
const LEAK_META: Record<
  string,
  {
    label: string
    hint: string
    icon: ComponentType<{ className?: string }>
    frame: string
    amountClass: string
    iconClass: string
  }
> = {
  "Lost Revenue": {
    label: "Lost / Opted Out",
    hint: "Closed as lost or opted out — exited the pipeline",
    icon: Ban,
    frame: "border-rose-900/50 bg-rose-950/20",
    amountClass: "text-rose-300",
    iconClass: "text-rose-400",
  },
  "Still At Risk": {
    label: "Still At Risk",
    hint: "Unpaid balance on open cases — still in train",
    icon: AlertTriangle,
    frame: "border-amber-900/50 bg-amber-950/20",
    amountClass: "text-amber-300",
    iconClass: "text-amber-400",
  },
}

function RevenueFunnel({ stages }: { stages: { name: string; amount: number }[] }) {
  // Main conversion path is strictly progressive; anything not on it is a
  // side leakage shown alongside (never a downward step in the funnel).
  const main = useMemo(
    () => stages.filter((s) => MAIN_FUNNEL_STAGES.includes(s.name)),
    [stages],
  )
  const leaks = useMemo(
    () => stages.filter((s) => LEAK_META[s.name]),
    [stages],
  )

  if (main.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-zinc-800/80 bg-zinc-950/40 text-sm text-zinc-500">
        No funnel data yet
      </div>
    )
  }

  const maxAmount = Math.max(...main.map((s) => s.amount), 1)
  const sidePad = 26
  const usable = VIEW_W - sidePad * 2
  const widths = main.map((s) => (s.amount / maxAmount) * usable)

  const bands = main.map((stage, i) => {
    const yTop = PAD_TOP + i * (BAND_HEIGHT + BAND_GAP)
    const yBot = yTop + BAND_HEIGHT
    const topW = Math.max(widths[i], 14)
    // Taper to the next stage's width; the last band keeps narrowing toward
    // the eventual conversion point (never to zero).
    const botW =
      i < main.length - 1 ? Math.max(widths[i + 1], 14) : Math.max(topW * 0.55, 10)
    const cx = VIEW_W / 2
    const pts = [
      `${cx - topW / 2},${yTop}`,
      `${cx + topW / 2},${yTop}`,
      `${cx + botW / 2},${yBot}`,
      `${cx - botW / 2},${yBot}`,
    ].join(" ")
    const next = main[i + 1]
    const conversion =
      i < main.length - 1 && stage.amount > 0 ? (next.amount / stage.amount) * 100 : null
    return {
      stage,
      pts,
      cy: (yTop + yBot) / 2,
      yBot,
      conversion,
      fill: FUNNEL_COLORS[stage.name] ?? "#475569",
    }
  })

  const viewH = PAD_TOP + main.length * (BAND_HEIGHT + BAND_GAP) - BAND_GAP + PAD_BOTTOM

  return (
    <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_210px]">
      {/* Main conversion path */}
      <svg
        viewBox={`0 0 ${VIEW_W} ${viewH}`}
        className="h-auto w-full"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Revenue conversion funnel"
      >
        {bands.map((b) => (
          <g key={b.stage.name}>
            <polygon points={b.pts} fill={b.fill} fillOpacity={0.28} stroke={b.fill} strokeWidth={1.5} />
            <text x={VIEW_W / 2} y={b.cy - 1} textAnchor="middle" fill="#e4e4e7" fontSize={12} fontWeight={600}>
              {b.stage.name}
            </text>
            <text x={VIEW_W / 2} y={b.cy + 13} textAnchor="middle" fill={b.fill} fontSize={12.5} fontWeight={700}>
              {formatINR(b.stage.amount)}
            </text>
          </g>
        ))}
        {bands.slice(0, -1).map((b) => (
          <text
            key={`conversion-${b.stage.name}`}
            x={VIEW_W / 2}
            y={b.yBot + BAND_GAP / 2 + 3}
            textAnchor="middle"
            fill="#71717a"
            fontSize={10}
          >
            {b.conversion == null || !Number.isFinite(b.conversion)
              ? ""
              : `${Math.max(0, Math.round(b.conversion))}% converted`}
          </text>
        ))}
      </svg>

      {/* Side leakages — drop-offs, not funnel steps */}
      {leaks.length > 0 && (
        <div className="flex flex-col gap-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
            Drop-offs & open balance
          </p>
          {leaks.map((leak) => {
            const meta = LEAK_META[leak.name]
            const Icon = meta.icon
            return (
              <div
                key={leak.name}
                className={`rounded-lg border border-dashed p-3 ${meta.frame}`}
              >
                <div className="flex items-center gap-1.5">
                  <Icon className={`h-3.5 w-3.5 ${meta.iconClass}`} />
                  <span className="text-[11px] font-medium text-zinc-300">{meta.label}</span>
                </div>
                <p className={`mt-1.5 font-mono text-base font-semibold tabular-nums ${meta.amountClass}`}>
                  {formatINR(leak.amount)}
                </p>
                <p className="mt-0.5 text-[10px] leading-snug text-zinc-500">{meta.hint}</p>
              </div>
            )
          })}
          <p className="text-[10px] leading-snug text-zinc-600">
            Exits and unpaid balances sit beside the funnel — they are not conversion steps.
          </p>
        </div>
      )}
    </div>
  )
}
