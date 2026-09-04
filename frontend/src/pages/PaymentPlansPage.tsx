import { useEffect, useMemo, useState } from "react"
import { CalendarDays } from "lucide-react"
import { fetchPaymentPlansList } from "../services/operations"
import type { PaymentPlan, PlanPreset, PlanSortDir, PlanSortKey } from "../components/payment-plans/types"
import { planRiskScore, toPaymentPlan } from "../components/payment-plans/types"
import { estimatedNextLegDue } from "../components/payment-plans/types"
import PaymentPlansHeader from "../components/payment-plans/PaymentPlansHeader"
import PlanFilterToolbar, { matchesPreset } from "../components/payment-plans/PlanFilterToolbar"
import PaymentPlanTable from "../components/payment-plans/PaymentPlanTable"
import { Card } from "../components/ui/Card"
import { EmptyState } from "../components/ui/EmptyState"
import { SkeletonTable } from "../components/ui/Skeleton"

const DEFAULT_SORT: PlanSortKey = "risk"
const DEFAULT_DIR: PlanSortDir = "desc"

function parseDate(value: string | null): number | null {
  if (!value) return null
  const t = Date.parse(value)
  return Number.isNaN(t) ? null : t
}

function comparePlans(
  a: PaymentPlan,
  b: PaymentPlan,
  key: PlanSortKey,
  dir: PlanSortDir,
): number {
  const mul = dir === "asc" ? 1 : -1
  switch (key) {
    case "total":
      return (a.totalAmountPaise - b.totalAmountPaise) * mul
    case "recovery":
      return (a.progress.percentPaid - b.progress.percentPaid) * mul
    case "nextLeg": {
      const va = parseDate(estimatedNextLegDue(a))
      const vb = parseDate(estimatedNextLegDue(b))
      if (va === null && vb === null) return 0
      if (va === null) return 1
      if (vb === null) return -1
      return (va - vb) * mul
    }
    case "risk":
      return (planRiskScore(a) - planRiskScore(b)) * mul
    default:
      return 0
  }
}

export default function PaymentPlansPage() {
  const [plans, setPlans] = useState<PaymentPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [status, setStatus] = useState<string>("all")
  const [preset, setPreset] = useState<PlanPreset>("all")
  const [query, setQuery] = useState("")
  const [sortKey, setSortKey] = useState<PlanSortKey>(DEFAULT_SORT)
  const [sortDir, setSortDir] = useState<PlanSortDir>(DEFAULT_DIR)

  useEffect(() => {
    let cancelled = false
    fetchPaymentPlansList()
      .then((data) => {
        if (!cancelled) setPlans(data.map(toPaymentPlan))
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "Failed to load payment plans",
          )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return plans
      .filter((p) => (status === "all" ? true : p.status === status))
      .filter((p) => matchesPreset(p, preset))
      .filter((p) => {
        if (!q) return true
        return (
          p.customer.name?.toLowerCase().includes(q) ||
          p.customer.email?.toLowerCase().includes(q) ||
          p.customer.phone?.toLowerCase().includes(q) ||
          p.id.toLowerCase().includes(q)
        )
      })
      .slice()
      .sort((a, b) => comparePlans(a, b, sortKey, sortDir))
  }, [plans, status, preset, query, sortKey, sortDir])

  const reset = () => {
    setStatus("all")
    setPreset("all")
    setQuery("")
    setSortKey(DEFAULT_SORT)
    setSortDir(DEFAULT_DIR)
  }

  return (
    <div className="space-y-4">
      {!loading && !error && <PaymentPlansHeader plans={plans} />}

      {!loading && !error && (
        <PlanFilterToolbar
          plans={plans}
          status={status}
          onStatusChange={setStatus}
          preset={preset}
          onPresetChange={setPreset}
          query={query}
          onQueryChange={setQuery}
          sortKey={sortKey}
          sortDir={sortDir}
          onSortChange={(key, dir) => {
            setSortKey(key)
            setSortDir(dir)
          }}
          shownCount={filtered.length}
          onReset={reset}
        />
      )}

      {loading ? (
        <Card className="panel p-3">
          <SkeletonTable rows={8} />
        </Card>
      ) : error ? (
        <Card className="panel p-8 text-center text-[13px] text-rose-400">
          {error}
        </Card>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={CalendarDays}
          title={
            plans.length === 0 ? "No payment plans yet" : "No plans match filters"
          }
          description={
            plans.length === 0
              ? "When a customer agrees to pay in installments, the plan shows up here with legs, mandates and retry status."
              : "Adjust the status, preset or search query to widen the view."
          }
        />
      ) : (
        <PaymentPlanTable plans={filtered} />
      )}
    </div>
  )
}