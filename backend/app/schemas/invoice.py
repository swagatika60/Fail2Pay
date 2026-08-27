from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class InvoiceCreate(BaseModel):
    recovery_case_id: UUID | None = None
    customer_id: UUID | None = None
    invoice_number: str
    amount: int  # in paise
    currency: str = "INR"
    description: str | None = None
    customer_name: str | None = None
    customer_email: str | None = None


class InvoiceRead(BaseModel):
    id: UUID
    recovery_case_id: UUID | None
    customer_id: UUID | None
    invoice_number: str
    amount: int
    currency: str
    description: str | None
    customer_name: str | None
    customer_email: str | None
    status: str
    issued_at: datetime | None
    paid_at: datetime | None
    viewed_at: datetime | None
    secure_token: str
    token_expires_at: datetime | None
    access_count: int
    delivered_via: str | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceAccessRequest(BaseModel):
    """Request to access an invoice via secure token."""
    token: str


class InvoiceAccessResponse(BaseModel):
    """Response with invoice details for secure access."""
    id: UUID
    invoice_number: str
    amount: int
    currency: str
    description: str | None
    customer_name: str | None
    status: str
    issued_at: datetime | None
    paid_at: datetime | None
    payment_link: str | None = None
