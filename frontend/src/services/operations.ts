import type {
  PaymentPlanListItem,
  ConversationListItem,
  InvoiceListItem,
} from "../types/operations"

interface CacheEntry<T> {
  data: T
  fetchedAt: number
}

const TTL_MS = 1000 * 60 * 5

const listCache = new Map<string, CacheEntry<unknown>>()

function cached<T>(
  key: string,
  fetcher: () => Promise<T>,
  bypass = false,
): Promise<T> {
  const entry = listCache.get(key)
  if (!bypass && entry && Date.now() - entry.fetchedAt < TTL_MS) {
    return Promise.resolve(entry.data as T)
  }
  return fetcher().then((data) => {
    listCache.set(key, { data, fetchedAt: Date.now() })
    return data
  })
}

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`Failed to fetch ${path}`)
  return response.json() as Promise<T>
}

export function fetchPaymentPlansList(opts: { bypass?: boolean } = {}): Promise<PaymentPlanListItem[]> {
  return cached(
    "payment-plans",
    () => getJSON<PaymentPlanListItem[]>("/api/payment-plans"),
    opts.bypass,
  )
}

export function fetchConversationsList(opts: { bypass?: boolean } = {}): Promise<ConversationListItem[]> {
  return cached(
    "conversations",
    () => getJSON<ConversationListItem[]>("/api/conversations"),
    opts.bypass,
  )
}

export function fetchInvoicesList(opts: { bypass?: boolean } = {}): Promise<InvoiceListItem[]> {
  return cached(
    "invoices",
    () => getJSON<InvoiceListItem[]>("/api/invoices"),
    opts.bypass,
  )
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
  reply_text?: string
  agent_payload?: Record<string, unknown> | null
  escalated_to_human?: boolean
  promise_scheduled?: Record<string, unknown> | null
  split_plan?: Record<string, unknown> | null
  language?: string
  recovered?: boolean
  hard_stopped?: boolean
  recovered_amount?: number
  remaining_amount?: number
  recovery_rate?: number
  attempt_count?: number
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

export async function generateAgentInitial(
  caseId: string,
): Promise<{ message: string; agent_payload: Record<string, unknown>; email: unknown }> {
  const response = await fetch(`/api/cases/${caseId}/agent-initial`, {
    method: "POST",
  })
  if (!response.ok) throw new Error("Failed to generate agent trigger")
  return response.json()
}

export async function generateCaseEmail(
  caseId: string,
): Promise<{ email: unknown }> {
  const response = await fetch(`/api/cases/${caseId}/generate-email`, {
    method: "POST",
  })
  if (!response.ok) throw new Error("Failed to generate email")
  return response.json()
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
  return cached(`plan-seq:${planId}`, () =>
    getJSON<RetrySequencer>(`/api/plans/${planId}/retry-sequencer`),
  )
}