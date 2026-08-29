import { useState } from "react"
import { simulateCustomerMessage } from "../../services/operations"
import type { SimulateMessageResult } from "../../services/operations"
import {
  buildSplitOptions,
  summarizeSplit,
  type SplitOption,
} from "../../lib/installments"
import { formatINRFull } from "../../lib/format"

interface QuickReplyDef {
  id: string
  label: string
  trigger: string
  hint: string
  tone: string
}

const STATIC_QUICK_REPLIES: QuickReplyDef[] = [
  {
    id: "pay_now",
    label: "Pay Now",
    trigger: "pay_link",
    hint: "Request payment link",
    tone: "green",
  },
  {
    id: "promise",
    label: "Kal pakka karunga",
    trigger: "promise",
    hint: "Promise to pay → pause + schedule reminder",
    tone: "blue",
  },
  {
    id: "wrong_bill",
    label: "Wrong bill amount",
    trigger: "wrong_bill",
    hint: "Dispute → escalate to human",
    tone: "amber",
  },
  {
    id: "support",
    label: "Talk to Support",
    trigger: "support",
    hint: "Hand off to a human",
    tone: "purple",
  },
  {
    id: "stop",
    label: "Stop messaging me",
    trigger: "stop",
    hint: "Explicit opt-out → hard stop",
    tone: "red",
  },
]

const TONE_CLASSES: Record<string, string> = {
  green: "border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/20",
  blue: "border-blue-500/40 text-blue-300 hover:bg-blue-500/20",
  amber: "border-amber-500/40 text-amber-300 hover:bg-amber-500/20",
  purple: "border-purple-500/40 text-purple-300 hover:bg-purple-500/20",
  red: "border-red-500/40 text-red-300 hover:bg-red-500/20",
}

interface Props {
  caseId: string
  amount?: number
  compact?: boolean
  onApplied?: (result: SimulateMessageResult) => void
  onTyping?: (typing: boolean) => void
}

