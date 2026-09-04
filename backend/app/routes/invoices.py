"""Invoice Routes.

Provides:
- Secure invoice access via token (GET /api/invoices/access/{token})
- Invoice PDF download via token (GET /api/invoices/download/{token})
- Invoice PDF download by ID (GET /api/invoices/{id}/download)
- Invoice list for a case (GET /api/invoices/case/{case_id})
- Invoice creation (POST /api/invoices)
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.crud.invoice import get_invoice as get_invoice_by_id, get_invoice_by_token
from app.services.invoice import (
    access_invoice_by_token,
    create_recovery_invoice,
    get_case_invoices,
    get_invoice_for_frontend,
)
from app.services.invoice_pdf import generate_invoice_pdf_from_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("/access/{token}")
def access_invoice(token: str, db: Session = Depends(get_db)):
    """Access an invoice using a secure token.

    This is the public endpoint that the secure URL points to.
    Validates the token and returns invoice data.
    """
    result = access_invoice_by_token(db, token)

    if result["status"] == "error":
        reason = result["reason"]
        if reason == "invalid_token":
            raise HTTPException(status_code=404, detail="Invoice not found")
        elif reason == "token_expired":
            raise HTTPException(status_code=410, detail="Invoice link has expired")
        else:
            raise HTTPException(status_code=500, detail=reason)

    return result["invoice"]


@router.get("/{invoice_id}")
def get_invoice_details(invoice_id: UUID, db: Session = Depends(get_db)):
    """Get invoice details by ID (requires authentication in production)."""
    invoice_data = get_invoice_for_frontend(db, invoice_id)

    if not invoice_data:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return invoice_data


@router.get("/case/{case_id}")
def list_case_invoices(case_id: UUID, db: Session = Depends(get_db)):
    """List all invoices for a recovery case."""
    invoices = get_case_invoices(db, case_id)
    return {"invoices": invoices, "count": len(invoices)}


@router.get("/download/{token}")
def download_invoice_by_token(token: str, db: Session = Depends(get_db)):
    """Download invoice PDF using secure token.

    This is the public endpoint for downloading invoices.
    Validates the token and returns a PDF file.
    """
    invoice = get_invoice_by_token(db, token)

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Check token expiry
    from datetime import datetime, timezone
    if invoice.token_expires_at:
        now = datetime.now(timezone.utc)
        expires = invoice.token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            raise HTTPException(status_code=410, detail="Invoice link has expired")

    # Generate PDF
    pdf_bytes = generate_invoice_pdf_from_db(invoice)

    # Track download
    from app.crud.invoice import mark_invoice_viewed
    mark_invoice_viewed(db, invoice.id)

    filename = f"invoice_{invoice.invoice_number}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/{invoice_id}/download")
def download_invoice_by_id(invoice_id: UUID, db: Session = Depends(get_db)):
    """Download invoice PDF by invoice ID (requires authentication in production)."""
    invoice = get_invoice_by_id(db, invoice_id)

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Generate PDF
    pdf_bytes = generate_invoice_pdf_from_db(invoice)

    filename = f"invoice_{invoice.invoice_number}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/case/{case_id}")
def create_invoice_for_case(case_id: UUID, db: Session = Depends(get_db)):
    """Create a new invoice for a recovery case."""
    result = create_recovery_invoice(db, case_id)

    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["reason"])

    return result
