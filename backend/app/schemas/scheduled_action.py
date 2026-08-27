from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ScheduledActionCreate(BaseModel):
    recovery_case_id: UUID
    action_type: str  # "initial_message", "reminder", "final_notice", "payment_check"
    attempt_number: int
    channel: str  # "whatsapp", "email", "sms"
    scheduled_for: datetime
    extra_data: dict | None = None


class ScheduledActionRead(BaseModel):
    id: UUID
    recovery_case_id: UUID
    action_type: str
    attempt_number: int
    channel: str
    scheduled_for: datetime
    status: str
    executed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    extra_data: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
