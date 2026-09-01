import { Select } from "../ui/Select"

export const DATE_RANGES = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "all", label: "All time" },
]

export const CHANNELS = [
  { value: "all", label: "All channels" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "email", label: "Email" },
  { value: "payment_plan", label: "Payment plans" },
]

export const CURRENCIES = [
  { value: "INR", label: "INR" },
  { value: "USD", label: "USD" },
]

export interface FilterState {
  range: string
  channel: string
  currency: string
}

export function DashboardFilters({
  state,
  onChange,
}: {
  state: FilterState
  onChange: (next: FilterState) => void
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="group"
      aria-label="Dashboard filters"
    >
      <Select
        value={state.range}
        onValueChange={(range) => onChange({ ...state, range })}
        options={DATE_RANGES}
        ariaLabel="Date range"
      />
      <Select
        value={state.channel}
        onValueChange={(channel) => onChange({ ...state, channel })}
        options={CHANNELS}
        ariaLabel="Channel"
      />
      <Select
        value={state.currency}
        onValueChange={(currency) => onChange({ ...state, currency })}
        options={CURRENCIES}
        ariaLabel="Currency"
      />
    </div>
  )
}
