"""Analytics schemas for the Revenue Map dashboard."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RevenueSummary(BaseModel):
    """Summary metrics for the dashboard."""

    expected_revenue: int  # total original amounts
    collected_revenue: int  # sum of recovered amounts
    revenue_at_risk: int  # AT_RISK cases total
    recovery_in_progress: int  # RECOVERY_IN_PROGRESS cases total
    promised_revenue: int  # PROMISED cases total
    scheduled_revenue: int  # SCHEDULED cases total
    partially_recovered: int  # PARTIALLY_RECOVERED cases total
    recovered_revenue: int  # RECOVERED cases total
    lost_revenue: int  # LOST cases total
    # Metrics
    total_revenue: int
    revenue_recovered: int
    revenue_remaining: int
    recovery_rate: float  # recovered / at_risk, 0.0 if no at_risk
    # Self-cure baseline: cases recovered without any outreach
    self_cure_count: int = 0
    self_cure_amount: int = 0
    self_cure_rate: float = 0.0  # self-cure / total_recovered
    lift_over_self_cure: float = 0.0  # recovery_rate vs self-cure_rate


class FunnelStage(BaseModel):
    """One stage of the revenue funnel (real amounts, clearly labelled)."""

    name: str
    amount: int
    tooltip: str = ""


class ChannelSlice(BaseModel):
    channel: str
    name: str
    amount: int
    count: int


class RiskLevelSlice(BaseModel):
    risk_level: str
    amount: int
    count: int


class LanguageSlice(BaseModel):
    language: str
    name: str
    amount: int
    count: int


class TimelinePoint(BaseModel):
    label: str
    recovered: int
    cumulative: int


class PipelineStage(BaseModel):
    """One stage of the canonical recovery pipeline (unified tracker widget)."""

    stage: str
    label: str
    index: int
    amount: int = 0
    count: int = 0


class RecoveryCost(BaseModel):
    """Approximate cost of recovery outreach vs verified revenue."""

    whatsapp_messages: int = 0
    emails: int = 0
    whatsapp_cost_paise: int = 0
    email_cost_paise: int = 0
    total_cost_paise: int = 0
    recovered_revenue: int = 0
    cost_of_recovery_ratio: float = 0.0


class PaymentPlanRecovery(BaseModel):
    plans_count: int
    total_amount: int
    recovered_amount: int
    remaining_amount: int
    recovery_rate: float


class PromiseToPayRecovery(BaseModel):
    promised_cases: int
    promised_amount: int
    recovered_amount: int
    outstanding_amount: int
    recovery_rate: float


class RevenueMap(BaseModel):
    """Full Revenue Map analytics — verified money only.

    ``recovered_revenue`` is the sum of captured (verified) payments.
    ``attempted_recovery`` is the pool money recovery engaged, shown
    separately from verified recovered revenue.
    """

    total_revenue: int
    at_risk_revenue: int
    recovered_revenue: int
    lost_revenue: int
    recovery_rate: float
    avg_recovery_time_days: float
    avg_attempts_before_recovery: float
    attempted_recovery: int
    attempted_unfulfilled: int
    payments_count: int
    cases_count: int
    funnel: list[FunnelStage] = []
    recovery_by_channel: list[ChannelSlice] = []
    recovery_by_risk_level: list[RiskLevelSlice] = []
    recovery_by_language: list[LanguageSlice] = []
    payment_plan_recovery: PaymentPlanRecovery
    promise_to_pay_recovery: PromiseToPayRecovery
    recovery_timeline: list[TimelinePoint] = []
    recovery_pipeline: list[PipelineStage] = []
    recovery_cost: RecoveryCost = RecoveryCost()


class RecoveryCaseSummary(BaseModel):
    """Summary of a recovery case for the table."""

    id: UUID
    customer_name: str | None
    customer_email: str | None
    original_amount: int
    risk_level: str
    status: str
    recovery_stage: str | None = None
    recovered_amount: int
    remaining_amount: int
    attempt_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecoveryCaseDetail(BaseModel):
    """Full details of a recovery case."""

    id: UUID
    customer_id: UUID
    customer_name: str | None
    customer_email: str | None
    customer_phone: str | None
    revenue_event_id: UUID
    risk_level: str
    risk_reason: str | None
    status: str
    recovery_stage: str | None = None
    recovery_stage_index: int | None = None
    original_amount: int
    recovered_amount: int
    remaining_amount: int
    attempt_count: int
    max_attempts: int
    recovery_started_at: datetime | None
    recovery_deadline: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Related data
    event_type: str | None = None
    source: str | None = None
    currency: str = "INR"
    failure_reason: str | None = None
    root_cause: str | None = None
    audit_events: list[dict] | None = None
    agent_steps: list[dict] | None = None

    model_config = {"from_attributes": True}
