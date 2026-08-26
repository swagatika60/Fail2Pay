from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.recovery_case import RecoveryStatus


class RecoveryCaseCreate(BaseModel):
    customer_id: UUID
    revenue_event_id: UUID
    risk_level: str  # "high", "medium", "low"
    risk_reason: str | None = None
    original_amount: int
    remaining_amount: int
    max_attempts: int = 5


class RecoveryCaseRead(BaseModel):
    id: UUID
    customer_id: UUID
    revenue_event_id: UUID
    risk_level: str
    risk_reason: str | None
    status: RecoveryStatus
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

    model_config = {"from_attributes": True}
