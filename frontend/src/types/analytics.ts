export interface RevenueMap {
  total_revenue: number
  at_risk_revenue: number
  recovered_revenue: number
  lost_revenue: number
  recovery_rate: number
  avg_recovery_time_days: number
  avg_attempts_before_recovery: number
  attempted_recovery: number
  attempted_unfulfilled: number
  payments_count: number
  cases_count: number
  funnel: { name: string; amount: number; tooltip: string }[]
  recovery_by_channel: {
    channel: string
    name: string
    amount: number
    count: number
  }[]
  recovery_by_risk_level: {
    risk_level: string
    amount: number
    count: number
  }[]
  recovery_by_language: {
    language: string
    name: string
    amount: number
    count: number
  }[]
  recovery_by_failure_reason: {
    failure_reason: string
    name: string
    amount: number
    count: number
  }[]
  payment_plan_recovery: {
    plans_count: number
    total_amount: number
    recovered_amount: number
    remaining_amount: number
    recovery_rate: number
  }
  promise_to_pay_recovery: {
    promised_cases: number
    promised_amount: number
    recovered_amount: number
    outstanding_amount: number
    recovery_rate: number
  }
  recovery_timeline: { label: string; recovered: number; cumulative: number }[]
  recovery_pipeline: RecoveryPipelineStage[]
  recovery_cost: RecoveryCost
}

export interface RecoveryPipelineStage {
  stage: string
  label: string
  index: number
  amount: number
  count: number
}

export interface RecoveryCost {
  whatsapp_messages: number
  emails: number
  whatsapp_cost_paise: number
  email_cost_paise: number
  total_cost_paise: number
  recovered_revenue: number
  cost_of_recovery_ratio: number
}

export interface AgentStep {
  step_id: string
  stage: string
  type: string
  label: string
  detail?: string | null
  confidence?: number | null
  latency_ms?: number | null
  occurred_at?: string | null
  extra?: Record<string, unknown>
}

export interface AgentStepsResponse {
  case_id: string
  steps: AgentStep[]
  summary: {
    step_count: number
    by_stage: Record<string, number>
    avg_latency_ms: number
    max_latency_ms: number
  }
}

export interface RevenueSummary {
  expected_revenue: number
  collected_revenue: number
  revenue_at_risk: number
  recovery_in_progress: number
  promised_revenue: number
  scheduled_revenue: number
  partially_recovered: number
  recovered_revenue: number
  lost_revenue: number
  total_revenue: number
  revenue_recovered: number
  revenue_remaining: number
  recovery_rate: number
  self_cure_count: number
  self_cure_amount: number
  self_cure_rate: number
  lift_over_self_cure: number
}

export interface RecoveryCaseSummary {
  id: string
  customer_name: string | null
  customer_email: string | null
  original_amount: number
  risk_level: string
  status: string
  recovery_stage?: string | null
  recovered_amount: number
  remaining_amount: number
  attempt_count: number
  created_at: string
  updated_at: string
}

export interface AuditEvent {
  id: string
  action: string
  entity_type: string
  old_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  created_at: string | null
}

export interface PaymentPromise {
  id: string
  amount_promised: number
  currency: string
  promised_date: string | null
  expires_at: string | null
  status: string
  customer_message: string | null
  fulfilled_at: string | null
  fulfilled_amount: number
  missed_at: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  created_at: string | null
}

export interface Installment {
  id: string
  installment_number: number
  amount: number
  due_date: string | null
  status: string
  paid_at: string | null
  paid_amount: number
  failed_at: string | null
  failure_reason: string | null
  razorpay_payment_id: string | null
}

export interface PaymentPlan {
  id: string
  total_amount: number
  installment_amount: number
  number_of_installments: number
  frequency: string
  currency: string
  status: string
  amount_paid: number
  installments_paid: number
  installments_failed: number
  first_payment_date: string | null
  last_payment_date: string | null
  completed_at: string | null
  created_at: string | null
  installments: Installment[]
}

export interface ConversationMessage {
  id: string
  direction: string
  content: string
  message_type: string
  extra_data: Record<string, unknown> | null
  created_at: string | null
}

