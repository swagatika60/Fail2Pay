import { memo, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Zap, TrendingUp, ShieldAlert, Clock3 } from "lucide-react"
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { useDashboardStore } from "../hooks/dashboardStore"
import { Card, CardHeader } from "../components/ui/Card"
import { PageHeader } from "../components/ui/PageHeader"
import { Skeleton, SkeletonTable } from "../components/ui/Skeleton"
import { Button } from "../components/ui/Button"
import { MetricCard, type Delta } from "../components/dashboard/MetricCard"
import { RecoveryFunnel, type FunnelStage } from "../components/dashboard/RecoveryFunnel"
import { SectionCard } from "../components/dashboard/SectionCard"
import { AttentionTable } from "../components/dashboard/AttentionTable"
import { RecentRecoveries } from "../components/dashboard/RecentRecoveries"
import {
  DashboardFilters,
  type FilterState,
} from "../components/dashboard/DashboardFilters"
import { formatMoney, formatPercent, formatFullMoney } from "../lib/format"
import type { CSSProperties } from "react"

const TOOLTIP_STYLE: CSSProperties = {
  backgroundColor: "#0f172a",
  border: "1px solid #334155",
  borderRadius: "8px",
  color: "#e2e8f0",
  fontSize: "13px",
}

const CHART_TICK = { fill: "#64748b", fontSize: 10.5 }
const CHART_TICK_Y = { fill: "#64748b", fontSize: 11 }

const TODAY_ISO = (() => {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, "0")
  const d = String(now.getDate()).padStart(2, "0")
  return `${y}-${m}-${d}`
})()

const OPEN_STATUSES = new Set([
  "AT_RISK",
  "RECOVERY_IN_PROGRESS",
  "ENGAGED",
  "PROMISED",
  "PAYMENT_PLAN",
  "SCHEDULED",
  "PARTIALLY_RECOVERED",
])

const RISK_ORDER: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 }

const DEFAULT_FILTERS: FilterState = { range: "30d", channel: "all", currency: "INR" }

function withinRange(updatedAt: string, range: string): boolean {
  if (!updatedAt || range === "all") return true
  const days = range === "7d" ? 7 : range === "30d" ? 30 : 90
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000
  return Date.parse(updatedAt) >= cutoff
}

