from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.invoice import InvoiceStatus


class InvoiceCreate(BaseModel):
    payment_plan_id: UUID
    invoice_number: str
    amount: int


class InvoiceRead(BaseModel):
    id: UUID
    payment_plan_id: UUID
    invoice_number: str
    amount: int
    status: InvoiceStatus
    issued_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
