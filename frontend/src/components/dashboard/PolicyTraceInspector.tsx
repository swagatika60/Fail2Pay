import { useEffect, useState } from "react"
import type { PolicyTrace, PolicyTraceNode } from "../../types/analytics"
import { fetchCasePolicyTrace } from "../../services/analytics"
import { formatCurrency } from "./MetricCard"
import {
  Brain,
  Info,
  ScrollText,
  SendHorizonal,
  Target,
  X,
  Zap,
} from "lucide-react"

const LAYER_META: Record<
  PolicyTraceNode["layer"],
  { label: string; icon: typeof Zap; color: string; note: string }
> = {
  trigger: {
    label: "Trigger",
    icon: Zap,
    color: "bg-red-500/15 text-red-400 border-red-500/30",
    note: "Initiating failed-payment event",
  },
  ai_judgment: {
    label: "AI Judgment",
    icon: Brain,
    color: "bg-purple-500/15 text-purple-400 border-purple-500/30",
    note: "Bounded intent classification — never decides actions",
  },
  policy: {
    label: "Policy Layer",
    icon: ScrollText,
    color: "bg-blue-500/15 text-blue-400 border-blue-500/30",
    note: "Deterministic rules — hard stops can never be overridden",
  },
  action: {
    label: "Action Dispatched",
    icon: SendHorizonal,
    color: "bg-green-500/15 text-green-400 border-green-500/30",
    note: "What the system actually did",
  },
  outcome: {
    label: "Outcome",
    icon: Target,
    color: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    note: "Verified result incl. money recovered",
  },
}

const LAYER_ORDER: PolicyTraceNode["layer"][] = [
  "trigger",
  "ai_judgment",
  "policy",
  "action",
  "outcome",
]

interface Props {
  caseId: string
  onClose: () => void
}

