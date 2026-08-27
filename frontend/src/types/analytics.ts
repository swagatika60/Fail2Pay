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
}

export interface RecoveryCaseSummary {
  id: string
  customer_name: string | null
  customer_email: string | null
  original_amount: number
  risk_level: string
  status: string
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
  audit_events: AuditEvent[] | null
}