export interface Conversation {
  id: string
  channel: string
  status: string
  created_at: string | null
  messages: ConversationMessage[]
}

export interface VoiceCall {
  id: string
  call_sid: string
  direction: string
  duration_seconds: number
  transcription: string
  intent: string
  dtmf_input: string
  language: string
  status: string
  created_at: string | null
}

export interface SentEmail {
  id: string
  email_type: string
  recipient_email: string
  subject: string
  body: string
  delivery_status: string
  provider_message_id: string | null
  error_message: string | null
  sent_at: string | null
  delivered_at: string | null
  created_at: string | null
}

export interface HardStop {
  id: string
  action: string
  new_value: Record<string, unknown> | null
  created_at: string | null
}

export interface TimelineEvent {
  id: string
  event_type: string
  timestamp: string | null
  description: string
  icon: string
  color: string
  entity_type: string
  old_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  result: string
  reason: string
  amount: number | null
  amount_formatted: string | null
  metadata: Record<string, unknown>
}

export interface TimelineSummary {
  total_events: number
  event_counts: Record<string, number>
  first_event_at: string | null
  last_event_at: string | null
  messages_sent: number
  messages_failed: number
  customer_replies: number
  payments_recovered: number
  original_amount: number
  recovered_amount: number
  recovery_rate: number
}

export interface RecoveryTimeline {
  case: {
    case_id: string
    customer_name: string
    customer_email: string | null
    customer_phone: string | null
    original_amount: number
    recovered_amount: number
    remaining_amount: number
    status: string
    risk_level: string
    attempt_count: number
    max_attempts: number
  }
  timeline: TimelineEvent[]
  total_events: number
  summary: TimelineSummary
}

export interface PolicyTraceNode {
  id: string
  event_type: string
  timestamp: string | null
  reason: string
  result: string
  amount: number | null
  amount_formatted: string | null
  metadata: Record<string, unknown>
  old_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  layer: "trigger" | "ai_judgment" | "policy" | "action" | "outcome"
}

export interface PolicyTrace {
  case_id: string
  original_amount: number
  recovered_amount: number
  remaining_amount: number
  status: string
  chain: PolicyTraceNode[]
  layer_counts: Record<string, number>
}

export interface ScheduledActionSummary {
  action_id: string
  action_type: string
  attempt_number: number
  channel: string
  scheduled_for: string | null
  due: boolean
}

export interface CaseSchedule {
  case_id: string
  total_actions: number
  pending_count: number
  executed_count: number
  cancelled_count: number
  next_action: ScheduledActionSummary | null
  pending: ScheduledActionSummary[]
}

export interface RecoveryCaseDetail {
  id: string
  customer_id: string
  customer_name: string | null
  customer_email: string | null
  customer_phone: string | null
  revenue_event_id: string
  risk_level: string
  risk_reason: string | null
  status: string
  recovery_stage?: string | null
  recovery_stage_index?: number | null
  original_amount: number
  recovered_amount: number
  remaining_amount: number
  attempt_count: number
  max_attempts: number
  recovery_started_at: string | null
  recovery_deadline: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
  event_type: string | null
  source: string | null
  currency: string
  failure_reason: string | null
  root_cause?: string | null
  extra_data?: Record<string, unknown> | null
  audit_events: AuditEvent[] | null
  agent_steps?: AgentStep[] | null
}

export interface ImpactLedgerStage {
  count: number
  amount: number
}

export interface ImpactLedgerFunnel {
  at_risk: ImpactLedgerStage
  intervention_dispatched: ImpactLedgerStage
  promise_captured: ImpactLedgerStage
  verified_recovered: ImpactLedgerStage
}

export interface ImpactLedgerRow {
  case_id: string
  risk_level: string
  status: string
  original_amount: number
  verified_recovered_amount: number
  remaining_amount: number
  intervention_dispatched: boolean
  promise_captured: boolean
  verified_recovered: boolean
}

export interface VerifiedImpactLedger {
  present: boolean
  summary: {
    original_revenue: number
    verified_recovered: number
    revenue_at_risk: number
    recovery_rate: number
  }
  funnel: ImpactLedgerFunnel
  ledger: ImpactLedgerRow[]
}
