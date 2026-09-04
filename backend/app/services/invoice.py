"""Invoice Service for Recovery Workflows.

Handles:
1. Invoice generation with secure tokens
2. Secure access URL creation (expiring)
3. Invoice delivery via WhatsApp and email
4. Access tracking and validation
5. Invoice data retrieval for frontend

Security:
- Every invoice access requires a valid, non-expired token
- Tokens are cryptographically secure (secrets.token_urlsafe)
- Tokens expire after 72 hours by default
- Access count is tracked
- Tokens can be manually invalidated
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.customer import get_customer
from app.crud.invoice import (
    create_invoice,
    get_invoice_by_token,
    get_invoices_by_case,
    mark_invoice_viewed,
    update_invoice_delivery,
)
from app.crud.recovery_case import get_recovery_case
from app.schemas.invoice import InvoiceCreate

logger = logging.getLogger(__name__)

# Token validity: 72 hours
TOKEN_EXPIRY_HOURS = 72


def format_amount(amount_paise: int) -> str:
    """Format amount in paise to Indian Rupee format."""
    rupees = amount_paise // 100
    s = str(rupees)
    if len(s) <= 3:
        return f"\u20b9{s}"
    last_three = s[-3:]
    remaining = s[:-3]
    formatted = ""
    while len(remaining) > 2:
        formatted = "," + remaining[-2:] + formatted
        remaining = remaining[:-2]
    formatted = remaining + formatted + "," + last_three
    return f"\u20b9{formatted}"


def generate_invoice_number(case_id: str) -> str:
    """Generate a unique invoice number.

    Format: F2P-{short_case_id}-{timestamp}-{random}
    """
    import secrets
    short_id = str(case_id)[:8].upper()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    random_suffix = secrets.token_hex(3).upper()
    return f"F2P-{short_id}-{timestamp}-{random_suffix}"


def create_recovery_invoice(
    db: Session,
    case_id: uuid.UUID,
    description: str | None = None,
) -> dict:
    """Create an invoice for a recovery case.

    Generates a unique invoice number and secure access token.

    Args:
        db: Database session
        case_id: Recovery case ID
        description: Optional invoice description

    Returns:
        dict with invoice details and secure URL
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    customer = get_customer(db, case.customer_id)
    if not customer:
        return {"status": "error", "reason": "customer_not_found"}

    # Generate unique invoice number
    invoice_number = generate_invoice_number(str(case.id))

    # Create invoice
    invoice = create_invoice(
        db,
        data=InvoiceCreate(
            recovery_case_id=case.id,
            customer_id=customer.id,
            invoice_number=invoice_number,
            amount=case.original_amount,
            currency="INR",
            description=description or f"Invoice for failed payment of {format_amount(case.original_amount)}",
            customer_name=customer.name,
            customer_email=customer.email,
        ),
    )

    # Set token expiry
    invoice.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
    invoice.issued_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(invoice)

    # Generate secure URL
    secure_url = generate_secure_url(invoice.secure_token)

    logger.info(
        "Invoice created: number=%s, case=%s, amount=%d",
        invoice_number, case_id, case.original_amount,
    )

    return {
        "status": "created",
        "invoice_id": str(invoice.id),
        "invoice_number": invoice_number,
        "amount": case.original_amount,
        "secure_token": invoice.secure_token,
        "secure_url": secure_url,
        "expires_at": invoice.token_expires_at.isoformat(),
    }


def generate_secure_url(token: str) -> str:
    """Generate a secure invoice access URL.

    Returns a URL that includes the secure token.
    The backend validates the token on access.
    """
    settings = get_settings()
    base_url = settings.payment_link_base_url
    return f"{base_url}/api/invoices/access/{token}"


def access_invoice_by_token(
    db: Session,
    token: str,
) -> dict:
    """Access an invoice using a secure token.

    Validates the token, checks expiry, and returns invoice data.

    Args:
        db: Database session
        token: Secure access token

    Returns:
        dict with invoice data or error
    """
    invoice = get_invoice_by_token(db, token)

    if not invoice:
        return {"status": "error", "reason": "invalid_token"}

    # Check token expiry
    if invoice.token_expires_at:
        now = datetime.now(timezone.utc)
        expires = invoice.token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            return {"status": "error", "reason": "token_expired"}

    # Mark as viewed
    mark_invoice_viewed(db, invoice.id)

    # Get payment link if case exists
    payment_link = None
    if invoice.recovery_case_id:
        settings = get_settings()
        payment_link = f"{settings.payment_link_base_url}/pay/{invoice.recovery_case_id}"

    return {
        "status": "success",
        "invoice": {
            "id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "amount": invoice.amount,
            "currency": invoice.currency,
            "description": invoice.description,
            "customer_name": invoice.customer_name,
            "status": invoice.status,
            "issued_at": invoice.issued_at.isoformat() if invoice.issued_at else None,
            "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
            "payment_link": payment_link,
        },
    }


