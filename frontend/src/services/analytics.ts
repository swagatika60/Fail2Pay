import type {
  RevenueMap,
  RevenueSummary,
  RecoveryCaseSummary,
  RecoveryCaseDetail,
  PaymentPromise,
  PaymentPlan,
  Conversation,
  SentEmail,
  HardStop,
  RecoveryTimeline,
  PolicyTrace,
  CaseSchedule,
  VerifiedImpactLedger,
  VoiceCall,
} from "../types/analytics"

interface CacheEntry<T> {
  data: T
  fetchedAt: number
}

const TTL_MS = 1000 * 60 * 5

function cached<T>(key: string, cache: Map<string, CacheEntry<T>>, fetcher: () => Promise<T>): Promise<T> {
  const entry = cache.get(key)
  if (entry && Date.now() - entry.fetchedAt < TTL_MS) {
    return Promise.resolve(entry.data)
  }
  return fetcher().then((data) => {
    cache.set(key, { data, fetchedAt: Date.now() })
    return data
  })
}

const detailCache = new Map<string, CacheEntry<RecoveryCaseDetail>>()

export function clearCaseDetailCache(caseId: string) {
  detailCache.delete(caseId)
}

export async function fetchVerifiedImpactLedger(): Promise<VerifiedImpactLedger> {
  const response = await fetch("/api/simulation/impact-ledger")
  if (!response.ok) throw new Error("Failed to fetch impact ledger")
  return response.json()
}


export async function fetchRevenueMap(): Promise<RevenueMap> {
  const response = await fetch("/api/analytics/revenue-map")
  if (!response.ok) throw new Error("Failed to fetch revenue map")
  return response.json()
}

export async function fetchRevenueSummary(): Promise<RevenueSummary> {
  const response = await fetch("/api/analytics/summary")
  if (!response.ok) throw new Error("Failed to fetch revenue summary")
  return response.json()
}

export async function fetchRecoveryCases(): Promise<RecoveryCaseSummary[]> {
  const response = await fetch("/api/analytics/recovery-cases")
  if (!response.ok) throw new Error("Failed to fetch recovery cases")
  return response.json()
}

export async function fetchRecoveryCaseDetail(
  caseId: string,
  opts: { bypass?: boolean } = {},
): Promise<RecoveryCaseDetail> {
  if (!opts.bypass) {
    return cached(caseId, detailCache, () =>
      fetch(`/api/analytics/recovery-cases/${caseId}`).then(async (response) => {
        if (!response.ok) {
          console.error(
            `[CaseDetail] fetch failed — status=${response.status} caseId=${caseId}`,
          )
          throw new Error(`Failed to fetch case detail (HTTP ${response.status})`)
        }
        return response.json() as Promise<RecoveryCaseDetail>
      }),
    )
  }
  const response = await fetch(`/api/analytics/recovery-cases/${caseId}`)
  if (!response.ok) {
    console.error(
      `[CaseDetail] fetch failed (bypass) — status=${response.status} caseId=${caseId}`,
    )
    throw new Error(`Failed to fetch case detail (HTTP ${response.status})`)
  }
  return response.json()
}export async function fetchCasePromises(caseId: string): Promise<PaymentPromise[]> {
  const response = await fetch(`/api/cases/${caseId}/promises`)
  if (!response.ok) throw new Error("Failed to fetch promises")
  return response.json()
}

export async function fetchCasePaymentPlans(
  caseId: string,
): Promise<PaymentPlan[]> {
  const response = await fetch(`/api/cases/${caseId}/payment-plans`)
  if (!response.ok) throw new Error("Failed to fetch payment plans")
  return response.json()
}

export async function fetchCaseConversations(
  caseId: string,
): Promise<Conversation[]> {
  const response = await fetch(`/api/cases/${caseId}/conversations`)
  if (!response.ok) throw new Error("Failed to fetch conversations")
  return response.json()
}

export async function fetchCaseEmails(caseId: string): Promise<SentEmail[]> {
  const response = await fetch(`/api/cases/${caseId}/emails`)
  if (!response.ok) throw new Error("Failed to fetch emails")
  return response.json()
}

export async function fetchCaseVoiceCalls(caseId: string): Promise<VoiceCall[]> {
  const response = await fetch(`/api/cases/${caseId}/voice-calls`)
  if (!response.ok) throw new Error("Failed to fetch voice calls")
  return response.json()
}

export interface VoiceCallInitiateResult {
  status: string
  reason?: string
  stop_condition?: string
  case_id?: string
  to_phone?: string
  language?: string
}

/**
 * Trigger an outbound recovery voice call for a case.
 *
 * With Twilio credentials configured this places a real call; without them the
 * backend logs the attempt honestly and returns a preview (never a fake call).
 */
export async function initiateVoiceCall(
  caseId: string,
  toPhone: string,
  language = "en",
): Promise<VoiceCallInitiateResult> {
  const response = await fetch("/api/voice/outbound", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id: caseId, to_phone: toPhone, language }),
  })
  if (!response.ok) throw new Error("Failed to initiate voice call")
  return response.json()
}

export async function fetchCaseHardStops(
  caseId: string,
): Promise<HardStop[]> {
  const response = await fetch(`/api/cases/${caseId}/hard-stops`)
  if (!response.ok) throw new Error("Failed to fetch hard stops")
  return response.json()
}

export async function fetchCaseTimeline(
  caseId: string,
): Promise<RecoveryTimeline> {
  const response = await fetch(`/api/cases/${caseId}/timeline`)
  if (!response.ok) throw new Error("Failed to fetch timeline")
  return response.json()
}

export async function fetchCasePolicyTrace(
  caseId: string,
): Promise<PolicyTrace> {
  const response = await fetch(`/api/cases/${caseId}/policy-trace`)
  if (!response.ok) throw new Error("Failed to fetch policy trace")
  return response.json()
}

export async function fetchCaseSchedule(caseId: string): Promise<CaseSchedule> {
  const response = await fetch(`/api/cases/${caseId}/schedule`)
  if (!response.ok) throw new Error("Failed to fetch case schedule")
  return response.json()
}

export async function runAutonomousScheduler(): Promise<{
  total_due: number
  executed: number
  cancelled: number
  skipped: number
}> {
  const response = await fetch("/api/autonomous/scheduler/run", {
    method: "POST",
  })
  if (!response.ok) throw new Error("Failed to run autonomous scheduler")
  return response.json()
}

export interface SimulateSingleCaseResult {
  case_id: string
  customer_name: string
  original_amount: number
  risk_level: string
  status: string
}

/**
 * Create a single persisted simulation case in the backend database.
 *
 * Unlike the dashboard's client-side mock, this creates real DB rows
 * (Customer → RevenueEvent → RecoveryCase → AuditEvent → AgentSteps)
 * so the case survives page refreshes and can be navigated to from
 * the cases list.
 */
export async function simulateSingleCase(
  opts: { amount?: number; name?: string } = {},
): Promise<SimulateSingleCaseResult> {
  const body: Record<string, unknown> = {}
  if (opts.amount && opts.amount > 0) body.amount = opts.amount
  if (opts.name) body.name = opts.name
  const response = await fetch("/api/simulation/single", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error("Failed to create simulated case")
  return response.json() as Promise<SimulateSingleCaseResult>
}