export default function DashboardPage() {
  const { map, summary, cases, loading, error, simulatePaymentFailure } =
    useDashboardStore()
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS)
  const currency = filters.currency

  const money = (amount: number) => formatMoney(amount, currency)
  const moneyFull = (amount: number) => formatFullMoney(amount, currency)

  const needsAttention = useMemo(() => {
    return cases
      .filter((c) => OPEN_STATUSES.has(c.status))
      .filter((c) => withinRange(c.updated_at, filters.range))
      .sort((a, b) => {
        const riskDiff =
          (RISK_ORDER[a.risk_level] ?? 9) - (RISK_ORDER[b.risk_level] ?? 9)
        if (riskDiff !== 0) return riskDiff
        return b.remaining_amount - a.remaining_amount
      })
  }, [cases, filters.range])

  const recentRecovered = useMemo(() => {
    return cases
      .filter((c) => c.status === "RECOVERED")
      .filter((c) => withinRange(c.updated_at, filters.range))
      .slice()
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  }, [cases, filters.range])

  const openCaseCount = useMemo(
    () => cases.filter((c) => OPEN_STATUSES.has(c.status)).length,
    [cases],
  )

  // Sparklines derived from the verified cumulative timeline.
  const sparkSeries = useMemo(() => {
    const ts = (map?.recovery_timeline ?? []).filter(
      (d) => d.label <= TODAY_ISO,
    )
    return {
      recovered: ts.map((d) => d.recovered),
      cumulative: ts.map((d) => d.cumulative),
      atRisk: ts.map((_, i) => Math.max(ts[i]?.cumulative ?? 0, 0)),
    }
  }, [map])

  // Conversion funnel: entered at risk -> engaged/promised -> recovered.
  const funnel = useMemo<FunnelStage[]>(() => {
    if (!map) return []
    const promised = map.promise_to_pay_recovery?.promised_amount ?? 0
    const planTotal = map.payment_plan_recovery?.total_amount ?? 0
    return [
      {
        key: "entered",
        label: "Entered recovery",
        amount: map.at_risk_revenue,
        count: map.cases_count ?? 0,
        tone: "amber",
      },
      {
        key: "active",
        label: "Active / Promised",
        amount: promised + planTotal,
        count: (map.promise_to_pay_recovery?.promised_cases ?? 0) +
          (map.payment_plan_recovery?.plans_count ?? 0),
        tone: "default",
      },
      {
        key: "recovered",
        label: "Verified recovered",
        amount: map.recovered_revenue,
        count: map.payments_count ?? 0,
        tone: "emerald",
      },
    ]
  }, [map])

  const triggerMockFailureWebhook = () => {
    const base = Math.max(map?.at_risk_revenue ?? 0, 500000)
    const amount = Math.round(base * 0.1) + Math.floor(Math.random() * 300000)
    simulatePaymentFailure(amount)
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-72" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-36 rounded-xl" />
          ))}
        </div>
        <SkeletonTable rows={6} />
      </div>
    )
  }

  if (error || !map || !summary) {
    return (
      <div className="rounded-xl border border-rose-800 bg-rose-900/20 p-6 text-center">
        <p className="text-lg font-semibold text-rose-400">Failed to load dashboard</p>
        <p className="mt-2 text-sm text-slate-400">{error}</p>
      </div>
    )
  }

  // Deltas (comparison baselines derived from self-cure ledger where sensible).
  const recoveredDelta: Delta | undefined =
    summary.self_cure_amount > 0
      ? {
          direction: "up",
          label: `${formatPercent(
            map.recovered_revenue / summary.self_cure_amount - 1,
            0,
          )} vs baseline`,
          favorable: true,
        }
      : undefined

  const rateDelta: Delta = summary.self_cure_rate > 0
    ? {
        direction: "up",
        label: `${formatPercent(summary.lift_over_self_cure, 0)} vs self-cure`,
        favorable: true,
      }
    : { direction: "flat", label: "vs baseline", favorable: true }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Revenue Recovery Command Center"
        subtitle="Verified money only — captured settlements, not touches."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <DashboardFilters state={filters} onChange={setFilters} />
            <div className="mx-1 hidden h-6 w-px bg-slate-800 sm:block" />
            <Button
              variant="secondary"
              size="sm"
              onClick={triggerMockFailureWebhook}
            >
              <Zap className="h-3.5 w-3.5" />
              Simulate Failure Webhook
            </Button>
            <Link to="/revenue-map">
              <Button variant="secondary" size="sm">
                View Revenue Map
              </Button>
            </Link>
          </div>
        }
      />

      {/* Primary Row — Hero Stats */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Revenue recovered"
          value={money(map.recovered_revenue)}
          delta={recoveredDelta}
          context={`${map.payments_count} captured payments`}
          spark={sparkSeries.cumulative}
          icon={<TrendingUp className="h-4 w-4" />}
          tone="emerald"
        />
        <MetricCard
          label="Recovery rate"
          value={formatPercent(map.recovery_rate)}
          delta={rateDelta}
          context={`${money(map.attempted_recovery)} engaged`}
          spark={sparkSeries.recovered}
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <MetricCard
          label="Revenue at risk"
          value={money(map.at_risk_revenue)}
          delta={{ direction: "flat", label: `${openCaseCount} open cases`, favorable: false }}
          context="Current exposure, not yet engaged"
          spark={sparkSeries.atRisk}
          icon={<ShieldAlert className="h-4 w-4" />}
          tone="amber"
        />
        <MetricCard
          label="Avg recovery time"
          value={`${map.avg_recovery_time_days.toFixed(1)}d`}
          delta={{
            direction: "down",
            label: `${map.avg_attempts_before_recovery.toFixed(1)} attempts`,
            favorable: true,
          }}
          context="Mean from failure to verified capture"
          icon={<Clock3 className="h-4 w-4" />}
        />
      </div>

      {/* Self-cure baseline */}
      {summary.self_cure_count > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800/80 bg-slate-900/40 px-5 py-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-400">
              <TrendingUp className="h-3.5 w-3.5" />
            </span>
            <span className="text-xs font-semibold text-slate-200">Self-cure baseline</span>
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
            <span className="text-[11px] text-slate-400 num">
              {summary.self_cure_count} cases ({formatPercent(summary.self_cure_rate)}) recovered organically
            </span>
            <span className="text-[11px] font-semibold text-emerald-400 num">
              +{formatPercent(summary.lift_over_self_cure)} lift from recovery engine
            </span>
          </div>
        </div>
      )}

      {/* Pipeline & Flow */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <SectionCard
          className="lg:col-span-2"
          label="Pipeline"
          title="Recovery flow"
          subtitle="Entered → active/promised → verified recovered. Only captured payments count."
          bodyClassName="px-4 py-5"
        >
          <div className="max-w-lg">
            <RecoveryFunnel stages={funnel} formatAmount={money} />
          </div>
          <div className="mt-5 flex items-center justify-between border-t border-slate-800/70 pt-3 text-xs">
            <span className="text-slate-500">Yield from at-risk pool</span>
            <span className="font-semibold text-emerald-400 num">
              {formatPercent(map.recovery_rate)}
            </span>
          </div>
        </SectionCard>

        <SectionCard
          label="Attention"
          title="Requires attention"
          subtitle={`${needsAttention.length} open cases`}
          action={
            <Link
              to="/cases"
              className="text-xs font-medium text-slate-400 transition-colors hover:text-slate-100"
            >
              View all →
            </Link>
          }
          bodyClassName="p-0"
        >
          <AttentionTable cases={needsAttention} maxRows={5} />
        </SectionCard>
      </div>

      {/* Row: cumulative timeline + channel mix */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Cumulative recovery over time"
            subtitle="Verified captured revenue after a payment failure enters recovery."
          />
          <div className="h-56">
            <RecoveryAreaChart data={map.recovery_timeline} formatFull={moneyFull} />
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Operating cadence"
            subtitle="Work standing across the ledger."
            action={
              <Link to="/plans" className="text-xs font-medium text-slate-400 hover:text-slate-100">
                Manage plans →
              </Link>
            }
          />
          <div className="space-y-2">
            <CadenceStat
              label="Active recoveries"
              value={`${openCaseCount}`}
              sub="Cases in progress"
            />
            <CadenceStat
              label="Pending promises"
              value={`${cases.filter((c) => c.status === "PROMISED").length}`}
              sub="Awaiting payment"
            />
            <CadenceStat
              label="Payment plans"
              value={`${map.payment_plan_recovery.plans_count}`}
              sub={`${money(map.payment_plan_recovery.total_amount)} total`}
            />
            <CadenceStat
              label="Failed payments"
              value={`${map.cases_count}`}
              sub="Total entering recovery"
            />
          </div>
        </Card>
      </div>

      {/* Recently recovered — dense ledger */}
      <SectionCard
        label="Ledger"
        title="Recently recovered"
        subtitle="Money captured in the last completed cases."
        action={
          <Link to="/cases" className="text-xs font-medium text-slate-400 hover:text-slate-100">
            Manage cases →
          </Link>
        }
        bodyClassName="p-0"
      >
        <RecentRecoveries cases={recentRecovered} maxRows={6} />
      </SectionCard>
    </div>
  )
}

