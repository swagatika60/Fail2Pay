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


class RecoveryCaseSummary(BaseModel):
    """Summary of a recovery case for the table."""

    id: UUID
    customer_name: str | None
    customer_email: str | None
    original_amount: int
    risk_level: str
    status: str
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
    audit_events: list[dict] | None = None

    model_config = {"from_attributes": True}
