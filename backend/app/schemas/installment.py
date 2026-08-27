from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class InstallmentCreate(BaseModel):
    payment_plan_id: UUID
    recovery_case_id: UUID | None = None
    installment_number: int
    amount: int  # in paise
    due_date: datetime
    currency: str = "INR"


class InstallmentRead(BaseModel):
    id: UUID
    payment_plan_id: UUID
    recovery_case_id: UUID | None
    installment_number: int
    amount: int
    due_date: datetime
    currency: str
    status: str
    paid_at: datetime | None
    paid_amount: int
    failed_at: datetime | None
    failure_reason: str | None
    razorpay_payment_id: str | None
    razorpay_order_id: str | None
    extra_data: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
