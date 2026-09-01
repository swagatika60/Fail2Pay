"""CRUD operations for B2B Receivable Invoices."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.receivable_invoice import (
    ReceivableInvoice,
    ReceivableStatus,
    ReceivableEscalationEvent,
)
from app.schemas.receivable_invoice import ReceivableInvoiceCreate


# --- Create ---

def create_receivable_invoice(
    db: Session, data: ReceivableInvoiceCreate
) -> ReceivableInvoice:
    """Create a new B2B receivable invoice."""
    invoice = ReceivableInvoice(
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        customer_company=data.customer_company,
        invoice_number=data.invoice_number,
        description=data.description,
        amount=data.amount,
        amount_paid=0,
        currency=data.currency,
        issued_at=data.issued_at,
        due_date=data.due_date,
        status=ReceivableStatus.PENDING.value,
        escalation_tier="NONE",
        extra_data=data.extra_data,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


# --- Read ---

def get_receivable_invoice(
    db: Session, invoice_id: UUID | str
) -> ReceivableInvoice | None:
    """Fetch a single receivable invoice by ID."""
    if isinstance(invoice_id, str):
        invoice_id = UUID(invoice_id)
    return db.execute(
        select(ReceivableInvoice).where(ReceivableInvoice.id == invoice_id)
    ).scalar_one_or_none()


def get_receivable_invoice_by_number(
    db: Session, invoice_number: str
) -> ReceivableInvoice | None:
    """Fetch a receivable invoice by its human-readable invoice number."""
    return db.execute(
        select(ReceivableInvoice).where(
            ReceivableInvoice.invoice_number == invoice_number
        )
    ).scalar_one_or_none()


def list_receivable_invoices(
    db: Session,
    status: str | None = None,
    escalation_tier: str | None = None,
    customer_id: UUID | None = None,
) -> list[ReceivableInvoice]:
    """List receivable invoices with optional filters."""
    stmt = select(ReceivableInvoice)
    if status:
        stmt = stmt.where(ReceivableInvoice.status == status)
    if escalation_tier:
        stmt = stmt.where(ReceivableInvoice.escalation_tier == escalation_tier)
    if customer_id:
        stmt = stmt.where(ReceivableInvoice.customer_id == customer_id)
    stmt = stmt.order_by(ReceivableInvoice.due_date.asc())
    return list(db.execute(stmt).scalars().all())


def get_overdue_invoices(db: Session) -> list[ReceivableInvoice]:
    """Get all invoices that are past due and not yet fully paid."""
    now = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(ReceivableInvoice).where(
                ReceivableInvoice.due_date < now,
                ReceivableInvoice.status.notin_([
                    ReceivableStatus.PAYMENT_RECEIVED.value,
                    ReceivableStatus.WRITTEN_OFF.value,
                    ReceivableStatus.DISPUTED.value,
                ]),
            )
        ).scalars().all()
    )


def get_invoices_due_for_escalation(db: Session) -> list[ReceivableInvoice]:
    """Get invoices whose next_escalation_at has arrived."""
    now = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(ReceivableInvoice).where(
                ReceivableInvoice.next_escalation_at <= now,
                ReceivableInvoice.next_escalation_at.isnot(None),
                ReceivableInvoice.status.notin_([
                    ReceivableStatus.PAYMENT_RECEIVED.value,
                    ReceivableStatus.WRITTEN_OFF.value,
                    ReceivableStatus.DISPUTED.value,
                ]),
            )
        ).scalars().all()
    )


# --- Update ---

def record_payment(
    db: Session,
    invoice_id: UUID,
    amount: int,
    payment_reference: str | None = None,
    notes: str | None = None,
) -> ReceivableInvoice | None:
    """Record a payment against a receivable invoice.

    Updates amount_paid, status, and paid_at if fully settled.
    """
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        return None

    invoice.amount_paid = min(invoice.amount, invoice.amount_paid + amount)

    if invoice.amount_paid >= invoice.amount:
        invoice.status = ReceivableStatus.PAYMENT_RECEIVED.value
        invoice.paid_at = datetime.now(timezone.utc)
        invoice.escalation_tier = "NONE"
        invoice.next_escalation_at = None
    else:
        invoice.status = ReceivableStatus.PARTIALLY_PAID.value

    # Merge payment record into extra_data
    extra = dict(invoice.extra_data or {})
    payments = extra.get("payments", [])
    payments.append({
        "amount": amount,
        "reference": payment_reference,
        "notes": notes,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    extra["payments"] = payments
    invoice.extra_data = extra

    db.commit()
    db.refresh(invoice)
    return invoice


def update_escalation_tier(
    db: Session,
    invoice_id: UUID,
    new_tier: str,
    next_escalation_at: datetime | None = None,
) -> ReceivableInvoice | None:
    """Update the escalation tier for a receivable invoice."""
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        return None

    old_tier = invoice.escalation_tier
    invoice.escalation_tier = new_tier
    invoice.last_escalation_at = datetime.now(timezone.utc)
    invoice.escalation_count += 1
    invoice.next_escalation_at = next_escalation_at

    # Also update status to IN_ESCALATION if currently overdue
    if invoice.status in (
        ReceivableStatus.OVERDUE.value,
        ReceivableStatus.IN_ESCALATION.value,
    ):
        invoice.status = ReceivableStatus.IN_ESCALATION.value

    db.commit()
    db.refresh(invoice)
    return invoice, old_tier


def write_off_invoice(
    db: Session, invoice_id: UUID, reason: str
) -> ReceivableInvoice | None:
    """Write off a receivable invoice as uncollectible."""
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        return None

    invoice.status = ReceivableStatus.WRITTEN_OFF.value
    invoice.escalation_tier = "NONE"
    invoice.next_escalation_at = None
    extra = dict(invoice.extra_data or {})
    extra["write_off_reason"] = reason
    extra["written_off_at"] = datetime.now(timezone.utc).isoformat()
    invoice.extra_data = extra

    db.commit()
    db.refresh(invoice)
    return invoice


def mark_disputed(db: Session, invoice_id: UUID) -> ReceivableInvoice | None:
    """Mark a receivable invoice as disputed (pauses escalation)."""
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        return None

    invoice.status = ReceivableStatus.DISPUTED.value
    invoice.escalation_tier = "NONE"
    invoice.next_escalation_at = None

    db.commit()
    db.refresh(invoice)
    return invoice


# --- Escalation Events ---

def create_escalation_event(
    db: Session,
    receivable_invoice_id: UUID,
    event_type: str,
    old_tier: str | None = None,
    new_tier: str | None = None,
    details: dict | None = None,
) -> ReceivableEscalationEvent:
    """Log an escalation event for audit trail."""
    event = ReceivableEscalationEvent(
        receivable_invoice_id=receivable_invoice_id,
        event_type=event_type,
        old_tier=old_tier,
        new_tier=new_tier,
        details=details,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_escalation_events(
    db: Session, receivable_invoice_id: UUID
) -> list[ReceivableEscalationEvent]:
    """Get all escalation events for a receivable invoice."""
    return list(
        db.execute(
            select(ReceivableEscalationEvent)
            .where(
                ReceivableEscalationEvent.receivable_invoice_id
                == receivable_invoice_id
            )
            .order_by(ReceivableEscalationEvent.created_at.asc())
        ).scalars().all()
    )


# --- Aggregate ---

def get_receivables_summary(db: Session) -> dict:
    """Compute aggregate receivables metrics."""
    all_invoices = list(
        db.execute(select(ReceivableInvoice)).scalars().all()
    )

    total_outstanding = 0
    total_invoices = len(all_invoices)
    overdue_count = 0
    overdue_amount = 0
    paid_count = 0
    paid_amount = 0
    tier_counts: dict[str, int] = {}
    collection_days: list[int] = []

    for inv in all_invoices:
        tier_counts[inv.escalation_tier] = tier_counts.get(inv.escalation_tier, 0) + 1

        if inv.status == ReceivableStatus.PAYMENT_RECEIVED.value:
            paid_count += 1
            paid_amount += inv.amount
            # Compute collection time
            if inv.paid_at and inv.due_date:
                days_to_collect = max(0, (inv.paid_at - inv.due_date).days)
                collection_days.append(days_to_collect)
        elif inv.status not in (
            ReceivableStatus.WRITTEN_OFF.value,
            ReceivableStatus.DISPUTED.value,
        ):
            remaining = inv.remaining_amount
            if inv.overdue_days() > 0:
                overdue_count += 1
                overdue_amount += remaining
            total_outstanding += remaining

    total_amount = sum(inv.amount for inv in all_invoices)
    collection_rate = (paid_amount / total_amount) if total_amount > 0 else 0.0
    avg_days = (
        sum(collection_days) / len(collection_days) if collection_days else None
    )

    return {
        "total_outstanding": total_outstanding,
        "total_invoices": total_invoices,
        "overdue_count": overdue_count,
        "overdue_amount": overdue_amount,
        "paid_count": paid_count,
        "paid_amount": paid_amount,
        "by_escalation_tier": tier_counts,
        "collection_rate": round(collection_rate, 4),
        "avg_days_to_collect": round(avg_days, 1) if avg_days is not None else None,
    }
