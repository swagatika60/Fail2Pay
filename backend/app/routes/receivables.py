"""B2B Receivables Chaser API Routes.

Endpoints for managing overdue receivable invoices, running escalation
batches, recording payments, and viewing the receivables dashboard.

Routes:
  POST   /api/receivables                          — Create a receivable invoice
  GET    /api/receivables                          — List all receivable invoices
  GET    /api/receivables/summary                  — Aggregate receivables metrics
  GET    /api/receivables/{id}                     — Get a single receivable invoice
  POST   /api/receivables/{id}/pay                 — Record a payment
  POST   /api/receivables/{id}/write-off           — Write off as uncollectible
  POST   /api/receivables/{id}/dispute             — Mark as disputed
  POST   /api/receivables/{id}/escalate            — Manually trigger escalation
  GET    /api/receivables/{id}/escalation-preview  — Preview next escalation
  GET    /api/receivables/{id}/events              — Get escalation event history
  POST   /api/receivables/batch/run                — Run batch overdue detection + escalation
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud.receivable_invoice import (
    create_receivable_invoice,
    get_receivable_invoice,
    list_receivable_invoices,
    record_payment,
    write_off_invoice,
    mark_disputed,
    get_escalation_events,
    get_receivables_summary,
)
from app.schemas.receivable_invoice import (
    ReceivableInvoiceCreate,
    ReceivableInvoiceRead,
    ReceivableInvoiceSummary,
    ReceivableEscalationEventRead,
    ReceivablesSummary,
    RecordPaymentRequest,
    WriteOffRequest,
    BatchOverdueCheckResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/receivables", tags=["receivables"])


# ============================================================
# Create
# ============================================================


@router.post("", response_model=ReceivableInvoiceRead, status_code=201)
def create_receivable(
    data: ReceivableInvoiceCreate,
    db: Session = Depends(get_db),
):
    """Create a new B2B receivable invoice for tracking."""
    # Check for duplicate invoice number
    from app.crud.receivable_invoice import get_receivable_invoice_by_number

    existing = get_receivable_invoice_by_number(db, data.invoice_number)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Invoice number '{data.invoice_number}' already exists",
        )

    invoice = create_receivable_invoice(db, data)
    return _to_read_model(invoice)


# ============================================================
# List & Summary
# ============================================================


@router.get("", response_model=list[ReceivableInvoiceSummary])
def list_receivables(
    status: str | None = None,
    escalation_tier: str | None = None,
    db: Session = Depends(get_db),
):
    """List all receivable invoices with optional filters."""
    invoices = list_receivable_invoices(db, status=status, escalation_tier=escalation_tier)
    return [_to_summary_model(inv) for inv in invoices]


@router.get("/summary", response_model=ReceivablesSummary)
def receivables_summary(db: Session = Depends(get_db)):
    """Aggregate receivables metrics for the dashboard."""
    data = get_receivables_summary(db)
    return ReceivablesSummary(**data)


# ============================================================
# Single Invoice
# ============================================================


@router.get("/{invoice_id}", response_model=ReceivableInvoiceRead)
def get_receivable(invoice_id: UUID, db: Session = Depends(get_db)):
    """Get full details of a single receivable invoice."""
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Receivable invoice not found")
    return _to_read_model(invoice)


# ============================================================
# Actions
# ============================================================


@router.post("/{invoice_id}/pay", response_model=ReceivableInvoiceRead)
def pay_receivable(
    invoice_id: UUID,
    data: RecordPaymentRequest,
    db: Session = Depends(get_db),
):
    """Record a payment against a receivable invoice."""
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Receivable invoice not found")

    if invoice.status == "PAYMENT_RECEIVED":
        raise HTTPException(
            status_code=400, detail="Invoice is already fully paid"
        )

    if invoice.status == "WRITTEN_OFF":
        raise HTTPException(
            status_code=400, detail="Cannot record payment on a written-off invoice"
        )

    updated = record_payment(
        db,
        invoice_id,
        amount=data.amount,
        payment_reference=data.payment_reference,
        notes=data.notes,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to record payment")

    # Log the payment event
    from app.crud.receivable_invoice import create_escalation_event

    create_escalation_event(
        db,
        receivable_invoice_id=invoice_id,
        event_type="payment_received",
        details={
            "amount": data.amount,
            "reference": data.payment_reference,
            "new_amount_paid": updated.amount_paid,
            "fully_settled": updated.is_fully_paid,
        },
    )

    return _to_read_model(updated)


@router.post("/{invoice_id}/write-off", response_model=ReceivableInvoiceRead)
def write_off(invoice_id: UUID, data: WriteOffRequest, db: Session = Depends(get_db)):
    """Write off a receivable invoice as uncollectible."""
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Receivable invoice not found")

    if invoice.status == "PAYMENT_RECEIVED":
        raise HTTPException(
            status_code=400, detail="Cannot write off a fully paid invoice"
        )

    updated = write_off_invoice(db, invoice_id, data.reason)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to write off invoice")

    from app.crud.receivable_invoice import create_escalation_event

    create_escalation_event(
        db,
        receivable_invoice_id=invoice_id,
        event_type="written_off",
        details={"reason": data.reason},
    )

    return _to_read_model(updated)


@router.post("/{invoice_id}/dispute", response_model=ReceivableInvoiceRead)
def dispute(invoice_id: UUID, db: Session = Depends(get_db)):
    """Mark a receivable invoice as disputed (pauses escalation)."""
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Receivable invoice not found")

    updated = mark_disputed(db, invoice_id)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to mark as disputed")

    from app.crud.receivable_invoice import create_escalation_event

    create_escalation_event(
        db,
        receivable_invoice_id=invoice_id,
        event_type="dispute_opened",
        details={"status": "DISPUTED"},
    )

    return _to_read_model(updated)


@router.post("/{invoice_id}/escalate")
def manually_escalate(invoice_id: UUID, db: Session = Depends(get_db)):
    """Manually trigger an escalation for a receivable invoice.

    Forces the escalation even if the cooldown hasn't elapsed.
    """
    from app.services.receivables_chaser import escalate_invoice

    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Receivable invoice not found")

    # Temporarily set next_escalation_at to now to bypass cooldown
    invoice.next_escalation_at = invoice.last_escalation_at  # will be <= now
    db.commit()
    db.refresh(invoice)

    result = escalate_invoice(db, str(invoice_id))
    if not result:
        raise HTTPException(
            status_code=400,
            detail="No escalation available (terminal state or max reached)",
        )

    return result


@router.get("/{invoice_id}/escalation-preview")
def escalation_preview(invoice_id: UUID, db: Session = Depends(get_db)):
    """Preview what the next escalation would look like."""
    from app.services.receivables_chaser import get_escalation_preview

    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Receivable invoice not found")

    return get_escalation_preview(invoice)


# ============================================================
# Events
# ============================================================


@router.get(
    "/{invoice_id}/events",
    response_model=list[ReceivableEscalationEventRead],
)
def escalation_events(invoice_id: UUID, db: Session = Depends(get_db)):
    """Get the full escalation event history for a receivable invoice."""
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Receivable invoice not found")

    events = get_escalation_events(db, invoice_id)
    return [
        ReceivableEscalationEventRead.model_validate(e) for e in events
    ]


# ============================================================
# Batch Operations
# ============================================================


@router.post("/batch/run", response_model=BatchOverdueCheckResult)
def run_batch(db: Session = Depends(get_db)):
    """Run the batch overdue detection + escalation cycle.

    Detects newly overdue invoices, escalates all that are due,
    and sends escalation emails. Typically called by a cron job.
    """
    from app.services.receivables_chaser import run_batch_escalation

    result = run_batch_escalation(db)
    return BatchOverdueCheckResult(**result)


# ============================================================
# Helpers
# ============================================================


def _to_read_model(invoice) -> ReceivableInvoiceRead:
    """Convert a SQLAlchemy model to a Pydantic read schema."""
    return ReceivableInvoiceRead(
        id=invoice.id,
        customer_id=invoice.customer_id,
        customer_name=invoice.customer_name,
        customer_email=invoice.customer_email,
        customer_company=invoice.customer_company,
        invoice_number=invoice.invoice_number,
        description=invoice.description,
        amount=invoice.amount,
        amount_paid=invoice.amount_paid,
        currency=invoice.currency,
        remaining_amount=invoice.remaining_amount,
        issued_at=invoice.issued_at,
        due_date=invoice.due_date,
        paid_at=invoice.paid_at,
        status=invoice.status,
        escalation_tier=invoice.escalation_tier,
        overdue_days=invoice.overdue_days(),
        last_escalation_at=invoice.last_escalation_at,
        next_escalation_at=invoice.next_escalation_at,
        escalation_count=invoice.escalation_count,
        max_escalations=invoice.max_escalations,
        extra_data=invoice.extra_data,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )


def _to_summary_model(invoice) -> ReceivableInvoiceSummary:
    """Convert a SQLAlchemy model to a summary schema."""
    return ReceivableInvoiceSummary(
        id=invoice.id,
        customer_name=invoice.customer_name,
        customer_company=invoice.customer_company,
        invoice_number=invoice.invoice_number,
        amount=invoice.amount,
        amount_paid=invoice.amount_paid,
        remaining_amount=invoice.remaining_amount,
        status=invoice.status,
        escalation_tier=invoice.escalation_tier,
        overdue_days=invoice.overdue_days(),
        due_date=invoice.due_date,
        created_at=invoice.created_at,
    )
