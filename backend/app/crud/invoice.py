import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.invoice import InvoiceCreate


def create_invoice(db: Session, data: InvoiceCreate) -> Invoice:
    """Create a new invoice."""
    invoice = Invoice(**data.model_dump())
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def get_invoice(db: Session, invoice_id: uuid.UUID) -> Invoice | None:
    """Get a single invoice by ID."""
    return db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    ).scalar_one_or_none()


def get_invoice_by_number(db: Session, invoice_number: str) -> Invoice | None:
    """Get invoice by invoice number."""
    return db.execute(
        select(Invoice).where(Invoice.invoice_number == invoice_number)
    ).scalar_one_or_none()


def get_invoice_by_token(db: Session, token: str) -> Invoice | None:
    """Get invoice by secure access token."""
    return db.execute(
        select(Invoice).where(Invoice.secure_token == token)
    ).scalar_one_or_none()


def get_invoices_by_case(db: Session, case_id: uuid.UUID) -> list[Invoice]:
    """Get all invoices for a recovery case."""
    return list(
        db.execute(
            select(Invoice)
            .where(Invoice.recovery_case_id == case_id)
            .order_by(Invoice.created_at.desc())
        ).scalars().all()
    )


def get_invoices_by_customer(db: Session, customer_id: uuid.UUID) -> list[Invoice]:
    """Get all invoices for a customer."""
    return list(
        db.execute(
            select(Invoice)
            .where(Invoice.customer_id == customer_id)
            .order_by(Invoice.created_at.desc())
        ).scalars().all()
    )


def mark_invoice_viewed(db: Session, invoice_id: uuid.UUID) -> Invoice | None:
    """Mark an invoice as viewed and increment access count."""
    invoice = get_invoice(db, invoice_id)
    if invoice:
        invoice.viewed_at = datetime.now(timezone.utc)
        invoice.access_count += 1
        if invoice.status == InvoiceStatus.SENT.value:
            invoice.status = InvoiceStatus.VIEWED.value
        db.commit()
        db.refresh(invoice)
    return invoice


def mark_invoice_paid(db: Session, invoice_id: uuid.UUID) -> Invoice | None:
    """Mark an invoice as paid."""
    invoice = get_invoice(db, invoice_id)
    if invoice:
        invoice.status = InvoiceStatus.PAID.value
        invoice.paid_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(invoice)
    return invoice


def update_invoice_delivery(
    db: Session,
    invoice_id: uuid.UUID,
    delivered_via: str,
) -> Invoice | None:
    """Update invoice delivery status."""
    invoice = get_invoice(db, invoice_id)
    if invoice:
        invoice.delivered_via = delivered_via
        invoice.delivered_at = datetime.now(timezone.utc)
        invoice.status = InvoiceStatus.SENT.value
        invoice.issued_at = invoice.issued_at or datetime.now(timezone.utc)
        db.commit()
        db.refresh(invoice)
    return invoice


def refresh_secure_token(db: Session, invoice_id: uuid.UUID) -> Invoice | None:
    """Generate a new secure token for an invoice."""
    from app.models.invoice import generate_secure_token
    invoice = get_invoice(db, invoice_id)
    if invoice:
        invoice.secure_token = generate_secure_token()
        invoice.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
        db.commit()
        db.refresh(invoice)
    return invoice


def invalidate_token(db: Session, invoice_id: uuid.UUID) -> Invoice | None:
    """Invalidate an invoice's secure token."""
    invoice = get_invoice(db, invoice_id)
    if invoice:
        invoice.token_expires_at = datetime.now(timezone.utc)  # expired
        db.commit()
        db.refresh(invoice)
    return invoice
