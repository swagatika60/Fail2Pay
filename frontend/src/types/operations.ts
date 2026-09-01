export interface CaseCustomerContext {
  case_id: string
  case_status: string | null
  case_risk_level: string | null
  customer_name: string | null
  customer_email: string | null
  customer_phone: string | null
}

export interface PlanProgress {
  paid_installments: number
  failed_installments: number
  total_installments: number
  remaining_installments: number
  paid_amount: number
  remaining_amount: number
  percent_paid: number
}

export interface PlanDegradation {
  degraded: boolean
  fail_threshold: number
  failed_count: number
  strategy: string | null
  strategy_label: string | null
}

export interface PaymentPlanListItem extends CaseCustomerContext {
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
  customer_message: string | null
  agreed_at: string | null
  first_payment_date: string | null
  last_payment_date: string | null
  completed_at: string | null
  created_at: string | null
  degradation: PlanDegradation
  progress: PlanProgress
}

export interface ConversationMessageItem {
  id: string
  direction: string
  content: string
  message_type: string | null
  created_at: string | null
}

export interface ConversationListItem extends CaseCustomerContext {
  id: string
  channel: string
  status: string
  created_at: string | null
  updated_at: string | null
  message_count: number
  outbound_count: number
  inbound_count: number
  last_message: {
    direction: string
    content: string
    created_at: string | null
  } | null
  messages: ConversationMessageItem[]
}

export interface InvoiceListItem extends CaseCustomerContext {
  id: string
  invoice_number: string
  amount: number
  currency: string
  description: string | null
  status: string
  issued_at: string | null
  paid_at: string | null
  viewed_at: string | null
  token_expires_at: string | null
  access_count: number
  delivered_via: string | null
  delivered_at: string | null
  created_at: string | null
  secure_token: string
}

export interface CheckoutAbandonmentItem {
  id: string
  customer_id: string
  customer_name: string | null
  customer_email: string | null
  customer_phone: string | null
  cart_ref: string
  amount: number
  currency: string
  item_count: number
  source: string
  abandonment_reason: string | null
  cause: string
  status: string
  reengagement_count: number
  reengagement_channel: string | null
  abandoned_at: string | null
  last_reengagement_at: string | null
  created_at: string | null
  recovery_case_id: string | null
}

export interface CheckoutSummary {
  total: number
  total_amount: number
  recovered: number
  abandoned: number
  recovering: number
  lost: number
  recovery_rate: number
}

export interface SubscriptionFailureItem {
  id: string
  customer_id: string
  customer_name: string | null
  customer_email: string | null
  customer_phone: string | null
  subscription_id: string
  plan_id: string | null
  plan_name: string | null
  billing_cycle: string | null
  amount: number
  currency: string
  failure_code: string | null
  failure_reason: string | null
  cause: string
  status: string
  retry_count: number
  max_retries: number
  days_until_churn: number | null
  failed_at: string | null
  next_retry_at: string | null
  last_retry_at: string | null
  created_at: string | null
  recovery_case_id: string | null
}

export interface SubscriptionSummary {
  total: number
  total_amount: number
  failed: number
  retrying: number
  recovered: number
  churned: number
  retention_rate: number
}