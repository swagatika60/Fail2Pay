import { Link } from "react-router-dom"
import { ArrowUpRight, ChevronRight } from "lucide-react"
import type { RecoveryCaseSummary } from "../../types/analytics"
import { caseMeta, riskMeta } from "../../lib/status"
import { formatINR, timeAgo, initials } from "../../lib/format"
import { Button } from "../ui/Button"

/** Compact human reference for a case (full UUID in the hover tooltip). */
function shortCaseId(id: string): string {
  return id.slice(0, 8)
}

/**
 * Dense, action-first feed of open cases. Each row links out to the case
 * workspace and exposes a primary quick action so recovery work stays
 * one click away from the dashboard.
 */
export function AttentionTable({
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
        No open cases require attention right now.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto px-5">
      <table className="w-full min-w-[620px] border-collapse text-left">
        <thead>
          <tr className="border-b border-slate-800/70">
            <th className="pb-2 pr-4 text-xs font-medium uppercase tracking-wider text-slate-500">
              Customer
            </th>
            <th className="pb-2 pr-4 text-xs font-medium uppercase tracking-wider text-slate-500">
              Case ID
            </th>
            <th className="pb-2 pr-4 text-right text-xs font-medium uppercase tracking-wider text-slate-500">
              Amount
            </th>
            <th className="pb-2 pr-4 text-xs font-medium uppercase tracking-wider text-slate-500">
              Status
            </th>
            <th className="pb-2 pr-4 text-xs font-medium uppercase tracking-wider text-slate-500">
              Risk
            </th>
            <th className="pb-2 text-right text-xs font-medium uppercase tracking-wider text-slate-500">
              Action
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const meta = caseMeta(c.status)
            const risk = riskMeta(c.risk_level)
            return (
              <tr
                key={c.id}
                className="group border-b border-slate-800/50 last:border-0"
              >
                <td className="py-2.5 pr-4">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-slate-700/60 bg-slate-800/60 text-[10px] font-semibold text-slate-300">
                      {initials(c.customer_name)}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate whitespace-nowrap text-sm font-medium text-slate-200">
                        {c.customer_name || "Unknown customer"}
                      </p>
                      <p className="text-[11px] text-slate-500">
                        updated {timeAgo(c.updated_at)}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="py-2.5 pr-4">
                  <Link
                    to={`/case/${c.id}`}
                    className="font-mono text-[11px] tabular-nums text-slate-500 transition-colors hover:text-slate-300"
                    title={`Case ${c.id}`}
                  >
                    #{shortCaseId(c.id)}
                  </Link>
                </td>
                <td className="py-2.5 pr-4 text-right text-sm font-semibold tabular-nums text-slate-100">
                  {formatINR(c.remaining_amount)}
                </td>
                <td className="py-2.5 pr-4">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] font-medium ${meta.badge}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
                    {meta.label}
                  </span>
                </td>
                <td className="py-2.5 pr-4">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] font-medium ${risk.badge}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${risk.dot}`} />
                    {risk.label}
                  </span>
                </td>
                <td className="py-2.5 text-right">
                  <div className="flex items-center justify-end gap-1.5 opacity-70 transition-opacity group-hover:opacity-100">
                    <Link to={`/case/${c.id}`}>
                      <Button variant="secondary" size="sm" className="h-7 px-2.5">
                        View
                        <ArrowUpRight className="h-3 w-3" />
                      </Button>
                    </Link>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 px-0"
                      aria-label={`Open ${c.customer_name || "case"} actions`}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
