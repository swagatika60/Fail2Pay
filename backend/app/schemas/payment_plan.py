from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.payment_plan import PaymentPlanStatus


class PaymentPlanCreate(BaseModel):
    recovery_case_id: UUID
    total_amount: int
    number_of_installments: int
    frequency: str  # "weekly", "monthly"


class PaymentPlanRead(BaseModel):
    id: UUID
    recovery_case_id: UUID
    total_amount: int
    number_of_installments: int
    frequency: str
    status: PaymentPlanStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
