import { Link } from "react-router-dom"
import { ArrowUpRight, CheckCircle2 } from "lucide-react"
import type { RecoveryCaseSummary } from "../../types/analytics"
import { caseMeta } from "../../lib/status"
import { formatINR, formatDate, initials } from "../../lib/format"
import { Button } from "../ui/Button"

/**
 * Compact table of the most recently verified recoveries. Renders as a dense
 * list (Customer + amount + recovered-on date + open affordance) that reads
 * like a ledger rather than disconnected cards.
 */
export function RecentRecoveries({
  cases,
  maxRows = 6,
}: {
  cases: RecoveryCaseSummary[]
  maxRows?: number
}) {
  const rows = cases.slice(0, maxRows)

  if (rows.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        No verified recoveries yet.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto px-5">
      <table className="w-full min-w-[480px] border-collapse text-left">
        <thead>
          <tr className="border-b border-slate-800/70">
            <th className="pb-2 pr-4 text-xs font-medium uppercase tracking-wider text-slate-500">
              Customer
            </th>
            <th className="pb-2 pr-4 text-right text-xs font-medium uppercase tracking-wider text-slate-500">
              Amount
            </th>
            <th className="pb-2 pr-4 text-xs font-medium uppercase tracking-wider text-slate-500">
              Status
            </th>
            <th className="pb-2 pr-4 text-xs font-medium uppercase tracking-wider text-slate-500">
              Recovered on
            </th>
            <th className="pb-2 text-right text-xs font-medium uppercase tracking-wider text-slate-500">
              Action
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const meta = caseMeta(c.status)
            return (
              <tr
                key={c.id}
                className="group border-b border-slate-800/50 last:border-0"
              >
                <td className="py-2.5 pr-4">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-emerald-500/20 bg-emerald-500/10 text-[10px] font-semibold text-emerald-300">
                      {initials(c.customer_name)}
                    </span>
                    <span className="truncate whitespace-nowrap text-sm font-medium text-slate-200">
                      {c.customer_name || "Unknown customer"}
                    </span>
                  </div>
                </td>
                <td className="py-2.5 pr-4 text-right">
                  <span className="flex items-center justify-end gap-1 text-sm font-semibold tabular-nums text-emerald-300">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400/70" />
                    {formatINR(c.recovered_amount)}
                  </span>
                </td>
                <td className="py-2.5 pr-4">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] font-medium ${meta.badge}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
                    {meta.label}
                  </span>
                </td>
                <td className="py-2.5 pr-4 text-xs text-slate-500">
                  {formatDate(c.updated_at)}
                </td>
                <td className="py-2.5 text-right">
                  <Link to={`/case/${c.id}`} className="inline-block">
                    <Button
                      variant="secondary"
                      size="sm"
                      className="h-7 opacity-70 transition-opacity group-hover:opacity-100"
                    >
                      View
                      <ArrowUpRight className="h-3 w-3" />
                    </Button>
                  </Link>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