export default function SimulateMessageControls({
  caseId,
  amount,
  compact = false,
  onApplied,
  onTyping,
}: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<SimulateMessageResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [currentLanguage, setCurrentLanguage] = useState<"en" | "hi">("en")

  const hinglish = currentLanguage === "hi"
  const splitOptions: SplitOption[] =
    amount && amount > 0 ? buildSplitOptions(amount) : []

  const localizedStaticLabel = (id: string): string => {
    if (!hinglish) {
      return STATIC_QUICK_REPLIES.find((q) => q.id === id)?.label || id
    }
    const map: Record<string, string> = {
      pay_now: "Abhi Pay Karein",
      promise: "Kal pakka karunga",
      wrong_bill: "Galat bill amount",
      support: "Support Se Baat Karein",
      stop: "Messaging band karo",
    }
    return map[id] || id
  }

  const splitLabel = (count: number): string =>
    hinglish ? `${count} Kishton mein baantein` : `Split in ${count} EMIs`

  const run = async (trigger: string, id: string) => {
    setBusy(id)
    setError(null)
    onTyping?.(true)
    try {
      // Small delay so the typing indicator is visible (simulated multi-turn).
      await new Promise((r) => setTimeout(r, 900))
      const res = await simulateCustomerMessage(caseId, trigger)
      if (res.language === "hi" || res.language === "hi-en") {
        setCurrentLanguage("hi")
      } else if (res.language === "en") {
        setCurrentLanguage("en")
      }
      setResult(res)
      onApplied?.(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Simulation failed")
    } finally {
      setBusy(null)
      onTyping?.(false)
    }
  }

  return (
    <div className={compact ? "space-y-2" : "rounded-xl border border-slate-700 bg-slate-900 p-4"}>
      <p className="text-xs font-medium text-slate-400">
        🧪 Simulate customer reply — tap a quick-reply to run the full dialogue
        cycle
      </p>
      <div className="flex flex-wrap gap-2">
        {STATIC_QUICK_REPLIES.map((q) => (
          <button
            key={q.id}
            onClick={() => run(q.trigger, q.id)}
            disabled={busy !== null}
            className={`rounded-lg border bg-slate-800/40 px-3 py-1.5 text-sm transition-colors disabled:opacity-50 ${TONE_CLASSES[q.tone]}`}
            title={q.hint}
          >
            {busy === q.id ? "…" : `"${localizedStaticLabel(q.id)}"`}
          </button>
        ))}
      </div>

      {/* Dynamic split-in-N EMIs chips with computed amounts */}
      {splitOptions.length > 0 && (
        <div className="mt-2">
          <p className="mb-1 text-[11px] text-slate-500">
            💸{" "}
            {hinglish
              ? `${formatINRFull(amount!)} ko N kisth mein baantein:`
              : `Split in N EMIs (computed from ${formatINRFull(amount!)}):`}
          </p>
          <div className="flex flex-wrap gap-2">
            {splitOptions.map((s) => (
              <button
                key={s.id}
                onClick={() => run(s.id, s.id)}
                disabled={busy !== null}
                className="rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-3 py-1.5 text-sm text-indigo-200 transition-colors hover:bg-indigo-500/20 disabled:opacity-50"
                title={s.amounts.map((a) => formatINRFull(a)).join(" + ")}
              >
                {busy === s.id
                  ? "…"
                  : `${splitLabel(s.count)} · ${summarizeSplit(amount!, s.count)}`}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span>Language:</span>
        {[
          { id: "lang:en", label: "English", trigger: "language_en" },
          { id: "lang:hi", label: "हिंदी / Hinglish", trigger: "language_hi" },
        ].map((l) => (
          <button
            key={l.id}
            onClick={() => run(l.trigger, l.id)}
            disabled={busy !== null}
            className="rounded-full border border-slate-600 px-2 py-0.5 text-xs text-slate-300 hover:bg-slate-700 disabled:opacity-50"
          >
            {l.label}
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
                  : result.recovered
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "bg-blue-500/20 text-blue-400"
              }`}
            >
              {result.recovered
                ? "✅ RECOVERED"
                : result.case_status === "STOPPED"
                  ? "🛑 STOPPED"
                  : result.case_status.replace(/_/g, " ")}
              {result.escalated_to_human ? " · ESCALATED TO HUMAN" : ""}
              {result.hard_stopped ? " · HARD-STOPPED" : ""}
            </span>
            <span className="text-slate-300">
              Intent: <span className="font-medium">{result.detected_intent}</span>
              <span className="text-slate-500">
                {" "}
                ({result.intent_source}, {Math.round(result.intent_confidence * 100)}%)
              </span>
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-400">
            {(typeof result.attempt_count === "number" ||
              typeof result.language === "string") && (
              <span>
                Attempts:{" "}
                <span className="font-semibold text-slate-200">
                  {typeof result.attempt_count === "number"
                    ? result.attempt_count
                    : "—"}
                </span>
              </span>
            )}
            {result.language && (
              <span>
                Lang:{" "}
                <span className="font-semibold text-slate-200">
                  {result.language}
                </span>
              </span>
            )}
            {result.recovered && (
              <span>
                Recovered:{" "}
                <span className="font-semibold text-emerald-400">
                  {formatINRFull(result.recovered_amount ?? 0)}
                </span>
                {typeof result.recovery_rate === "number" &&
                  ` · ${result.recovery_rate}%`}
              </span>
            )}
          </div>
          {result.guardrail_note && (
            <p className="mt-2 text-red-300">🛡️ {result.guardrail_note}</p>
          )}
          {result.reply_text && (
            <div className="mt-2 rounded bg-slate-800/50 p-2 text-slate-300">
              <span className="font-medium text-emerald-400">Agent:</span>{" "}
              {result.reply_text}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
