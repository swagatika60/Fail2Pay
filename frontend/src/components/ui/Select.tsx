import {
  Check,
  ChevronDown,
  ChevronUp,
} from "lucide-react"
import * as SelectPrimitive from "@radix-ui/react-select"
import type { ComponentProps, ReactNode } from "react"

interface SelectOption {
  value: string
  label: string
}

interface SelectProps {
  value: string
  onValueChange: (value: string) => void
  options: SelectOption[]
  placeholder?: string
  ariaLabel: string
  triggerClassName?: string
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder = "Select…",
  ariaLabel,
  triggerClassName = "",
}: SelectProps) {
  return (
    <SelectPrimitive.Root
      value={value}
      onValueChange={onValueChange}
    >
      <SelectPrimitive.Trigger
        aria-label={ariaLabel}
        className={`group inline-flex h-8 items-center justify-between gap-2 rounded-lg border border-slate-700/70 bg-slate-800/40 px-2.5 text-xs font-medium text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-800/70 ${triggerClassName}`}
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon className="text-slate-500 group-hover:text-slate-400">
          <ChevronDown className="h-3.5 w-3.5" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className="z-50 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-slate-700/70 bg-slate-900 p-1 shadow-xl shadow-black/40"
        >
          <SelectPrimitive.ScrollUpButton className="flex items-center justify-center py-1 text-slate-500">
            <ChevronUp className="h-3.5 w-3.5" />
          </SelectPrimitive.ScrollUpButton>
          <SelectPrimitive.Viewport>
            {options.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectPrimitive.Viewport>
          <SelectPrimitive.ScrollDownButton className="flex items-center justify-center py-1 text-slate-500">
            <ChevronDown className="h-3.5 w-3.5" />
          </SelectPrimitive.ScrollDownButton>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  )
}

function SelectItem({
  children,
  ...props
}: ComponentProps<typeof SelectPrimitive.Item> & { children: ReactNode }) {
  return (
    <SelectPrimitive.Item
      className="flex cursor-pointer select-none items-center justify-between rounded-md px-2.5 py-1.5 text-xs text-slate-300 outline-none data-[highlighted]:bg-slate-800 data-[highlighted]:text-slate-100"
      {...props}
    >
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator>
        <Check className="h-3.5 w-3.5 text-slate-200" />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  )
}
