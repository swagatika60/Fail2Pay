import type { RecoveryTimeline as TimelineData } from "../../types/analytics"
import { formatCurrency } from "./MetricCard"
import { Info, Activity, GitCommit } from "lucide-react"

interface RecoveryTimelineProps {
  timeline: TimelineData | null
  loading: boolean
}

function formatTimeOnly(dateStr: string | null): string {
  if (!dateStr) return ""
  return new Date(dateStr).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return ""
  return new Date(dateStr).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

const COLOR_MAP: Record<string, { bg: string; border: string; dot: string }> = {
  red: { bg: "bg-red-500/10", border: "border-red-500/30", dot: "bg-red-500" },
  amber: { bg: "bg-amber-500/10", border: "border-amber-500/30", dot: "bg-amber-500" },
  blue: { bg: "bg-blue-500/10", border: "border-blue-500/30", dot: "bg-blue-500" },
  indigo: { bg: "bg-indigo-500/10", border: "border-indigo-500/30", dot: "bg-indigo-500" },
  slate: { bg: "bg-slate-500/10", border: "border-slate-500/30", dot: "bg-slate-500" },
  gray: { bg: "bg-gray-500/10", border: "border-gray-500/30", dot: "bg-gray-500" },
  green: { bg: "bg-green-500/10", border: "border-green-500/30", dot: "bg-green-500" },
  cyan: { bg: "bg-cyan-500/10", border: "border-cyan-500/30", dot: "bg-cyan-500" },
  purple: { bg: "bg-purple-500/10", border: "border-purple-500/30", dot: "bg-purple-500" },
}

export default function RecoveryTimeline({
  timeline,
  loading,
}: RecoveryTimelineProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
      </div>
    )
  }

  if (!timeline) {
    return (
      <div className="rounded-lg bg-slate-800/50 p-4 text-center text-sm text-slate-500">
        No timeline data
      </div>
    )
  }

  const { case: caseInfo, timeline: events, summary } = timeline

  return (
    <div className="space-y-6">
      {/* Case Summary Header */}
      <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-medium text-slate-200 flex items-center gap-2">
            <Info className="w-4 h-4 text-slate-400" />
            Case Summary
          </h3>
          <span
            className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
              caseInfo.status === "RECOVERED"
                ? "bg-green-500/20 text-green-400"
                : caseInfo.status === "STOPPED"
                  ? "bg-red-500/20 text-red-400"
                  : "bg-amber-500/20 text-amber-400"
            }`}
          >
            {caseInfo.status.replace(/_/g, " ")}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
          <div>
            <span className="text-slate-500">Customer: </span>
            <span className="text-slate-200">{caseInfo.customer_name}</span>
          </div>
          <div>
            <span className="text-slate-500">Risk: </span>
            <span
              className={
                caseInfo.risk_level === "HIGH"
                  ? "text-red-400"
                  : caseInfo.risk_level === "MEDIUM"
                    ? "text-yellow-400"
                    : "text-green-400"
              }
            >
              {caseInfo.risk_level}
            </span>
          </div>
          <div>
            <span className="text-slate-500">Original: </span>
            <span className="text-slate-200">
              {formatCurrency(caseInfo.original_amount)}
            </span>
          </div>
          <div>
            <span className="text-slate-500">Recovered: </span>
            <span className="text-green-400">
              {formatCurrency(caseInfo.recovered_amount)}
            </span>
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <div className="rounded-lg bg-slate-800/30 p-3 text-center">
          <div className="text-lg font-bold text-slate-100">
            {summary.total_events}
          </div>
          <div className="text-[10px] text-slate-500">Total Events</div>
        </div>
        <div className="rounded-lg bg-slate-800/30 p-3 text-center">
          <div className="text-lg font-bold text-green-400">
            {summary.messages_sent}
          </div>
          <div className="text-[10px] text-slate-500">Messages Sent</div>
        </div>
        <div className="rounded-lg bg-slate-800/30 p-3 text-center">
          <div className="text-lg font-bold text-cyan-400">
            {summary.customer_replies}
          </div>
          <div className="text-[10px] text-slate-500">Customer Replies</div>
        </div>
        <div className="rounded-lg bg-slate-800/30 p-3 text-center">
          <div className="text-lg font-bold text-amber-400">
            {summary.messages_failed}
          </div>
          <div className="text-[10px] text-slate-500">Failed Messages</div>
        </div>
        <div className="rounded-lg bg-slate-800/30 p-3 text-center">
          <div className="text-lg font-bold text-green-400">
            {Math.round(summary.recovery_rate * 100)}%
          </div>
          <div className="text-[10px] text-slate-500">Recovery Rate</div>
        </div>
      </div>

      {/* Timeline */}
      <div>
        <h3 className="mb-3 text-sm font-medium text-slate-200 flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyan-400" />
          Recovery Timeline ({events.length}{" "}
          {events.length === 1 ? "event" : "events"})
        </h3>

        {events.length === 0 ? (
          <div className="rounded-lg bg-slate-800/50 p-4 text-center text-sm text-slate-500">
            No events recorded
          </div>
        ) : (
          <div className="relative ml-4 border-l-2 border-slate-700 pl-6">
            {events.map((event, index) => {
              const colors = COLOR_MAP[event.color] || COLOR_MAP.slate
              const prevEvent = events[index - 1]
              const showDateSeparator =
                !prevEvent ||
                formatDate(event.timestamp) !== formatDate(prevEvent.timestamp)

              return (
                <div key={event.id}>
                  {/* Date separator */}
                  {showDateSeparator && (
                    <div className="mb-4 ml-[-2.75rem] flex items-center gap-2">
                      <div className="h-3 w-3 rounded-full border-2 border-slate-600 bg-slate-900" />
                      <span className="text-xs font-medium text-slate-400">
                        {formatDate(event.timestamp)}
                      </span>
                    </div>
                  )}

                  {/* Event */}
                  <div className="relative mb-4">
                    {/* Dot on timeline */}
                    <div
                      className={`absolute -left-[2.75rem] top-1 h-3 w-3 rounded-full ${colors.dot}`}
                    />

                    {/* Event card */}
                    <div
                      className={`rounded-lg border ${colors.border} ${colors.bg} p-3`}
                    >
                      <div className="mb-1 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center gap-1.5 font-mono text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                            <GitCommit className="w-3 h-3 text-cyan-400" />
                            {event.entity_type}
                          </span>
                          <span className="text-sm font-medium text-slate-200">
                            {event.description}
                          </span>
                        </div>
                        <span className="text-[10px] text-slate-500">
                          {formatTimeOnly(event.timestamp)}
                        </span>
                      </div>

                      {event.reason && (
                        <p className="mb-1 text-xs text-slate-400">
                          {event.reason}
                        </p>
                      )}

                      <div className="flex flex-wrap gap-2 text-[10px] text-slate-500">
                        {event.result && (
                          <span
                            className={`rounded px-1.5 py-0.5 ${
                              event.result === "success" || event.result === "sent" || event.result === "paid" || event.result === "recovered"
                                ? "bg-green-900/30 text-green-400"
                                : event.result === "failed" || event.result === "error"
                                  ? "bg-red-900/30 text-red-400"
                                  : "bg-slate-900/50 text-slate-400"
                            }`}
                          >
                            {event.result}
                          </span>
                        )}
                        {event.amount_formatted && (
                          <span className="rounded bg-slate-900/50 px-1.5 py-0.5 text-green-400">
                            {event.amount_formatted}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
