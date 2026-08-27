"""PDF Invoice Generation Service.

Generates professional PDF invoices using ReportLab.
- Clean, readable layout
- Company branding header
- Customer and payment details
- Secure access link with QR-style token display
- Indian Rupee formatting

All data comes from the database — no AI involvement.
"""

import io
import logging
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    HRFlowable,
)

logger = logging.getLogger(__name__)

# Colors
PRIMARY_COLOR = colors.HexColor("#1a73e8")
HEADER_BG = colors.HexColor("#f8f9fa")
BORDER_COLOR = colors.HexColor("#dee2e6")
TEXT_COLOR = colors.HexColor("#212529")
MUTED_COLOR = colors.HexColor("#6c757d")


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


def generate_invoice_pdf(
    invoice_number: str,
    amount_paise: int,
    customer_name: str | None = None,
    customer_email: str | None = None,
    description: str | None = None,
    issued_at: str | None = None,
    paid_at: str | None = None,
    status: str = "PENDING",
    secure_token: str | None = None,
    payment_link: str | None = None,
    currency: str = "INR",
) -> bytes:
    """Generate a PDF invoice.

    Args:
        invoice_number: Unique invoice number
        amount_paise: Amount in paise
        customer_name: Customer's name
        customer_email: Customer's email
        description: Invoice description
        issued_at: Issue date string
        paid_at: Payment date string
        status: Invoice status
        secure_token: Secure access token for the invoice
        payment_link: Link to pay the invoice
        currency: Currency code

    Returns:
        PDF file as bytes
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=25 * mm,
        leftMargin=25 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        fontSize=24,
        textColor=PRIMARY_COLOR,
        spaceAfter=2 * mm,
    )
    subtitle_style = ParagraphStyle(
        "InvoiceSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=MUTED_COLOR,
        spaceAfter=4 * mm,
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=TEXT_COLOR,
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
    )
    body_style = ParagraphStyle(
        "BodyText",
        parent=styles["Normal"],
        fontSize=10,
        textColor=TEXT_COLOR,
        leading=14,
    )
    amount_style = ParagraphStyle(
        "AmountDisplay",
        parent=styles["Normal"],
        fontSize=20,
        textColor=PRIMARY_COLOR,
        spaceBefore=2 * mm,
        spaceAfter=2 * mm,
    )
    footer_style = ParagraphStyle(
        "FooterText",
        parent=styles["Normal"],
        fontSize=8,
        textColor=MUTED_COLOR,
        alignment=1,  # center
    )

    elements = []

    # --- Header ---
    elements.append(Paragraph("INVOICE", title_style))
    elements.append(Paragraph(f"Invoice #{invoice_number}", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=BORDER_COLOR))
    elements.append(Spacer(1, 4 * mm))

    # --- Status Badge ---
    status_display = status.replace("_", " ").title()
    status_color = {
        "PENDING": colors.HexColor("#ffc107"),
        "SENT": colors.HexColor("#17a2b8"),
        "VIEWED": colors.HexColor("#17a2b8"),
        "PAID": colors.HexColor("#28a745"),
        "CANCELLED": colors.HexColor("#dc3545"),
    }.get(status, colors.HexColor("#6c757d"))

    status_table = Table(
        [[Paragraph(f"<b>{status_display}</b>", ParagraphStyle(
            "StatusText", parent=styles["Normal"], fontSize=10,
            textColor=colors.white, alignment=1,
        ))]],
        colWidths=[80],
        rowHeights=[25],
    )
    status_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), status_color),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    elements.append(status_table)
    elements.append(Spacer(1, 6 * mm))

    # --- Two-column layout: Bill To | Invoice Details ---
    left_data = []
    if customer_name:
        left_data.append(Paragraph(f"<b>{customer_name}</b>", body_style))
    if customer_email:
        left_data.append(Paragraph(customer_email, body_style))

    right_data = []
    if issued_at:
        right_data.append(Paragraph(f"<b>Issue Date:</b> {issued_at}", body_style))
    if paid_at:
        right_data.append(Paragraph(f"<b>Paid Date:</b> {paid_at}", body_style))
    right_data.append(Paragraph(f"<b>Currency:</b> {currency}", body_style))

    info_table = Table(
        [[left_data, right_data]],
        colWidths=[250, 250],
    )
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 8 * mm))

    # --- Line Items Table ---
    elements.append(Paragraph("PAYMENT DETAILS", heading_style))

    formatted_amount = format_amount(amount_paise)
    desc_text = description or "Payment recovery"

    line_data = [
        [Paragraph("<b>Description</b>", body_style),
         Paragraph("<b>Amount</b>", body_style)],
        [Paragraph(desc_text, body_style),
         Paragraph(formatted_amount, body_style)],
    ]

    line_table = Table(line_data, colWidths=[350, 150])
    line_table.setStyle(TableStyle([
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_COLOR),
        # Borders
        ("LINEBELOW", (0, 0), (-1, 0), 1, BORDER_COLOR),
        ("LINEBELOW", (0, 1), (-1, 1), 1, BORDER_COLOR),
        # Padding
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        # Alignment
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 6 * mm))

    # --- Total Amount ---
    total_data = [
        [Paragraph("<b>Total Amount</b>", ParagraphStyle(
            "TotalLabel", parent=styles["Normal"], fontSize=14, textColor=TEXT_COLOR,
        )),
         Paragraph(f"<b>{formatted_amount}</b>", ParagraphStyle(
            "TotalValue", parent=styles["Normal"], fontSize=14,
            textColor=PRIMARY_COLOR, alignment=2,
        ))],
    ]
    total_table = Table(total_data, colWidths=[350, 150])
    total_table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.5, PRIMARY_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 10 * mm))

    # --- Payment Link ---
    if payment_link:
        elements.append(HRFlowable(width="100%", thickness=1, color=BORDER_COLOR))
        elements.append(Spacer(1, 4 * mm))
        elements.append(Paragraph("HOW TO PAY", heading_style))
        elements.append(Paragraph(
            f'Click the link below to complete your payment:<br/>'
            f'<link href="{payment_link}" color="#1a73e8">{payment_link}</link>',
            body_style,
        ))
        elements.append(Spacer(1, 4 * mm))

    # --- Secure Access Token ---
    if secure_token:
        elements.append(Paragraph(
            f"<b>Invoice ID:</b> {secure_token[:16]}...",
            ParagraphStyle("TokenText", parent=body_style, fontSize=8, textColor=MUTED_COLOR),
        ))
        elements.append(Spacer(1, 2 * mm))

    # --- Footer ---
    elements.append(Spacer(1, 10 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_COLOR))
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(
        "This invoice was generated by Fail2Pay. "
        "If you have questions, reply to the email or message you received.",
        footer_style,
    ))
    elements.append(Paragraph(
        f"Generated on {datetime.now(timezone.utc).strftime('%d %B %Y, %H:%M UTC')}",
        footer_style,
    ))

    # Build PDF
    doc.build(elements)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    logger.info("PDF generated: invoice=%s, size=%d bytes", invoice_number, len(pdf_bytes))

    return pdf_bytes


def generate_invoice_pdf_from_db(invoice) -> bytes:
    """Generate a PDF from an Invoice model object.

    Args:
        invoice: Invoice SQLAlchemy model instance

    Returns:
        PDF file as bytes
    """
    from app.config import get_settings

    payment_link = None
    if invoice.recovery_case_id:
        settings = get_settings()
        payment_link = f"{settings.payment_link_base_url}/pay/{invoice.recovery_case_id}"

    return generate_invoice_pdf(
        invoice_number=invoice.invoice_number,
        amount_paise=invoice.amount,
        customer_name=invoice.customer_name,
        customer_email=invoice.customer_email,
        description=invoice.description,
        issued_at=invoice.issued_at.strftime("%d %b %Y") if invoice.issued_at else None,
        paid_at=invoice.paid_at.strftime("%d %b %Y") if invoice.paid_at else None,
        status=invoice.status,
        secure_token=invoice.secure_token,
        payment_link=payment_link,
        currency=invoice.currency,
    )
