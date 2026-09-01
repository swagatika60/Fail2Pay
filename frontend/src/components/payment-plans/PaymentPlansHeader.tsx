import { useMemo } from "react"
import type { PaymentPlan } from "./types"
import {
  formatCompact,
  formatCurrencyFull,
  isPlanOpen,
  planAdherence,
} from "./types"

interface PaymentPlansHeaderProps {
  plans: PaymentPlan[]
}

interface KpiTile {
  label: string
  value: string
  sub: string
  tone: "ink" | "accent" | "warning" | "danger"
}

const TONE_TEXT: Record<KpiTile["tone"], string> = {
  ink: "text-slate-100",
  accent: "text-emerald-400",
  warning: "text-amber-400",
  danger: "text-rose-400",
}

function Tile({ tile }: { tile: KpiTile }) {
  return (
    <div className="px-5 py-4 md:px-6 md:py-5">
      <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {tile.label}
      </p>
      <p
        className={`mt-1.5 font-mono text-xl font-semibold tabular-nums tracking-tight md:text-2xl ${TONE_TEXT[tile.tone]}`}
      >
        {tile.value}
      </p>
      <p className="mt-1 truncate text-[11px] text-slate-500">{tile.sub}</p>
    </div>
  )
}

export default function PaymentPlansHeader({
  plans,
}: PaymentPlansHeaderProps) {
  const kpis = useMemo<KpiTile[]>(() => {
    const open = plans.filter(isPlanOpen)
    const atRiskCapital = open.reduce(
      (s, p) => s + p.progress.remainingAmountPaise,
      0,
    )
    const openRecovered = open.reduce((s, p) => s + p.amountPaidPaise, 0)
    const openPlanned = open.reduce((s, p) => s + p.totalAmountPaise, 0)
    const openRate =
      openPlanned > 0 ? (openRecovered / openPlanned) * 100 : 0

    const activeCount = plans.filter(
      (p) => p.status === "ACTIVE" || p.status === "ACCEPTED",
    ).length
    const proposedCount = plans.filter((p) => p.status === "PROPOSED").length

    const adherenceValues = open
      .map(planAdherence)
      .filter((v): v is number => v !== null)
    const avgAdherence =
      adherenceValues.length > 0
        ? adherenceValues.reduce((s, v) => s + v, 0) / adherenceValues.length
        : null

    return [
      {
        label: "Total At-Risk Capital",
        value: formatCurrencyFull(atRiskCapital),
        sub: `outstanding across ${open.length} open plans`,
        tone: "ink" as const,
      },
      {
        label: "Active Recovered Volume",
        value: formatCurrencyFull(openRecovered),
        sub: `${openRate.toFixed(1)}% of open plan value recovered`,
        tone: "accent" as const,
      },
      {
        label: "Active Plans",
        value: String(activeCount),
        sub: `${proposedCount} proposed · ${Math.max(0, open.length - activeCount)} pending acceptance`,
        tone: "ink" as const,
      },
      {
        label: "Avg Installment Adherence",
        value: avgAdherence === null ? "—" : `${avgAdherence.toFixed(1)}%`,
        sub:
          avgAdherence === null
            ? "no settled legs yet"
            : "paid legs ÷ settled legs across open plans",
        tone: "warning" as const,
      },
    ]
  }, [plans])

  const band = useMemo(() => {
    const totalPlanned = plans.reduce((s, p) => s + p.totalAmountPaise, 0)
    if (totalPlanned <= 0) return null

    const collected = plans.reduce((s, p) => s + p.amountPaidPaise, 0)
    const openRemaining = plans
      .filter(isPlanOpen)
      .reduce((s, p) => s + p.progress.remainingAmountPaise, 0)
    const defaulted = plans
      .filter((p) => p.status === "DEFAULTED")
      .reduce((s, p) => s + p.progress.remainingAmountPaise, 0)
    const netClosed =
      plans
        .filter((p) => p.status === "COMPLETED")
        .reduce((s, p) => s + p.amountPaidPaise, 0) +
      plans
        .filter((p) => p.status === "CANCELLED")
        .reduce((s, p) => s + p.amountPaidPaise, 0)

    const pct = (v: number) => Math.min(100, (v / totalPlanned) * 100)
    return {
      collected,
      openRemaining,
      defaulted,
      netClosed,
      collectedPct: pct(collected),
      openPct: pct(openRemaining),
      defaultedPct: pct(defaulted),
      closedPct: pct(netClosed),
      rate: (collected / totalPlanned) * 100,
      totalPlanned,
    }
  }, [plans])

  return (
    <div className="panel overflow-hidden rounded-xl bg-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-edge px-5 py-4 md:px-6">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">
            Revenue Recovery · Installment Portfolio
          </p>
          <h1 className="mt-0.5 text-xl font-bold tracking-tight text-slate-100 md:text-2xl">
            Payment Plans
          </h1>
        </div>
        <div className="flex items-center gap-4 text-[11px] text-slate-500">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Live portfolio
          </span>
          <span className="font-mono tabular-nums">
            {plans.length} plan{plans.length === 1 ? "" : "s"} loaded
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 divide-y divide-edge sm:grid-cols-2 lg:grid-cols-4 lg:divide-y-0 lg:divide-x">
        {kpis.map((tile) => (
          <Tile key={tile.label} tile={tile} />
        ))}
      </div>

      {band && (
        <div className="border-t border-edge px-5 py-4 md:px-6">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Portfolio recovery progress
            </p>
            <p className="font-mono text-xs tabular-nums text-emerald-400">
              {formatCompact(band.collected)} /{" "}
              {formatCompact(band.totalPlanned)} · {band.rate.toFixed(1)}%
            </p>
          </div>
          <div className="flex h-2 overflow-hidden rounded-full bg-slate-800/50">
            <div
              className="h-full bg-emerald-500/80 transition-all"
              style={{ width: `${band.collectedPct}%` }}
            />
            <div
              className="h-full bg-slate-300/30 transition-all"
              style={{ width: `${band.openPct}%` }}
            />
            <div
              className="h-full bg-rose-500/70 transition-all"
              style={{ width: `${band.defaultedPct}%` }}
            />
            <div
              className="h-full bg-slate-700/60 transition-all"
              style={{ width: `${band.closedPct}%` }}
            />
          </div>
          <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-500">
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500/80" />
              Collected ·{" "}
              <span className="font-mono tabular-nums text-slate-300">
                {formatCompact(band.collected)}
              </span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-slate-300/30" />
              Open outstanding ·{" "}
              <span className="font-mono tabular-nums text-slate-300">
                {formatCompact(band.openRemaining)}
              </span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-500/70" />
              Defaulted ·{" "}
              <span className="font-mono tabular-nums text-slate-300">
                {formatCompact(band.defaulted)}
              </span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-slate-700/60" />
              Closed (completed/cancelled)
            </span>
          </div>
        </div>
      )}
    </div>
  )
}