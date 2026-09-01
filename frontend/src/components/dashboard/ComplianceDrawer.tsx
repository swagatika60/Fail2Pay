import {
  X,
  ShieldCheck,
  Scale,
  LockKeyhole,
  BadgeCheck,
  UserX,
  Inbox,
  Handshake,
  Leaf,
} from "lucide-react"
import type { ReactNode } from "react"
import type { RecoveryCaseDetail } from "../../types/analytics"

/**
 * Compliance & Reasoning Drawer — makes every autonomous decision auditable.
 *
 * Explains WHY the engine acted the way it did, what guardrails bounded it,
 * and the exact money rules that apply. Opened from the case page; purely
 * informational (read-only telemetry + policy surface).
 */

const RULES: { icon: ReactNode; title: string; body: string }[] = [
  {
    icon: <Scale className="h-3.5 w-3.5 text-indigo-400" />,
    title: "Reasoning Transparency",
    body: "Every decision is recorded as a step in the Agent Thought Stream and persisted to the immutable audit trail — no black-box calls.",
  },
  {
    icon: <Inbox className="h-3.5 w-3.5 text-amber-400" />,
    title: "Bounded Outreach",
    body: "Messages follow the retry sequencer and merchant policy cap. Excessive reminders are impossible by construction.",
  },
  {
    icon: <UserX className="h-3.5 w-3.5 text-rose-400" />,
    title: "Opt-Out Is Immediate",
    body: 'A stop or opt-out instantly halts all scheduled actions, WhatsApp and email — "STOPPED" is honored as a hard terminal state.',
  },
  {
    icon: <LockKeyhole className="h-3.5 w-3.5 text-emerald-400" />,
    title: "No Discounting",
    body: "The policy engine holds the discount budget at zero. The agent can offer installation plans, never price discounts.",
  },
  {
    icon: <BadgeCheck className="h-3.5 w-3.5 text-emerald-400" />,
    title: "Money Rule: Verified Only",
    body: "Only Razorpay 'captured' webhooks create revenue. A customer message, promise, or agent claim is never counted as money.",
  },
  {
    icon: <Handshake className="h-3.5 w-3.5 text-violet-400" />,
    title: "Promise-to-Pay Ledger",
    body: "Promises are tracked with expiry windows and verified against real captures on the settlement path.",
  },
]

const GUARDRAILS = ["5 attempts max", "14-day window", "No discounts", "≥72h promise window", "Human escalation on high-value"]

export default function ComplianceDrawer({
  open,
  onClose,
  detail,
}: {
  open: boolean
  onClose: () => void
  detail: RecoveryCaseDetail | null
}) {
  if (!open) return null

  const rootCause = detail?.root_cause?.replace(/_/g, " ") || "Not yet diagnosed"
  const risk = detail?.risk_level || "—"

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        aria-label="Close compliance panel"
        className="absolute inset-0 cursor-default bg-black/60 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <aside className="relative flex h-full w-full max-w-md flex-col border-l border-edge bg-panel shadow-2xl">
        <header className="flex items-center justify-between border-b border-edge px-5 py-4">
          <div className="flex items-center gap-2.5">
            <ShieldCheck className="h-5 w-5 text-emerald-400" />
            <div>
              <h2 className="text-sm font-semibold text-ink">Compliance & Reasoning</h2>
              <p className="text-[11px] text-ink-muted">Why the agent acted, and within what guardrails</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-edge p-1.5 text-ink-muted transition-colors hover:bg-elevated hover:text-ink"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4 scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent">
          {/* Case posture */}
          <section className="rounded-lg border border-edge bg-panel-2 p-3.5">
            <h3 className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">Case Posture</h3>
            <dl className="mt-2 space-y-1.5 text-xs">
              <div className="flex justify-between">
                <dt className="text-ink-muted">Root Cause</dt>
                <dd className="font-medium text-ink">{rootCause}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-muted">Risk</dt>
                <dd className="font-mono font-semibold text-ink">{risk}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-muted">Attempts</dt>
                <dd className="font-mono text-ink">
                  {detail ? `${detail.attempt_count}/${detail.max_attempts}` : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-muted">Stage</dt>
                <dd className="font-medium text-ink">{detail?.recovery_stage?.replace(/_/g, " ") || "—"}</dd>
              </div>
            </dl>
          </section>

          {/* Guardrails */}
          <section className="mt-4">
            <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-ink-muted">Active Guardrails</h3>
            <div className="flex flex-wrap gap-1.5">
              {GUARDRAILS.map((g) => (
                <span key={g} className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[10px] font-medium text-emerald-400">
                  <BadgeCheck className="h-3 w-3" />
                  {g}
                </span>
              ))}
            </div>
            <p className="mt-2 text-[10px] leading-relaxed text-ink-faint">
              All decisions are evaluated against the merchant recovery policy via the bounded policy engine — the agent
              proposes, the policy disposes.
            </p>
          </section>

          {/* Rules */}
          <section className="mt-5">
            <h3 className="mb-2.5 text-[10px] font-semibold uppercase tracking-wider text-ink-muted">Autonomy Charter</h3>
            <div className="space-y-2.5">
              {RULES.map((rule) => (
                <div key={rule.title} className="flex gap-2.5 rounded-lg border border-edge bg-panel-2 p-2.5">
                  <span className="mt-0.5 shrink-0">{rule.icon}</span>
                  <div>
                    <p className="text-xs font-semibold text-ink">{rule.title}</p>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-ink-muted">{rule.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Footer note */}
          <footer className="mt-5 flex items-start gap-2 rounded-lg border border-emerald-500/15 bg-emerald-500/5 p-3">
            <Leaf className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
            <p className="text-[10px] leading-relaxed text-emerald-400/80">
              Fail2Pay operates consumer-friendly recovery by policy: no shaming language, immediate stop on opt-out, and
              verified-only revenue accounting.
            </p>
          </footer>
        </div>
      </aside>
    </div>
  )
}