def send_invoice_via_whatsapp(
    db: Session,
    case_id: uuid.UUID,
    invoice_id: uuid.UUID | None = None,
) -> dict:
    """Send an invoice link via WhatsApp.

    If no invoice_id provided, creates a new invoice first.

    Returns:
        dict with send status and invoice details
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    customer = get_customer(db, case.customer_id)
    if not customer or not customer.phone:
        return {"status": "error", "reason": "no_phone_number"}

    # Get or create invoice
    if invoice_id:
        from app.crud.invoice import get_invoice
        invoice = get_invoice(db, invoice_id)
        if not invoice:
            return {"status": "error", "reason": "invoice_not_found"}
    else:
        result = create_recovery_invoice(db, case_id)
        if result["status"] != "created":
            return result
        invoice_id = uuid.UUID(result["invoice_id"])
        from app.crud.invoice import get_invoice
        invoice = get_invoice(db, invoice_id)

    # Generate secure URL
    secure_url = generate_secure_url(invoice.secure_token)

    # Render WhatsApp message
    from app.services.multilingual import get_response_template
    template = get_response_template("invoice", "en")
    formatted_amount = format_amount(invoice.amount)

    message = template.format(
        customer_name=customer.name or "Customer",
        amount=formatted_amount,
        invoice_link=secure_url,
    )

    # Send via WhatsApp
    from app.services.whatsapp import send_text_message
    send_result = send_text_message(
        db=db,
        phone_number=customer.phone,
        message=message,
        recovery_case_id=case_id,
    )

    # Update invoice delivery status
    if send_result["status"] == "sent":
        update_invoice_delivery(db, invoice.id, "whatsapp")

    return {
        "status": send_result["status"],
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "secure_url": secure_url,
        "message_id": send_result.get("message_id"),
    }


def send_invoice_via_email(
    db: Session,
    case_id: uuid.UUID,
    invoice_id: uuid.UUID | None = None,
) -> dict:
    """Send an invoice via email.

    If no invoice_id provided, creates a new invoice first.

    Returns:
        dict with send status and invoice details
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    customer = get_customer(db, case.customer_id)
    if not customer or not customer.email:
        return {"status": "error", "reason": "no_email_address"}

    # Get or create invoice
    if invoice_id:
        from app.crud.invoice import get_invoice
        invoice = get_invoice(db, invoice_id)
        if not invoice:
            return {"status": "error", "reason": "invoice_not_found"}
    else:
        result = create_recovery_invoice(db, case_id)
        if result["status"] != "created":
            return result
        invoice_id = uuid.UUID(result["invoice_id"])
        from app.crud.invoice import get_invoice
        invoice = get_invoice(db, invoice_id)

    # Generate secure URL
    secure_url = generate_secure_url(invoice.secure_token)

    # Generate PDF attachment
    from app.services.invoice_pdf import generate_invoice_pdf_from_db
    pdf_bytes = generate_invoice_pdf_from_db(invoice)
    pdf_filename = f"invoice_{invoice.invoice_number}.pdf"

    # Send via email service with PDF attachment
    from app.services.email import send_recovery_email, EmailType
    email_result = send_recovery_email(
        db=db,
        case_id=case_id,
        email_type=EmailType.INVOICE.value,
        invoice_link=secure_url,
        attachment_bytes=pdf_bytes,
        attachment_filename=pdf_filename,
    )

    # Update invoice delivery status
    if email_result["status"] == "sent":
        update_invoice_delivery(db, invoice.id, "email")

    return {
        "status": email_result["status"],
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "secure_url": secure_url,
        "email_id": email_result.get("email_id"),
    }


def get_invoice_for_frontend(
    db: Session,
    invoice_id: uuid.UUID,
) -> dict | None:
    """Get invoice data formatted for frontend display.

    Returns:
        dict with invoice data or None
    """
    from app.crud.invoice import get_invoice

    invoice = get_invoice(db, invoice_id)
    if not invoice:
        return None

    return {
        "id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "description": invoice.description,
        "customer_name": invoice.customer_name,
        "customer_email": invoice.customer_email,
        "status": invoice.status,
        "issued_at": invoice.issued_at.isoformat() if invoice.issued_at else None,
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "viewed_at": invoice.viewed_at.isoformat() if invoice.viewed_at else None,
        "secure_token": invoice.secure_token,
        "token_expires_at": invoice.token_expires_at.isoformat() if invoice.token_expires_at else None,
        "access_count": invoice.access_count,
        "delivered_via": invoice.delivered_via,
        "delivered_at": invoice.delivered_at.isoformat() if invoice.delivered_at else None,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
    }


def get_case_invoices(
    db: Session,
    case_id: uuid.UUID,
) -> list[dict]:
    """Get all invoices for a recovery case (formatted for frontend)."""
    invoices = get_invoices_by_case(db, case_id)
    return [
        {
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "amount": inv.amount,
            "currency": inv.currency,
            "status": inv.status,
            "issued_at": inv.issued_at.isoformat() if inv.issued_at else None,
            "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
            "delivered_via": inv.delivered_via,
        }
        for inv in invoices
    ]
