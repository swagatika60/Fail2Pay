from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PromiseCreate(BaseModel):
    recovery_case_id: UUID
    customer_id: UUID
    amount_promised: int  # in paise
    currency: str = "INR"
    promised_date: datetime
    promise_window_hours: int = 72
    customer_message: str | None = None
    extra_data: dict | None = None


class PromiseRead(BaseModel):
    id: UUID
    recovery_case_id: UUID
    customer_id: UUID
    amount_promised: int
    currency: str
    promised_date: datetime
    promise_window_hours: int
    expires_at: datetime
    customer_message: str | None
    status: str
    fulfilled_at: datetime | None
    fulfilled_amount: int
    missed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    extra_data: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
