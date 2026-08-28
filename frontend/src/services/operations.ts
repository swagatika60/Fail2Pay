import type {
  PaymentPlanListItem,
  ConversationListItem,
  InvoiceListItem,
} from "../types/operations"

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`Failed to fetch ${path}`)
  return response.json() as Promise<T>
}

export function fetchPaymentPlansList(): Promise<PaymentPlanListItem[]> {
  return getJSON("/api/payment-plans")
}

export function fetchConversationsList(): Promise<ConversationListItem[]> {
  return getJSON("/api/conversations")
}

export function fetchInvoicesList(): Promise<InvoiceListItem[]> {
  return getJSON("/api/invoices")
}

export interface SimulateMessageResult {
  case_id: string
  trigger: string
  message: string
  detected_intent: string
  intent_source: string
  intent_confidence: number
  case_status: string
  guardrail_note: string | null
  opt_out_triggered: boolean
}

export async function simulateCustomerMessage(
  caseId: string,
  trigger: string,
): Promise<SimulateMessageResult> {
  const response = await fetch(`/api/cases/${caseId}/simulate-message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trigger }),
  })
  if (!response.ok) throw new Error("Failed to simulate customer message")
  return response.json() as Promise<SimulateMessageResult>
}

export interface RetryStep {
  order: number
  action: string
  label: string
  scheduled_for: string | null
  payload: Record<string, unknown>
}

export interface RetrySequencer {
  plan_id: string
  case_id: string
  degraded: boolean
  trigger_reason: string
  strategy: string | null
  strategy_label: string | null
  split: {
    upfront_amount: number
    upfront_due: string
    later_amount: number
    later_due: string
    note: string
  } | null
  timeline: RetryStep[]
  blocked: boolean
  block_reason: string | null
}

export function fetchPlanRetrySequencer(planId: string): Promise<RetrySequencer> {
  return getJSON(`/api/plans/${planId}/retry-sequencer`)
}