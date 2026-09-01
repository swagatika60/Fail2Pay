import { useState } from "react"
import type { PaymentPlan } from "./types"
import PlanTableRow from "./PlanTableRow"

interface PaymentPlanTableProps {
  plans: PaymentPlan[]
}

function TableHead() {
  const base = "px-4 text-[10px] font-medium uppercase tracking-wider text-slate-600"
  return (
    <div className="grid grid-cols-12 items-center gap-x-3 gap-y-2 border-b border-edge bg-panel px-4 py-2">
      <span className={`${base} col-span-12 sm:col-span-6 lg:col-span-4`}>
        Customer
      </span>
      <span className={`${base} col-span-6 lg:col-span-3`}>Progress</span>
      <span className={`${base} col-span-6 lg:col-span-3`}>
        Schedule &amp; retry
      </span>
      <span className={`${base} col-span-12 text-right lg:col-span-2`}>
        Actions
      </span>
    </div>
  )
}

export default function PaymentPlanTable({ plans }: PaymentPlanTableProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const toggle = (id: string) =>
    setExpandedId((cur) => (cur === id ? null : id))

  return (
    <div className="panel overflow-hidden rounded-lg bg-panel">
      <TableHead />
      <div className="divide-y divide-edge">
        {plans.map((plan) => (
          <PlanTableRow
            key={plan.id}
            plan={plan}
            expanded={expandedId === plan.id}
            onToggle={() => toggle(plan.id)}
          />
        ))}
      </div>
    </div>
  )
}