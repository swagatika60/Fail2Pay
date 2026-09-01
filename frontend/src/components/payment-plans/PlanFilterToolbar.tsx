import type {
  PaymentPlan,
  PlanPreset,
  PlanSortDir,
  PlanSortKey,
} from "./types"

const SORT_OPTIONS: { key: PlanSortKey; label: string }[] = [
  { key: "total", label: "Total amount" },
  { key: "recovery", label: "Recovery %" },
  { key: "nextLeg", label: "Next installment" },
  { key: "risk", label: "Risk score" },
]

const PRESETS: { key: PlanPreset; label: string }[] = [
  { key: "all", label: "All" },
  { key: "needs_action", label: "Needs action" },
  { key: "on_track", label: "On track" },
]

const STATUS_TABS: { key: string; label: string }[] = [
  { key: "all", label: "All" },
  { key: "ACTIVE", label: "Active" },
  { key: "ACCEPTED", label: "Accepted" },
  { key: "PROPOSED", label: "Proposed" },
  { key: "COMPLETED", label: "Completed" },
  { key: "DEFAULTED", label: "Defaulted" },
  { key: "CANCELLED", label: "Cancelled" },
]

export function matchesPreset(plan: PaymentPlan, preset: PlanPreset): boolean {
  if (preset === "all") return true
  if (preset === "needs_action") {
    return (
      plan.status === "DEFAULTED" ||
      plan.degradation.degraded ||
      plan.installmentsFailed > 0
    )
  }
  // on_track: open, no degradation, no failed legs.
  return (
    (plan.status === "ACTIVE" || plan.status === "ACCEPTED") &&
    !plan.degradation.degraded &&
    plan.installmentsFailed === 0
  )
}

interface PlanFilterToolbarProps {
  plans: PaymentPlan[]
  status: string
  onStatusChange: (status: string) => void
  preset: PlanPreset
  onPresetChange: (preset: PlanPreset) => void
  query: string
  onQueryChange: (query: string) => void
  sortKey: PlanSortKey
  sortDir: PlanSortDir
  onSortChange: (sortKey: PlanSortKey, sortDir: PlanSortDir) => void
  shownCount: number
  onReset: () => void
}

interface SortArrowProps {
  dir: PlanSortDir
}

function SortArrow({ dir }: SortArrowProps) {
  return (
    <svg
      className={`h-3.5 w-3.5 transition-transform ${
        dir === "desc" ? "rotate-180" : ""
      }`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 5v14M19 12l-7 7-7-7" />
    </svg>
  )
}

export default function PlanFilterToolbar({
  plans,
  status,
  onStatusChange,
  preset,
  onPresetChange,
  query,
  onQueryChange,
  sortKey,
  sortDir,
  onSortChange,
  shownCount,
  onReset,
}: PlanFilterToolbarProps) {
  const counts: Record<string, number> = { all: plans.length }
  for (const p of plans) counts[p.status] = (counts[p.status] ?? 0) + 1

  const filtersActive =
    status !== "all" || preset !== "all" || query.trim() !== ""

  return (
    <div className="panel-sub space-y-2.5 rounded-lg bg-panel-2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-0.5 rounded-md border border-edge bg-canvas p-0.5">
          {PRESETS.map((presetOpt) => {
            const active = preset === presetOpt.key
            return (
              <button
                key={presetOpt.key}
                onClick={() => onPresetChange(presetOpt.key)}
                className={`rounded px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  active
                    ? "bg-slate-200/10 text-slate-200"
                    : "text-slate-500 hover:text-slate-300"
                }`}
              >
                {presetOpt.label}
              </button>
            )
          })}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="relative">
            <svg
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
            >
              <path d="M21 21l-4.35-4.35M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              placeholder="Search customer, email, phone…"
              className="w-44 rounded-md border border-edge bg-canvas py-1.5 pl-8 pr-3 text-[13px] text-slate-200 placeholder:text-slate-600 focus:border-slate-500/70 focus:outline-none md:w-56"
            />
          </div>

          <div className="flex items-center gap-0.5 rounded-md border border-edge bg-canvas p-0.5">
            <select
              value={sortKey}
              onChange={(e) =>
                onSortChange(e.target.value as PlanSortKey, sortDir)
              }
              className="cursor-pointer appearance-none bg-transparent py-1 pl-2.5 pr-1 text-[11px] font-medium text-slate-400 focus:outline-none"
            >
              {SORT_OPTIONS.map((opt) => (
                <option
                  key={opt.key}
                  value={opt.key}
                  className="bg-canvas text-slate-200"
                >
                  Sort · {opt.label}
                </option>
              ))}
            </select>
            <button
              onClick={() =>
                onSortChange(sortKey, sortDir === "asc" ? "desc" : "asc")
              }
              aria-label="Toggle sort direction"
              className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-200/10 hover:text-slate-200"
            >
              <SortArrow dir={sortDir} />
            </button>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {STATUS_TABS.map((tab) => {
          const active = status === tab.key
          const count = counts[tab.key] ?? 0
          return (
            <button
              key={tab.key}
              onClick={() => onStatusChange(tab.key)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                active
                  ? "border-slate-500/50 bg-slate-200/10 text-slate-200"
                  : "border-edge bg-canvas text-slate-500 hover:border-slate-600/50 hover:text-slate-300"
              }`}
            >
              {tab.label}
              <span
                className={`rounded px-1 font-mono text-[10px] tabular-nums ${
                  active
                    ? "bg-slate-200/15 text-slate-200"
                    : "bg-slate-800/80 text-slate-500"
                }`}
              >
                {count}
              </span>
            </button>
          )
        })}

        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono text-[11px] tabular-nums text-slate-500">
            {shownCount} shown
          </span>
          {filtersActive && (
            <button
              onClick={onReset}
              className="rounded-md border border-edge px-2 py-1 text-[11px] font-medium text-slate-400 transition-colors hover:border-slate-600/50 hover:text-slate-200"
            >
              Reset
            </button>
          )}
        </div>
      </div>
    </div>
  )
}