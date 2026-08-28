export interface RecoverySettings {
  merchant_id: string
  max_recovery_attempts: number
  recovery_window_days: number
  whatsapp_enabled: boolean
  email_enabled: boolean
  default_reminder_sequence: number[]
  payment_plan_enabled: boolean
  max_installments: number
  promise_to_pay_enabled: boolean
  hard_stop_enabled: boolean
  opt_out_enforced: boolean
  min_reminder_gap_hours: number
  updated_at: string | null
}

export interface RecoverySettingsUpdate {
  max_recovery_attempts: number
  recovery_window_days: number
  whatsapp_enabled: boolean
  email_enabled: boolean
  default_reminder_sequence: number[]
  payment_plan_enabled: boolean
  max_installments: number
  promise_to_pay_enabled: boolean
}