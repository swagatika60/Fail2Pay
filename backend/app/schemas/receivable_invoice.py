"""Schemas for B2B Receivable Invoices."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# --- Create ---

class ReceivableInvoiceCreate(BaseModel):
    """Create a new B2B receivable invoice for tracking."""

    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_email: str = Field(..., min_length=1, max_length=255)
    customer_company: str | None = Field(default=None, max_length=255)
    customer_id: UUID | None = Field(default=None, description="Link to existing customer")
    invoice_number: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    amount: int = Field(..., gt=0, description="Total invoice amount in paise")
    currency: str = Field(default="INR", max_length=10)
    issued_at: datetime
    due_date: datetime
    extra_data: dict | None = None


# --- Read ---

class ReceivableInvoiceRead(BaseModel):
    """Full representation of a receivable invoice."""

    id: UUID
    customer_id: UUID | None
    customer_name: str
    customer_email: str
    customer_company: str | None
    invoice_number: str
    description: str | None
    amount: int
    amount_paid: int
    currency: str
    remaining_amount: int
    issued_at: datetime
    due_date: datetime
    paid_at: datetime | None
    status: str
    escalation_tier: str
    overdue_days: int
    last_escalation_at: datetime | None
    next_escalation_at: datetime | None
    escalation_count: int
    max_escalations: int
    extra_data: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReceivableInvoiceSummary(BaseModel):
    """Compact summary for list views / dashboard."""

    id: UUID
    customer_name: str
    customer_company: str | None
    invoice_number: str
    amount: int
    amount_paid: int
    remaining_amount: int
    status: str
    escalation_tier: str
    overdue_days: int
    due_date: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Escalation Event ---

class ReceivableEscalationEventRead(BaseModel):
    """An escalation event on a receivable invoice."""

    id: UUID
    receivable_invoice_id: UUID
    event_type: str
    old_tier: str | None
    new_tier: str | None
    details: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Dashboard ---

class ReceivablesSummary(BaseModel):
    """Aggregate receivables metrics for the dashboard."""

    total_outstanding: int = Field(description="Total outstanding amount in paise")
    total_invoices: int
    overdue_count: int
    overdue_amount: int = Field(description="Amount overdue in paise")
    paid_count: int
    paid_amount: int = Field(description="Amount fully paid in paise")
    by_escalation_tier: dict[str, int] = Field(
        description="Count of invoices per escalation tier"
    )
    collection_rate: float = Field(description="paid_amount / total_invoices_amount")
    avg_days_to_collect: float | None = Field(
        default=None,
        description="Average days from due_date to payment for collected invoices",
    )


# --- Action requests ---

class RecordPaymentRequest(BaseModel):
    """Record a payment against a receivable invoice."""

    amount: int = Field(..., gt=0, description="Payment amount in paise")
    payment_reference: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class WriteOffRequest(BaseModel):
    """Write off a receivable invoice as uncollectible."""

    reason: str = Field(..., min_length=1, max_length=500)


class UpdateEscalationConfigRequest(BaseModel):
    """Update escalation thresholds or max escalations for an invoice."""

    max_escalations: int | None = Field(default=None, ge=1, le=50)


# --- Batch operations ---

class BatchOverdueCheckResult(BaseModel):
    """Result of a batch overdue detection scan."""

    scanned: int
    newly_overdue: int
    escalated: int
    emails_sent: int
    details: list[dict] = Field(default_factory=list)
