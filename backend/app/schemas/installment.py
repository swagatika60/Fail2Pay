from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.installment import InstallmentStatus


class InstallmentCreate(BaseModel):
    payment_plan_id: UUID
    installment_number: int
    amount: int
    due_date: datetime


class InstallmentRead(BaseModel):
    id: UUID
    payment_plan_id: UUID
    installment_number: int
    amount: int
    due_date: datetime
    status: InstallmentStatus
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
