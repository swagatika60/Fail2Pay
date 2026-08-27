from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PaymentPlanCreate(BaseModel):
    recovery_case_id: UUID
    customer_id: UUID | None = None
    total_amount: int  # in paise
    installment_amount: int  # in paise
    number_of_installments: int
    frequency: str  # "weekly", "biweekly", "monthly"
    currency: str = "INR"
    first_payment_date: datetime | None = None
    customer_message: str | None = None


class PaymentPlanRead(BaseModel):
    id: UUID
    recovery_case_id: UUID
    customer_id: UUID | None
    total_amount: int
    installment_amount: int
    number_of_installments: int
    frequency: str
    currency: str
    first_payment_date: datetime | None
    last_payment_date: datetime | None
    completed_at: datetime | None
    status: str
    amount_paid: int
    installments_paid: int
    installments_failed: int
    customer_message: str | None
    agreed_at: datetime | None
    razorpay_plan_id: str | None
    razorpay_subscription_id: str | None
    extra_data: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
