import { useMemo, type ReactNode } from "react"
import { Brain, Radar, ShieldCheck, Send, BookOpenCheck, Loader2, Terminal } from "lucide-react"
import type { AgentStep } from "../../types/analytics"
import type { LiveAgentStep } from "../../services/realtime"

/**
 * Agent Thought Stream — the live, ordered reasoning chain the autonomous
 * engine produced for a case:
 *
 *   [Trigger Received] → [Root Cause: …] → [Policy Check: …] →
 *   [Action Dispatched] → [Ledger Verified ★]
 *
 * Steps are merged from the persisted chain (fetched with the case detail) and
 * the live WebSocket stream (deduped by step_id), so the feed stays correct
 * across reloads and animates in real time.
 */

const STAGE_META: Record<string, { label: string; tint: string; rail: string; icon: ReactNode }> = {
  TRIGGER: {
    label: "Trigger",
    tint: "border-rose-500/20 bg-rose-500/10 text-rose-400",
    rail: "bg-rose-400",
    icon: <Radar className="h-3 w-3" />,
  },
  DIAGNOSIS: {
    label: "Diagnosis",
    tint: "border-violet-500/20 bg-violet-500/10 text-violet-400",
    rail: "bg-violet-400",
    icon: <Brain className="h-3 w-3" />,
  },
  POLICY: {
    label: "Policy",
    tint: "border-royal/20 bg-royal/10 text-royal",
    rail: "bg-royal",
    icon: <ShieldCheck className="h-3 w-3" />,
  },
  ACTION: {
    label: "Action",
    tint: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
    rail: "bg-emerald-400",
    icon: <Send className="h-3 w-3" />,
  },
  LEDGER: {
    label: "Ledger",
    tint: "border-emerald-500/30 bg-emerald-500/15 text-emerald-400",
    rail: "bg-emerald-400",
    icon: <BookOpenCheck className="h-3 w-3" />,
  },
  // Live reasoning stream stages
  INTENT_PARSING: {
    label: "Intent Parsing",
    tint: "border-cyan-500/20 bg-cyan-500/10 text-cyan-400",
    rail: "bg-cyan-400",
    icon: <Brain className="h-3 w-3" />,
  },
  POLICY_EVALUATION: {
    label: "Policy Eval",
    tint: "border-blue-500/20 bg-blue-500/10 text-blue-400",
    rail: "bg-blue-400",
    icon: <ShieldCheck className="h-3 w-3" />,
  },
  DIAGNOSTIC_SYNC: {
    label: "Diagnostic",
    tint: "border-amber-500/20 bg-amber-500/10 text-amber-400",
    rail: "bg-amber-400",
    icon: <Radar className="h-3 w-3" />,
  },
  ACTION_DISPATCH: {
    label: "Dispatch",
    tint: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400",
    rail: "bg-emerald-400",
    icon: <Send className="h-3 w-3" />,
  },
  RESPONSE_GENERATION: {
    label: "Response",
    tint: "border-indigo-500/20 bg-indigo-500/10 text-indigo-400",
    rail: "bg-indigo-400",
    icon: <Terminal className="h-3 w-3" />,
  },
}

const STAGE_ORDER = ["TRIGGER", "DIAGNOSIS", "POLICY", "ACTION", "LEDGER", "UNKNOWN"]

function stageMeta(stage: string) {
  return STAGE_META[stage] ?? {
    label: stage.replace(/_/g, " "),
    tint: "border-slate-600/20 bg-slate-700/20 text-slate-400",
    rail: "bg-slate-500",
    icon: <Terminal className="h-3 w-3" />,
  }
}

function fmtTime(s?: string | null): string {
  if (!s) return ""
  return new Date(s).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

function pct(conf?: number | null): string {
  if (conf == null) return ""
  return `${Math.round(conf * 100)}%`
}

export default function AgentThoughtStream({
  persisted,
  live,
  collapsed = false,
}: {
  persisted?: AgentStep[] | null
  live?: LiveAgentStep[] | undefined
  collapsed?: boolean
}) {
  const steps = useMemo(() => {
    const seen = new Set<string>()
    const merged: AgentStep[] = []
    const push = (s: AgentStep) => {
      if (seen.has(s.step_id)) return
      seen.add(s.step_id)
      merged.push(s)
    }
    for (const s of persisted ?? []) push(s)
    for (const s of live ?? []) push(s as AgentStep)
    return merged.sort((a, b) => {
      const ia = STAGE_ORDER.indexOf(a.stage)
      const ib = STAGE_ORDER.indexOf(b.stage)
      if (ia !== ib) return ia - ib
      return String(a.occurred_at ?? "").localeCompare(String(b.occurred_at ?? ""))
    })
  }, [persisted, live])

  if (!steps.length) {
    return (
      <div className="flex h-28 flex-col items-center justify-center gap-2 rounded-lg border border-slate-800/60 bg-slate-800/20 text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin opacity-60" />
        <span className="text-[11px]">Waiting for the agent to reason about this case…</span>
      </div>
    )
  }

  const shown = collapsed ? steps.slice(-3) : steps

  return (
    <div className="relative ml-1 space-y-1.5 border-l border-slate-800/70 pl-4">
      {shown.map((step) => {
        const meta = stageMeta(step.stage)
        return (
          <div key={step.step_id} className="relative rounded-lg border border-slate-800/60 bg-panel p-2.5">
            <span className={`absolute -left-[1.22rem] top-4 h-2 w-2 rounded-full ${meta.rail}`} />
            <div className="flex items-center gap-1.5">
              <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${meta.tint}`}>
                {meta.icon}
                {meta.label}
              </span>
              <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-slate-200">
                {step.label}
              </span>
              {step.confidence != null && (
                <span className="shrink-0 font-mono text-[10px] font-semibold text-slate-500">{pct(step.confidence)}</span>
              )}
              {step.latency_ms != null && (
                <span className="shrink-0 font-mono text-[9px] text-slate-600">{step.latency_ms}ms</span>
              )}
              {step.occurred_at && (
                <span className="shrink-0 font-mono text-[9px] text-slate-600">{fmtTime(step.occurred_at)}</span>
              )}
            </div>
            {step.detail && (
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{step.detail}</p>
            )}
          </div>
        )
      })}
      {collapsed && steps.length > 3 && (
        <p className="pl-1 text-[10px] italic text-slate-600">+{steps.length - 3} earlier steps</p>
      )}
    </div>
  )
}