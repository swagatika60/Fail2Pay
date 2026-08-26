from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RevenueEventCreate(BaseModel):
    customer_id: UUID
    external_event_id: str  # razorpay payment id
    event_type: str
    amount: int
    currency: str = "INR"
    status: str
    source: str
    extra_data: dict | None = None


class RevenueEventRead(BaseModel):
    id: UUID
    customer_id: UUID
    external_event_id: str
    event_type: str
    amount: int
    currency: str
    status: str
    source: str
    extra_data: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
