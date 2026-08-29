import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  fetchRecoverySettings,
  saveRecoverySettings,
} from "../services/settings"
import type {
  RecoverySettings,
  RecoverySettingsUpdate,
} from "../types/settings"

const MAX_ATTEMPTS_CAP = 8
const WINDOW_CAP_DAYS = 60
const MAX_INSTALLMENTS_CAP = 12
const MAX_SEQUENCE_LEN = 8
const MIN_GAP_HOURS = 2

function validate(payload: RecoverySettingsUpdate): string | null {
  const attempts = payload.max_recovery_attempts
  if (!Number.isInteger(attempts) || attempts < 1 || attempts > MAX_ATTEMPTS_CAP) {
    return `Max recovery attempts must be an integer between 1 and ${MAX_ATTEMPTS_CAP}`
  }
  const window = payload.recovery_window_days
  if (!Number.isInteger(window) || window < 1 || window > WINDOW_CAP_DAYS) {
    return `Recovery window must be between 1 and ${WINDOW_CAP_DAYS} days`
  }
  const installments = payload.max_installments
  if (
    !Number.isInteger(installments) ||
    installments < 2 ||
    installments > MAX_INSTALLMENTS_CAP
  ) {
    return `Max installments must be between 2 and ${MAX_INSTALLMENTS_CAP}`
  }
  if (!payload.whatsapp_enabled && !payload.email_enabled) {
    return "At least one recovery channel (WhatsApp or Email) must stay enabled"
  }
  const seq = payload.default_reminder_sequence
  if (seq.length === 0) return "Reminder sequence must not be empty"
  if (seq.length > MAX_SEQUENCE_LEN) {
    return `At most ${MAX_SEQUENCE_LEN} reminders allowed`
  }
  for (const slot of seq) {
    if (!Number.isInteger(slot) || slot < 1) {
      return "Every reminder must be at least 1h after the start"
    }
  }
  for (let i = 0; i < seq.length - 1; i++) {
    if (seq[i] >= seq[i + 1]) {
      return "Reminder sequence must be strictly increasing"
    }
    if (seq[i + 1] - seq[i] < MIN_GAP_HOURS) {
      return `Reminders must be spaced at least ${MIN_GAP_HOURS}h apart`
    }
  }
  const totalHours = seq.reduce((a, b) => a + b, 0)
  if (totalHours > window * 24) {
    return `Reminder sequence totals ${totalHours}h which exceeds the ${window}‑day recovery window (${window * 24}h)`
  }
  return null
}