export default function PolicyTraceInspector({ caseId, onClose }: Props) {
  const [trace, setTrace] = useState<PolicyTrace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<PolicyTraceNode | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchCasePolicyTrace(caseId)
      .then((data) => setTrace(data))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setLoading(false))
  }, [caseId])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="my-8 w-full max-w-3xl rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 p-5">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-bold text-slate-100">
              <Brain className="w-5 h-5 text-indigo-400" />
              Agent Reasoning &amp; Policy Trace
            </h2>
            <p className="mt-0.5 text-xs text-slate-400">
              Full decision chain — why each step was taken, layer by layer
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto p-5">
          {loading && (
            <div className="flex items-center justify-center py-16">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-red-800 bg-red-900/20 p-4 text-sm text-red-400">
              {error}
            </div>
          )}

          {!loading && !error && trace && (
            <div className="space-y-6">
              {/* Money summary */}
              <div className="grid grid-cols-3 gap-3 text-center">
                <SummaryBox
                  label="Original"
                  value={formatCurrency(trace.original_amount)}
                  className="text-slate-100"
                />
                <SummaryBox
                  label="Verified Recovered"
                  value={formatCurrency(trace.recovered_amount)}
                  className="text-green-400"
                />
                <SummaryBox
                  label="Outstanding"
                  value={formatCurrency(trace.remaining_amount)}
                  className="text-amber-400"
                />
              </div>

              {/* Layer counts */}
              <div className="flex flex-wrap gap-2">
                {LAYER_ORDER.map((layer) => {
                  const count = trace.layer_counts[layer] ?? 0
                  const meta = LAYER_META[layer]
                  if (count === 0) return null
                  return (
                    <span
                      key={layer}
                      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${meta.color}`}
                    >
                      <meta.icon className="w-3.5 h-3.5" /> {meta.label} · {count}
                    </span>
                  )
                })}
              </div>

              {/* Decision chain grouped by layer */}
              {LAYER_ORDER.map((layer) => {
                const nodes = trace.chain.filter((n) => n.layer === layer)
                if (nodes.length === 0) return null
                const meta = LAYER_META[layer]
                return (
                  <div key={layer}>
                    <div className="mb-2 flex items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold ${meta.color}`}
                      >
                        <meta.icon className="w-3.5 h-3.5" /> {meta.label}
                      </span>
                      <span className="text-[10px] text-slate-500">{meta.note}</span>
                    </div>
                    <div className="space-y-2">
                      {nodes.map((node) => (
                        <button
                          key={node.id}
                          onClick={() =>
                            setSelected(selected?.id === node.id ? null : node)
                          }
                          className={`w-full rounded-lg border px-4 py-3 text-left transition-colors ${
                            selected?.id === node.id
                              ? "border-slate-500 bg-slate-800"
                              : "border-slate-800 bg-slate-800/40 hover:bg-slate-800/70"
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-slate-200">
                                {node.event_type}
                              </span>
                              {node.result && (
                                <span
                                  className={`rounded px-1.5 py-0.5 text-[10px] ${
                                    ["success", "sent", "paid", "recovered"].includes(
                                      node.result,
                                    )
                                      ? "bg-green-900/30 text-green-400"
                                      : node.result === "failed" ||
                                          node.result === "error" ||
                                          node.result === "blocked"
                                        ? "bg-red-900/30 text-red-400"
                                        : "bg-slate-700 text-slate-300"
                                  }`}
                                >
                                  {node.result}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2 text-xs text-slate-500">
                              {node.amount_formatted && (
                                <span className="font-medium text-green-400">
                                  {node.amount_formatted}
                                </span>
                              )}
                              <span>{formatTime(node.timestamp)}</span>
                            </div>
                          </div>

                          {node.reason && (
                            <p className="mt-1 text-xs text-slate-400">
                              {node.reason}
                            </p>
                          )}

                          {selected?.id === node.id && (
                            <div className="mt-3 space-y-2 border-t border-slate-700 pt-3">
                              <MetaGrid meta={node.metadata} />
                              {node.new_value && (
                                <JsonBlock title="new_value" data={node.new_value} />
                              )}
                              {node.old_value && (
                                <JsonBlock title="old_value" data={node.old_value} />
                              )}
                            </div>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )
              })}

              {trace.chain.length === 0 && (
                <div className="rounded-lg bg-slate-800/40 p-6 text-center text-sm text-slate-500">
                  No decision events recorded for this case yet.
                </div>
              )}

              {/* Integrity note */}
              <div className="flex items-start gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 p-3 text-xs text-blue-400">
                <Info className="w-4 h-4 shrink-0 mt-0.5" />
                <span>
                  Only verified captured payments appear as recovered revenue.
                  AI is used solely for bounded intent detection — every policy and
                  hard-stop decision above is deterministic and cannot be overridden.
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function SummaryBox({
  label,
  value,
  className,
}: {
  label: string
  value: string
  className: string
}) {
  return (
    <div className="rounded-lg bg-slate-800/40 p-3">
      <p className="text-[10px] text-slate-500">{label}</p>
      <p className={`text-base font-bold ${className}`}>{value}</p>
    </div>
  )
}

function formatTime(dateStr: string | null): string {
  if (!dateStr) return ""
  return new Date(dateStr).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function MetaGrid({ meta }: { meta: Record<string, unknown> }) {
  const str = (key: string) => (meta[key] != null ? String(meta[key]) : "")
  const channel = str("channel")
  const language = str("language")
  return (
    <div className="grid grid-cols-2 gap-2 text-xs">
      {channel && <MetaItem label="Channel" value={channel} />}
      {language && (
        <MetaItem
          label="Tone / Language"
          value={
            language === "hi-en"
              ? "Hinglish"
              : language === "hi"
                ? "Hindi"
                : language === "or"
                  ? "Odia"
                  : language
          }
        />
      )}
      {str("action_type") && (
        <MetaItem label="Action Type" value={str("action_type")} />
      )}
      {str("intent") && <MetaItem label="Intent" value={str("intent")} />}
      {meta.confidence != null && (
        <MetaItem
          label="Confidence"
          value={(Number(str("confidence")) * 100).toFixed(0) + "%"}
        />
      )}
      {str("source") && <MetaItem label="Source" value={str("source")} />}
      {str("failure_reason") && (
        <MetaItem label="Failure Reason" value={str("failure_reason")} />
      )}
      {str("stop_condition") && (
        <MetaItem label="Stop Condition" value={str("stop_condition")} />
      )}
      {str("strategy") && <MetaItem label="Strategy" value={str("strategy")} />}
      {str("scheduled_for") && (
        <MetaItem label="Scheduled For" value={str("scheduled_for")} />
      )}
    </div>
  )
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-900/50 px-2 py-1.5">
      <p className="text-[10px] text-slate-500">{label}</p>
      <p className="break-words text-slate-300">{value}</p>
    </div>
  )
}

function JsonBlock({ title, data }: { title: string; data: Record<string, unknown> }) {
  return (
    <div>
      <p className="mb-1 text-[10px] font-medium uppercase text-slate-500">{title}</p>
      <pre className="max-h-40 overflow-auto rounded bg-slate-950/60 p-2 text-[10px] text-slate-400">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}
