import { useState } from "react"
import { simulateCustomerMessage } from "../../services/operations"
import type { SimulateMessageResult } from "../../services/operations"

const TRIGGERS = [
  {
    key: "promise",
    label: "Kal pakka karunga",
    hint: "Promise to pay",
    tone: "blue",
  },
  {
    key: "stop",
    label: "Stop messaging me",
    hint: "Explicit opt-out → hard stop",
    tone: "red",
  },
  {
    key: "wrong_bill",
    label: "Wrong bill amount",
    hint: "Dispute / question",
    tone: "amber",
  },
]

const TONE_CLASSES: Record<string, string> = {
  blue: "border-blue-500/30 text-blue-300 hover:bg-blue-500/20",
  red: "border-red-500/30 text-red-300 hover:bg-red-500/20",
  amber: "border-amber-500/30 text-amber-300 hover:bg-amber-500/20",
}

interface Props {
  caseId: string
  compact?: boolean
  onApplied?: (result: SimulateMessageResult) => void
}

export default function SimulateMessageControls({
  caseId,
  compact = false,
  onApplied,
}: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<SimulateMessageResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async (trigger: string) => {
    setBusy(trigger)
    setError(null)
    try {
      const res = await simulateCustomerMessage(caseId, trigger)
      setResult(res)
      onApplied?.(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Simulation failed")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className={compact ? "space-y-2" : "rounded-xl border border-slate-700 bg-slate-900 p-4"}>
      <p className="text-xs font-medium text-slate-400">
        🧪 Simulate customer reply
      </p>
      <div className="flex flex-wrap gap-2">
        {TRIGGERS.map((t) => (
          <button
            key={t.key}
            onClick={() => run(t.key)}
            disabled={busy !== null}
            className={`rounded-lg border bg-slate-800/40 px-3 py-1.5 text-sm transition-colors disabled:opacity-50 ${TONE_CLASSES[t.tone]}`}
            title={t.hint}
          >
            {busy === t.key ? "Applying…" : `"${t.label}"`}
          </button>
        ))}
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}

      {result && (
        <div
          className={`rounded-lg border p-3 text-xs ${
            result.opt_out_triggered
              ? "border-red-500/40 bg-red-500/10"
              : "border-blue-500/30 bg-blue-500/5"
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 font-medium ${
                result.case_status === "STOPPED"
                  ? "bg-red-500/20 text-red-400"
                  : "bg-blue-500/20 text-blue-400"
              }`}
            >
              {result.case_status === "STOPPED" ? "🛑 STOPPED" : result.case_status.replace(/_/g, " ")}
            </span>
            <span className="text-slate-300">
              Intent: <span className="font-medium">{result.detected_intent}</span>
              <span className="text-slate-500">
                {" "}
                ({result.intent_source}, {Math.round(result.intent_confidence * 100)}%)
              </span>
            </span>
          </div>
          {result.guardrail_note && (
            <p className="mt-2 text-red-300">🛡️ {result.guardrail_note}</p>
          )}
        </div>
      )}
    </div>
  )
}