export default function RecoverySettingsPage() {
  const [settings, setSettings] = useState<RecoverySettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedFlash, setSavedFlash] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetchRecoverySettings()
      .then((data) => {
        if (!cancelled) setSettings(data)
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load recovery settings")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const patch = (next: Partial<RecoverySettingsUpdate>) => {
    if (!settings) return
    setSettings({ ...settings, ...next })
  }

  const setSequence = (seq: number[]) => patch({ default_reminder_sequence: seq })

  const handleSave = async () => {
    if (!settings) return
    setSaving(true)
    setError(null)
    setSavedFlash(false)
    const payload: RecoverySettingsUpdate = {
      max_recovery_attempts: settings.max_recovery_attempts,
      recovery_window_days: settings.recovery_window_days,
      whatsapp_enabled: settings.whatsapp_enabled,
      email_enabled: settings.email_enabled,
      default_reminder_sequence: settings.default_reminder_sequence,
      payment_plan_enabled: settings.payment_plan_enabled,
      max_installments: settings.max_installments,
      promise_to_pay_enabled: settings.promise_to_pay_enabled,
    }
    const clientError = validate(payload)
    if (clientError) {
      setError(clientError)
      setSaving(false)
      return
    }
    try {
      const saved = await saveRecoverySettings(payload)
      setSettings(saved)
      setSavedFlash(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-400">
        Loading settings…
      </div>
    )
  }

  if (!settings) {
    return (
<div className="space-y-6 text-slate-100">
        <div className="rounded-xl border border-red-800 bg-red-900/20 p-4 text-red-400">
          {error ?? "Unable to load recovery settings"}
        </div>
      </div>
    )
  }

  const totalReminderHours = settings.default_reminder_sequence.reduce(
    (a, b) => a + b,
    0,
  )
  const isLastChannel =
    settings.whatsapp_enabled && !settings.email_enabled
      ? "whatsapp"
      : !settings.whatsapp_enabled && settings.email_enabled
        ? "email"
        : null

  const toggleChannel = (channel: "whatsapp" | "email") => {
    if (channel === "whatsapp") {
      if (settings.whatsapp_enabled && isLastChannel === "whatsapp") return
      patch({ whatsapp_enabled: !settings.whatsapp_enabled })
    } else {
      if (settings.email_enabled && isLastChannel === "email") return
      patch({ email_enabled: !settings.email_enabled })
    }
  }

  const addReminder = () => {
    const seq = settings.default_reminder_sequence
    if (seq.length >= MAX_SEQUENCE_LEN) return
    const last = seq[seq.length - 1]
    setSequence([...seq, last + MIN_GAP_HOURS])
  }

  const removeReminder = (index: number) => {
    if (settings.default_reminder_sequence.length <= 1) return
    setSequence(settings.default_reminder_sequence.filter((_, i) => i !== index))
  }

  return (
    <div className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Recovery Settings</h1>
          <p className="mt-1 text-sm text-slate-400">
            Configure how recovery runs. Saved to the database and applied to all
            cases. Safety protections are always on and cannot be disabled.
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/dashboard"
            className="rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700"
          >
            Dashboard
          </Link>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Settings"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-red-800 bg-red-900/20 p-4 text-red-400">
          {error}
        </div>
      )}
      {savedFlash && (
        <div className="mb-6 rounded-xl border border-green-800 bg-green-900/20 p-4 text-green-400">
          Settings saved successfully
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left: form controls */}
        <div className="space-y-6 lg:col-span-2">
          {/* Recovery basics */}
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="mb-4 text-lg font-semibold text-slate-100">
              Recovery Basics
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-sm text-slate-400">
                  Max Recovery Attempts
                </span>
                <input
                  type="number"
                  min={1}
                  max={MAX_ATTEMPTS_CAP}
                  value={settings.max_recovery_attempts}
                  onChange={(e) =>
                    patch({ max_recovery_attempts: Number(e.target.value) })
                  }
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100"
                />
                <span className="mt-1 block text-xs text-slate-500">
                  Hard ceiling {MAX_ATTEMPTS_CAP} — above that is blocked.
                </span>
              </label>
              <label className="block">
                <span className="mb-1 block text-sm text-slate-400">
                  Recovery Window (days)
                </span>
                <input
                  type="number"
                  min={1}
                  max={WINDOW_CAP_DAYS}
                  value={settings.recovery_window_days}
                  onChange={(e) =>
                    patch({ recovery_window_days: Number(e.target.value) })
                  }
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100"
                />
                <span className="mt-1 block text-xs text-slate-500">
                  Max {WINDOW_CAP_DAYS} days. After this the case is marked Lost.
                </span>
              </label>
            </div>
          </section>

          {/* Channels */}
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="mb-4 text-lg font-semibold text-slate-100">
              Recovery Channels
            </h2>
            <div className="space-y-3">
              <ChannelToggle
                label="WhatsApp"
                description="Send recovery reminders over WhatsApp"
                checked={settings.whatsapp_enabled}
                onChange={() => toggleChannel("whatsapp")}
              />
              <ChannelToggle
                label="Email"
                description="Send recovery reminders over Email"
                checked={settings.email_enabled}
                onChange={() => toggleChannel("email")}
              />
            </div>
            <p className="mt-3 text-xs text-slate-500">
              At least one channel must stay enabled — turning off the last one
              is blocked.
            </p>
          </section>

          {/* Reminder sequence */}
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-slate-100">
                Reminder Sequence
              </h2>
              <span
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                  totalReminderHours <= settings.recovery_window_days * 24
                    ? "bg-blue-500/10 text-blue-400"
                    : "bg-red-500/10 text-red-400"
                }`}
              >
                Total {totalReminderHours}h of {settings.recovery_window_days * 24}h
                window
              </span>
            </div>
            <p className="mb-4 text-sm text-slate-400">
              Hours after recovery starts when a reminder is automatically sent.
              Must be strictly increasing, at least {MIN_GAP_HOURS}h apart, and fit
              inside the recovery window.
            </p>
            <div className="space-y-2">
              {settings.default_reminder_sequence.map((slot, index) => (
                <div
                  key={index}
                  className="flex items-center gap-3 rounded-lg bg-slate-800/60 px-3 py-2"
                >
                  <span className="text-xs text-slate-500">Reminder {index + 1}</span>
                  <input
                    type="number"
                    min={1}
                    value={slot}
                    onChange={(e) => {
                      const next = settings.default_reminder_sequence.slice()
                      next[index] = Number(e.target.value)
                      setSequence(next)
                    }}
                    className="w-24 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-slate-100"
                  />
                  <span className="text-sm text-slate-400">hours</span>
                  <button
                    onClick={() => removeReminder(index)}
                    disabled={settings.default_reminder_sequence.length <= 1}
                    className="ml-auto rounded-lg bg-red-600/20 px-2.5 py-1 text-xs text-red-400 hover:bg-red-600/30 disabled:opacity-40"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
            <button
              onClick={addReminder}
              disabled={settings.default_reminder_sequence.length >= MAX_SEQUENCE_LEN}
              className="mt-3 rounded-lg bg-slate-800 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700 disabled:opacity-40"
            >
              Add reminder
            </button>
          </section>

          {/* Payment plans + promise */}
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="mb-4 text-lg font-semibold text-slate-100">
              Payment Plans & Promises
            </h2>
            <div className="space-y-3">
              <ChannelToggle
                label="Payment Plans"
                description="Allow installing failed payments into EMIs"
                checked={settings.payment_plan_enabled}
                onChange={() =>
                  patch({ payment_plan_enabled: !settings.payment_plan_enabled })
                }
              />
              <ChannelToggle
                label="Promise-to-Pay"
                description="Track customer payment promises as recovery progress"
                checked={settings.promise_to_pay_enabled}
                onChange={() =>
                  patch({ promise_to_pay_enabled: !settings.promise_to_pay_enabled })
                }
              />
            </div>
            <label className="mt-4 block max-w-xs">
              <span className="mb-1 block text-sm text-slate-400">
                Max Installments
              </span>
              <input
                type="number"
                min={2}
                max={MAX_INSTALLMENTS_CAP}
                value={settings.max_installments}
                onChange={(e) =>
                  patch({ max_installments: Number(e.target.value) })
                }
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100"
              />
              <span className="mt-1 block text-xs text-slate-500">
                Between 2 and {MAX_INSTALLMENTS_CAP}.
              </span>
            </label>
          </section>
        </div>

        {/* Right: safety protections (read-only) */}
        <div className="space-y-6">
          <section className="rounded-xl border-2 border-green-500/30 bg-green-950/20 p-6">
            <h2 className="mb-3 text-lg font-semibold text-green-400">
              Safety Protections
            </h2>
            <div className="space-y-3 text-sm">
              <ProtectionRow
                label="Hard Stop Rules"
                value="Always On"
                description="Stops recovery instantly if the customer pays, opts out, or a hard condition triggers. Never overridable."
              />
              <ProtectionRow
                label="Customer Opt-Out"
                value="Always Enforced"
                description="A customer who asks to stop is never contacted again."
              />
              <ProtectionRow
                label="Min Reminder Spacing"
                value={`${settings.min_reminder_gap_hours}h`}
                description="Reminders can never be sent closer than this."
              />
              <ProtectionRow
                label="Attempts Ceiling"
                value={`${MAX_ATTEMPTS_CAP}`}
                description="Recovery attempts are hard-capped regardless of settings."
              />
            </div>
            <p className="mt-4 rounded-lg bg-green-500/10 p-3 text-xs text-green-400">
              These protections are enforced by the policy engine and cannot be
              disabled through merchant settings.
            </p>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-900 p-6 text-sm">
            <h2 className="mb-2 text-sm font-semibold text-slate-300">
              Current Value
            </h2>
            <dl className="space-y-1 text-xs text-slate-400">
              <div className="flex justify-between">
                <dt>Attempts</dt>
                <dd className="font-medium text-slate-200">
                  {settings.max_recovery_attempts}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt>Window</dt>
                <dd className="font-medium text-slate-200">
                  {settings.recovery_window_days} days
                </dd>
              </div>
              <div className="flex justify-between">
                <dt>Installments</dt>
                <dd className="font-medium text-slate-200">
                  {settings.max_installments}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt>Last saved</dt>
                <dd className="font-medium text-slate-200">
                  {settings.updated_at ? new Date(settings.updated_at).toLocaleString() : "never"}
                </dd>
              </div>
            </dl>
          </section>
        </div>
      </div>
    </div>
  )
}

function ChannelToggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string
  description: string
  checked: boolean
  onChange: () => void
}) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-slate-800/60 px-4 py-3">
      <div>
        <p className="text-sm font-medium text-slate-200">{label}</p>
        <p className="text-xs text-slate-500">{description}</p>
      </div>
      <button
        onClick={onChange}
        role="switch"
        aria-checked={checked}
        className={`relative h-6 w-11 rounded-full transition-colors ${
          checked ? "bg-green-500" : "bg-slate-600"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${
            checked ? "left-[22px]" : "left-0.5"
          }`}
        />
      </button>
    </div>
  )
}

function ProtectionRow({
  label,
  value,
  description,
}: {
  label: string
  value: string
  description: string
}) {
  return (
    <div className="rounded-lg bg-slate-900/60 p-3">
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-200">{label}</span>
        <span className="rounded-full bg-green-500/10 px-2 py-0.5 text-xs font-medium text-green-400">
          {value}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-500">{description}</p>
    </div>
  )
}