function CadenceStat({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub: string
}) {
  return (
    <div className="rounded-lg border border-slate-800/70 bg-slate-900/40 p-4">
      <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-1.5 text-xl font-semibold tabular-nums tracking-tight text-slate-100">
        {value}
      </p>
      <p className="mt-0.5 text-xs text-slate-500">{sub}</p>
    </div>
  )
}

const RecoveryAreaChart = memo(function RecoveryAreaChart({
  data,
  formatFull,
}: {
  data: { label: string; recovered: number; cumulative: number }[]
  formatFull: (amount: number) => string
}) {
  const clamped = useMemo(() => {
    return data.filter((d) => d.label <= TODAY_ISO)
  }, [data])
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={clamped} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="dashGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#34d399" stopOpacity={0.28} />
            <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis
          dataKey="label"
          tick={CHART_TICK}
          axisLine={{ stroke: "#334155" }}
          tickLine={false}
          minTickGap={20}
          domain={["dataMin", TODAY_ISO]}
          tickFormatter={(v: string) => {
            const d = new Date(`${v}T00:00:00`)
            if (Number.isNaN(d.getTime())) return v
            return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })
          }}
        />
        <YAxis
          tick={CHART_TICK_Y}
          axisLine={{ stroke: "#334155" }}
          tickLine={false}
          tickFormatter={(v: number) => formatFull(v)}
          width={76}
        />
        <Tooltip content={<TimelineTooltip />} />
        <Area
          type="monotone"
          dataKey="cumulative"
          name="Recovered"
          stroke="#34d399"
          strokeWidth={2}
          fill="url(#dashGrad)"
          dot={false}
          isAnimationActive={false}
        />
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
  const dateLabel = (() => {
    const parsed = new Date(`${d.label}T00:00:00`)
    if (Number.isNaN(parsed.getTime())) return d.label
    return parsed.toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  })()
  return (
    <div style={TOOLTIP_STYLE} className="rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="mb-1.5 font-semibold text-slate-200">{dateLabel}</p>
      <p className="flex items-center justify-between gap-5">
        <span className="text-slate-400">Recovered</span>
        <span className="font-medium tabular-nums text-emerald-300">
          {formatFullMoney(d.cumulative)}
        </span>
      </p>
    </div>
  )
}
