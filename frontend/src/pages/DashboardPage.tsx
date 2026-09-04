import { memo, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Zap, TrendingUp, ShieldAlert, Clock3, Info } from "lucide-react"
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
import type { RecoveryCaseSummary } from "../types/analytics"
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

  // ------------------------------------------------------------------
  // Active-case definitions (reconciled):
  //   open          = any OPEN_STATUSES case
  //   open backlog  = open case with ZERO attempts (never contacted)
  //   engaged       = open case recovery has actually touched (attempts,
  //                   captured money, promise, plan, …)
  // The two buckets always add back up to the open count, so the KPI
  // cards, cadence panel and pipeline never disagree about "active".
  // ------------------------------------------------------------------
  const openCases = useMemo(
    () => cases.filter((c) => OPEN_STATUSES.has(c.status)),
    [cases],
  )
  const openCaseCount = openCases.length

  const backlogCases = useMemo(
    () =>
      openCases.filter(
        (c) => (c.attempt_count ?? 0) === 0 && (c.recovered_amount ?? 0) === 0,
      ),
    [openCases],
  )
  const engagedCases = useMemo(
    () => openCases.filter((c) => !backlogCases.includes(c)),
    [openCases, backlogCases],
  )

  const sumOf = (list: RecoveryCaseSummary[], pick: (c: RecoveryCaseSummary) => number) =>
    list.reduce((acc, c) => acc + (pick(c) || 0), 0)
  const backlogRemaining = useMemo(
    () => sumOf(backlogCases, (c) => c.remaining_amount),
    [backlogCases],
  )
  const engagedRemaining = useMemo(
    () => sumOf(engagedCases, (c) => c.remaining_amount),
    [engagedCases],
  )

  const backlogCount = backlogCases.length
  const engagedCount = engagedCases.length

  // Pipeline sub-populations (money-matched): the attempted pool is every
  // case the engine engaged (attempts or a captured payment); the verified
  // pool is every case that holds at least one captured payment.
  const attemptedCaseCount = useMemo(
    () =>
      cases.filter(
        (c) => (c.attempt_count ?? 0) > 0 || (c.recovered_amount ?? 0) > 0,
      ).length,
    [cases],
  )
  const paidCaseCount = useMemo(
    () => cases.filter((c) => (c.recovered_amount ?? 0) > 0).length,
    [cases],
  )

  // Sparklines ----------------------------------------------------------
  // Verified cumulative capture (ascending green) for the recovered card.
  const sparkSeries = useMemo(() => {
    const ts = (map?.recovery_timeline ?? []).filter(
      (d) => d.label <= TODAY_ISO,
    )
    return {
      cumulative: ts.map((d) => d.cumulative),
    }
  }, [map])

  // 7-day rolling average of daily verified capture volume — a meaningful
  // trend line instead of the raw day-to-day spikes.
  const rollingRecovered = useMemo(() => {
    const daily = (map?.recovery_timeline ?? [])
      .filter((d) => d.label <= TODAY_ISO)
      .map((d) => d.recovered)
    if (daily.length < 2) return []
    const out: number[] = []
    for (let i = 0; i < daily.length; i++) {
      const from = Math.max(0, i - 6)
      const window = daily.slice(from, i + 1)
      out.push(window.reduce((a, b) => a + b, 0) / window.length)
    }
    return out
  }, [map])

  // At-risk exposure accrual: cumulative original volume of failures as
  // they arrived (stepped). Deliberately NOT the recovery curve — this
  // reads as the growing backlog of exposure, not money coming back.
  const riskSeries = useMemo(() => {
    const byDay = new Map<string, number>()
    for (const c of cases) {
      const day = (c.created_at || "").slice(0, 10)
      if (!day) continue
      byDay.set(day, (byDay.get(day) ?? 0) + (c.original_amount || 0))
    }
    const days = [...byDay.keys()].sort()
    let acc = 0
    return days.map((day) => {
      acc += byDay.get(day) ?? 0
      return acc
    })
  }, [cases])

  // Conversion funnel: nested money pools so stage-to-stage conversion is a
  // genuine 0-100% rate. Total failed volume → pool the engine engaged →
  // verified captured money. Promises/plans live in the cadence panel.
  const funnel = useMemo<FunnelStage[]>(() => {
    if (!map) return []
    return [
      {
        key: "failed",
        label: "Total failed volume",
        amount: map.total_revenue,
        count: map.cases_count ?? 0,
        tone: "slate",
      },
      {
        key: "engaged",
        label: "Engaged / In recovery",
        amount: map.attempted_recovery,
        count: attemptedCaseCount,
        tone: "amber",
      },
      {
        key: "recovered",
        label: "Verified recovered",
        amount: map.recovered_revenue,
        count: paidCaseCount,
        tone: "emerald",
      },
    ]
  }, [map, attemptedCaseCount, paidCaseCount])

  const navigate = useNavigate()
  const triggerMockFailureWebhook = async () => {
    const base = Math.max(map?.at_risk_revenue ?? 0, 500000)
    const amount = Math.round(base * 0.1) + Math.floor(Math.random() * 300000)
    const caseId = await simulatePaymentFailure(amount)
    // Navigate to the newly created case if we got a real case ID
    if (caseId) navigate(`/case/${caseId}`)
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
          context={`${map.payments_count} captured payments · ${paidCaseCount} recovered cases`}
          hint={`Verified captured revenue (${money(map.recovered_revenue)}) across ${map.payments_count} captured payments. Messages and promises are never counted.`}
          spark={sparkSeries.cumulative}
          icon={<TrendingUp className="h-4 w-4" />}
          tone="emerald"
        />
        <MetricCard
          label="Recovery rate"
          value={formatPercent(map.recovery_rate)}
          delta={rateDelta}
          context={`${money(map.recovered_revenue)} captured of ${money(map.total_revenue)} failed`}
          hint={`Recovery rate = verified recovered (${money(map.recovered_revenue)}) ÷ total failed volume (${money(map.total_revenue)}). Sparkline shows the 7-day rolling average of daily verified capture volume.`}
          spark={rollingRecovered}
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <MetricCard
          label="Revenue at risk"
          value={money(map.at_risk_revenue)}
          delta={{ direction: "flat", label: `${openCaseCount} open · ${backlogCount} unengaged`, favorable: false }}
          context={`${backlogCount} unengaged (${money(backlogRemaining)}) · ${engagedCount} in recovery (${money(engagedRemaining)})`}
          hint={`Open exposure split by engagement: ${backlogCount} unengaged (never contacted) and ${engagedCount} in recovery (outreach sent / in conversation). Sparkline shows cumulative failed volume as it arrived — not the recovery curve.`}
          spark={riskSeries}
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
          hint="Days from the failed payment to the first verified captured payment, averaged across recovered cases."
          icon={<Clock3 className="h-4 w-4" />}
        />
      </div>

      {/* Self-cure baseline — its own banner, visually separate from the KPIs */}
      {summary.self_cure_count > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2.5 rounded-xl border border-dashed border-emerald-800/40 bg-gradient-to-r from-emerald-950/50 via-emerald-950/20 to-transparent px-5 py-3.5">
          <div className="flex items-center gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-emerald-800/40 bg-emerald-900/30 text-emerald-400">
              <TrendingUp className="h-4 w-4" />
            </span>
            <div>
              <p className="text-xs font-semibold text-emerald-200">Self-cure baseline</p>
              <p className="text-[11px] text-slate-500">
                Cases that recovered organically — with zero outreach attempts.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
            <span className="text-[11px] text-slate-400 num">
              {summary.self_cure_count} cases ({formatPercent(summary.self_cure_rate)}) recovered organically
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-800/50 bg-emerald-900/20 px-2 py-1 font-mono text-[11px] font-semibold tabular-nums text-emerald-400">
              <Info className="h-3 w-3 cursor-help opacity-70" />
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
          subtitle="Total failed → engaged pool → verified captured. Stages are nested money pools, so each conversion is an honest share of the previous stage."
          bodyClassName="px-4 py-5"
        >
          <div className="max-w-lg">
            <RecoveryFunnel stages={funnel} formatAmount={money} />
          </div>
          <div className="mt-5 flex items-center justify-between border-t border-slate-800/70 pt-3 text-xs">
            <span className="flex items-center gap-1.5 text-slate-500">
              Recovery yield
              <span
                className="inline-flex cursor-help"
                aria-label={`Verified recovered (${money(map.recovered_revenue)}) ÷ total failed volume (${money(map.total_revenue)}) = ${formatPercent(map.recovery_rate)}`}
                title={`Verified recovered (${money(map.recovered_revenue)}) ÷ total failed volume (${money(map.total_revenue)}) = ${formatPercent(map.recovery_rate)}`}
              >
                <Info className="h-3 w-3 opacity-70 transition-opacity hover:opacity-100" />
              </span>
            </span>
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
            <RecoveryAreaChart data={map.recovery_timeline} formatCompact={money} />
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
              value={`${engagedCases.length}`}
              sub="Engaged — outreach sent / in conversation"
            />
            <CadenceStat
              label="Open backlog"
              value={`${backlogCases.length}`}
              sub="Unengaged — awaiting first touch"
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
              label="Total failed volume"
              value={`${map.cases_count}`}
              sub={`${money(map.total_revenue)} original`}
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
  formatCompact,
}: {
  data: { label: string; recovered: number; cumulative: number }[]
  formatCompact: (amount: number) => string
}) {
  const clamped = useMemo(() => {
    return data.filter((d) => d.label <= TODAY_ISO)
  }, [data])

  // Clean weekly ticks (e.g. "3 Jul, 10 Jul, 17 Jul") instead of a crowded
  // daily axis: one label every 7 days, anchored at the first data point,
  // with today's endpoint appended when it isn't already labelled.
  const weeklyTicks = useMemo(() => {
    if (clamped.length <= 8) return clamped.map((d) => d.label)
    const ticks: string[] = []
    for (let i = 0; i < clamped.length; i += 7) {
      ticks.push(clamped[i].label)
    }
    const last = clamped[clamped.length - 1].label
    const prev = ticks[ticks.length - 1]
    const gapDays =
      (Date.parse(last) - Date.parse(prev)) / (24 * 60 * 60 * 1000)
    if (Number.isFinite(gapDays) && gapDays > 3) ticks.push(last)
    return ticks
  }, [clamped])

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
          ticks={weeklyTicks}
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
          tickFormatter={(v: number) => formatCompact(v)}
          width={64}
        />
        <Tooltip content={<TimelineTooltip formatCompact={formatCompact} />} />
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
  formatCompact?: (amount: number) => string
}

function TimelineTooltip({ active, payload, formatCompact }: TimelineTooltipProps) {
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
  const compact = formatCompact ?? ((a: number) => formatFullMoney(a))
  return (
    <div style={TOOLTIP_STYLE} className="rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="mb-1.5 font-semibold text-slate-200">{dateLabel}</p>
      <p className="flex items-center justify-between gap-5">
        <span className="text-slate-400">Recovered</span>
        <span className="font-medium tabular-nums text-emerald-300">
          {compact(d.cumulative)}
        </span>
      </p>
    </div>
  )
}
