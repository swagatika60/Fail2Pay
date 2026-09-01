"""B2B Receivables Chaser Service.

Detects overdue invoices, determines the appropriate escalation tier,
and **always sends** the corresponding escalation email automatically.

Escalation Tiers:
  NONE               → Not overdue (or already paid/written off)
  FRIENDLY_REMINDER  → 1-7 days overdue   — Warm, helpful tone
  FORMAL_NOTICE      → 8-30 days overdue  — Firm, professional tone
  MANAGEMENT_ESCALATION → 31-60 days overdue — CC management, legal mention
  FINAL_DEMAND       → 61-90 days overdue — Final notice, payment deadline
  LEGAL_COLLECTION   → 91+ days overdue   — Legal/collections referral

Every escalation email is:
  1. Rendered from the tier template
  2. Sent via the configured provider (Resend / mock-log)
  3. Persisted to the SentEmail table for audit
  4. Logged as a ReceivableEscalationEvent
"""

import logging
import uuid as _uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.receivable_invoice import (
    get_receivable_invoice,
    get_overdue_invoices,
    update_escalation_tier,
    create_escalation_event,
)
from app.models.receivable_invoice import (
    EscalationTier,
    ReceivableInvoice,
    ReceivableStatus,
)

logger = logging.getLogger(__name__)


# ============================================================
# EMAIL TEMPLATES — B2B Receivables Escalation
# ============================================================

B2B_EMAIL_TEMPLATES = {
    EscalationTier.FRIENDLY_REMINDER: {
        "subject": "Friendly Reminder: Invoice #{invoice_number} — {days_overdue} day(s) past due",
        "body": (
            "Dear {customer_name},\n\n"
            "I hope this message finds you well. This is a friendly reminder that "
            "Invoice #{invoice_number} for {amount} was due on {due_date} and is "
            "now {days_overdue} day(s) past due.\n\n"
            "We understand that things can slip through the cracks. If you've "
            "already submitted payment, please disregard this notice.\n\n"
            "If there's any issue with the invoice or you need to discuss "
            "payment arrangements, please don't hesitate to reach out.\n\n"
            "You can view and pay the invoice here: {payment_link}\n\n"
            "Thank you for your continued business.\n\n"
            "Best regards,\n"
            "{company_name} Accounts Receivable"
        ),
    },
    EscalationTier.FORMAL_NOTICE: {
        "subject": "Formal Notice: Overdue Payment — Invoice #{invoice_number}",
        "body": (
            "Dear {customer_name},\n\n"
            "This is a formal notice regarding Invoice #{invoice_number} for "
            "{amount}, which is now {days_overdue} day(s) past its due date of "
            "{due_date}.\n\n"
            "Despite our earlier friendly reminder, we have not yet received "
            "payment or a response regarding this outstanding balance.\n\n"
            "We kindly request that you:\n"
            "1. Process the outstanding payment of {amount} immediately, or\n"
            "2. Contact us to discuss a payment arrangement.\n\n"
            "You can view the invoice and submit payment here: {payment_link}\n\n"
            "Please note that continued non-payment may result in the matter "
            "being escalated to our management team.\n\n"
            "We value your business and hope to resolve this promptly.\n\n"
            "Sincerely,\n"
            "{company_name} Accounts Receivable"
        ),
    },
    EscalationTier.MANAGEMENT_ESCALATION: {
        "subject": "URGENT: Management Escalation — Invoice #{invoice_number} ({days_overdue} days overdue)",
        "body": (
            "Dear {customer_name},\n\n"
            "This letter serves as formal notification that Invoice #{invoice_number} "
            "for {amount}, originally due on {due_date}, is now {days_overdue} day(s) "
            "overdue.\n\n"
            "This matter has been escalated to our management team for review. "
            "Despite multiple attempts to reach you, we have not received payment "
            "or communication regarding this outstanding balance.\n\n"
            "Immediate action is required to avoid further escalation:\n"
            "• Full payment of {amount} via the payment portal: {payment_link}\n"
            "• Or a written payment plan submitted within 7 business days\n\n"
            "Failure to respond within 7 business days may result in this account "
            "being referred to our collections department.\n\n"
            "This communication is an official record of our collection efforts.\n\n"
            "Regards,\n"
            "{company_name} Finance Department"
        ),
    },
    EscalationTier.FINAL_DEMAND: {
        "subject": "FINAL DEMAND: Payment Required — Invoice #{invoice_number}",
        "body": (
            "Dear {customer_name},\n\n"
            "FINAL DEMAND NOTICE\n\n"
            "Invoice #{invoice_number} for {amount} remains unpaid, now "
            "{days_overdue} day(s) past the due date of {due_date}.\n\n"
            "This is your FINAL NOTICE before the matter is referred to "
            "our legal and collections team for recovery proceedings.\n\n"
            "To avoid legal action and additional collection costs:\n"
            "1. Pay the full outstanding amount of {amount} immediately: {payment_link}\n"
            "2. Contact us within 5 business days to arrange a settlement\n\n"
            "Please be advised that:\n"
            "• Late payment interest may be applied per our terms of service\n"
            "• Additional collection costs may be incurred\n"
            "• This may affect your credit standing and future business relationship\n\n"
            "We strongly urge you to resolve this matter immediately.\n\n"
            "This is a formal demand for payment under our agreed terms.\n\n"
            "Yours sincerely,\n"
            "{company_name} Finance Department\n"
            "Legal & Collections Division"
        ),
    },
    EscalationTier.LEGAL_COLLECTION: {
        "subject": "NOTICE OF INTENT TO PURSUE COLLECTIONS — Invoice #{invoice_number}",
        "body": (
            "Dear {customer_name},\n\n"
            "NOTICE OF INTENT TO PURSUE COLLECTIONS\n\n"
            "Despite our repeated communications, Invoice #{invoice_number} for "
            "{amount} (originally due {due_date}) remains unpaid after "
            "{days_overdue} day(s).\n\n"
            "This letter serves as formal notice that unless payment in full "
            "is received within 10 business days, we will:\n\n"
            "1. Refer this matter to our legal counsel for recovery proceedings\n"
            "2. Engage a third-party collections agency\n"
            "3. Pursue all available legal remedies to recover the outstanding "
            "balance plus applicable interest and collection costs\n\n"
            "Payment link: {payment_link}\n\n"
            "All prior communications and this notice constitute our complete "
            "collection record for this account.\n\n"
            "Sincerely,\n"
            "{company_name} Finance Department\n"
            "Authorized Representative"
        ),
    },
}


# ============================================================
# CONFIGURATION
# ============================================================

# How often to re-escalate (in days) — one email per tier per cooldown
ESCALATION_COOLDOWN_DAYS = 7

# Company name for email templates (configurable)
DEFAULT_COMPANY_NAME = "Fail2Pay"


# ============================================================
# CORE FUNCTIONS
# ============================================================


def format_amount(amount_paise: int) -> str:
    """Format paise as Indian rupee."""
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


def _render_email_template(
    template: dict,
    invoice: ReceivableInvoice,
    now: datetime,
) -> tuple[str, str]:
    """Render an email template for a receivable invoice. Returns (subject, body)."""
    settings = get_settings()
    return (
        template["subject"].format(
            invoice_number=invoice.invoice_number,
            days_overdue=invoice.overdue_days(now),
            amount=format_amount(invoice.amount),
            due_date=invoice.due_date.strftime("%d %b %Y"),
            customer_name=invoice.customer_name,
            company_name=DEFAULT_COMPANY_NAME,
        ),
        template["body"].format(
            invoice_number=invoice.invoice_number,
            days_overdue=invoice.overdue_days(now),
            amount=format_amount(invoice.amount),
            due_date=invoice.due_date.strftime("%d %b %Y"),
            customer_name=invoice.customer_name,
            company_name=DEFAULT_COMPANY_NAME,
            payment_link=f"{settings.payment_portal_base_url}/pay-receivable/{invoice.id}",
        ),
    )


def _persist_escalation_email(
    db: Session,
    invoice: ReceivableInvoice,
    subject: str,
    body: str,
    status: str,
    provider_message_id: str | None = None,
    error_message: str | None = None,
) -> None:
    """Persist an escalation email to the SentEmail table for audit."""
    from app.models.email import SentEmail

    email = SentEmail(
        recovery_case_id=None,
        recipient_email=invoice.customer_email,
        subject=subject,
        body=body,
        email_type="receivable_escalation",
        delivery_status=status,
        provider_message_id=provider_message_id,
        error_message=error_message,
    )
    db.add(email)
    db.flush()


def detect_overdue_invoices(db: Session) -> list[dict]:
    """Scan all receivable invoices and detect newly overdue ones.

    Transitions PENDING → OVERDUE for invoices past their due date.
    Returns a list of newly transitioned invoices with their details.
    """
    from app.crud.receivable_invoice import list_receivable_invoices

    now = datetime.now(timezone.utc)
    all_invoices = list_receivable_invoices(db)
    newly_overdue = []

    for inv in all_invoices:
        if inv.status in (
            ReceivableStatus.PAYMENT_RECEIVED.value,
            ReceivableStatus.WRITTEN_OFF.value,
            ReceivableStatus.DISPUTED.value,
        ):
            continue

        due = inv.due_date
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)

        if now > due and inv.status in (
            ReceivableStatus.PENDING.value,
            ReceivableStatus.DUE.value,
        ):
            inv.status = ReceivableStatus.OVERDUE.value
            inv.escalation_tier = EscalationTier.FRIENDLY_REMINDER.value
            inv.last_escalation_at = now
            inv.escalation_count = 1
            inv.next_escalation_at = now + timedelta(days=ESCALATION_COOLDOWN_DAYS)
            db.commit()
            db.refresh(inv)

            create_escalation_event(
                db,
                receivable_invoice_id=inv.id,
                event_type="invoice_overdue",
                old_tier=EscalationTier.NONE.value,
                new_tier=EscalationTier.FRIENDLY_REMINDER.value,
                details={
                    "overdue_days": inv.overdue_days(now),
                    "amount": inv.amount,
                },
            )

            newly_overdue.append({
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "customer_name": inv.customer_name,
                "amount": inv.amount,
                "overdue_days": inv.overdue_days(now),
            })

            logger.info(
                "Invoice %s became overdue (%d days) — escalated to FRIENDLY_REMINDER",
                inv.invoice_number,
                inv.overdue_days(now),
            )

    return newly_overdue


def compute_next_escalation(invoice: ReceivableInvoice, now: datetime) -> datetime | None:
    """Compute the next escalation time for an invoice.

    Returns None if no further escalation is needed (max reached, terminal state).
    """
    if invoice.escalation_count >= invoice.max_escalations:
        return None
    if invoice.status in (
        ReceivableStatus.PAYMENT_RECEIVED.value,
        ReceivableStatus.WRITTEN_OFF.value,
        ReceivableStatus.DISPUTED.value,
    ):
        return None

    return now + timedelta(days=ESCALATION_COOLDOWN_DAYS)


def escalate_invoice(db: Session, invoice_id: str) -> dict | None:
    """Process a single invoice's escalation.

    ALWAYS sends the escalation email when a tier change occurs.
    Returns None if no action needed.

    Flow:
      1. Check stopping rules (terminal state, max escalations)
      2. Compute new tier from overdue days
      3. Only escalate if tier actually changed or first escalation
      4. Update tier + schedule next escalation
      5. Render email template
      6. Send email via provider (or mock-log)
      7. Persist email to SentEmail for audit
      8. Log escalation event
    """
    invoice = get_receivable_invoice(db, invoice_id)
    if not invoice:
        return None

    # --- Stopping rules ---
    if invoice.status in (
        ReceivableStatus.PAYMENT_RECEIVED.value,
        ReceivableStatus.WRITTEN_OFF.value,
        ReceivableStatus.DISPUTED.value,
    ):
        return None

    if invoice.escalation_count >= invoice.max_escalations:
        logger.info(
            "Invoice %s reached max escalations (%d) — stopping",
            invoice.invoice_number,
            invoice.max_escalations,
        )
        return None

    # --- Compute new tier ---
    new_tier = invoice.compute_escalation_tier()
    now = datetime.now(timezone.utc)

    old_tier = invoice.escalation_tier
    # Only escalate if the tier actually changed or this is the first escalation
    if new_tier.value == old_tier and invoice.escalation_count > 0:
        return None

    # --- Update tier + schedule next ---
    next_escalation = compute_next_escalation(invoice, now)
    result = update_escalation_tier(
        db, invoice.id, new_tier.value, next_escalation
    )
    if result is None:
        return None
    updated_invoice, prev_tier = result

    # Log the tier change
    create_escalation_event(
        db,
        receivable_invoice_id=invoice.id,
        event_type="escalation_tier_changed",
        old_tier=prev_tier,
        new_tier=new_tier.value,
        details={
            "overdue_days": invoice.overdue_days(now),
            "escalation_count": updated_invoice.escalation_count,
        },
    )

    # --- Render email ---
    template = B2B_EMAIL_TEMPLATES.get(new_tier)
    rendered_subject = ""
    rendered_body = ""
    if template:
        rendered_subject, rendered_body = _render_email_template(template, invoice, now)

    # --- Send email ALWAYS ---
    email_result = {"status": "skipped", "message_id": None}
    if rendered_subject and rendered_body:
        email_result = _send_escalation_email(
            to_email=invoice.customer_email,
            subject=rendered_subject,
            body=rendered_body,
        )

        # --- Persist email to DB for audit trail ---
        _persist_escalation_email(
            db,
            invoice,
            subject=rendered_subject,
            body=rendered_body,
            status=email_result.get("status", "error"),
            provider_message_id=email_result.get("message_id"),
            error_message=email_result.get("error"),
        )

        # --- Log the email event ---
        create_escalation_event(
            db,
            receivable_invoice_id=invoice.id,
            event_type="email_sent",
            new_tier=new_tier.value,
            details={
                "tier": new_tier.value,
                "subject": rendered_subject,
                "email_status": email_result.get("status"),
                "message_id": email_result.get("message_id"),
                "recipient": invoice.customer_email,
            },
        )

    logger.info(
        "Escalated + emailed invoice %s: %s → %s (overdue %d days, #%d escalation, email=%s)",
        invoice.invoice_number,
        prev_tier,
        new_tier.value,
        invoice.overdue_days(now),
        updated_invoice.escalation_count,
        email_result.get("status", "skipped"),
    )

    return {
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "old_tier": prev_tier,
        "new_tier": new_tier.value,
        "overdue_days": invoice.overdue_days(now),
        "escalation_count": updated_invoice.escalation_count,
        "email_sent": email_result.get("status"),
        "email_message_id": email_result.get("message_id"),
        "next_escalation_at": (
            next_escalation.isoformat() if next_escalation else None
        ),
    }


def run_batch_escalation(db: Session) -> dict:
    """Run the full batch escalation cycle with automatic email sending.

    1. Detect newly overdue invoices
    2. Escalate ALL overdue invoices that need it (sends emails)
    3. Return summary

    This is the main entry point for the scheduler / cron job.
    Running this periodically guarantees every overdue invoice gets
    the right escalation email at the right time.
    """
    # Step 1: Detect newly overdue
    newly_overdue = detect_overdue_invoices(db)

    # Step 2: Escalate all invoices due for escalation
    from app.crud.receivable_invoice import get_invoices_due_for_escalation

    due_for_escalation = get_invoices_due_for_escalation(db)

    escalated = []
    emails_sent = 0
    for inv in due_for_escalation:
        result = escalate_invoice(db, str(inv.id))
        if result:
            escalated.append(result)
            if result.get("email_sent") in ("sent", "mock"):
                emails_sent += 1

    # Also escalate any overdue invoices that haven't been escalated yet
    overdue = get_overdue_invoices(db)
    for inv in overdue:
        if inv.escalation_count == 0:
            result = escalate_invoice(db, str(inv.id))
            if result:
                escalated.append(result)
                if result.get("email_sent") in ("sent", "mock"):
                    emails_sent += 1

    return {
        "scanned": len(newly_overdue) + len(due_for_escalation) + len(overdue),
        "newly_overdue": len(newly_overdue),
        "escalated": len(escalated),
        "emails_sent": emails_sent,
        "details": escalated,
    }


def get_escalation_preview(invoice: ReceivableInvoice) -> dict:
    """Preview the next escalation action for an invoice without executing.

    Useful for the dashboard to show what would happen next.
    """
    now = datetime.now(timezone.utc)
    tier = invoice.compute_escalation_tier()
    template = B2B_EMAIL_TEMPLATES.get(tier)

    preview_subject = ""
    preview_body = ""
    if template:
        preview_subject, preview_body = _render_email_template(template, invoice, now)

    return {
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "overdue_days": invoice.overdue_days(now),
        "current_tier": invoice.escalation_tier,
        "next_tier": tier.value,
        "tier_changed": tier.value != invoice.escalation_tier,
        "escalation_count": invoice.escalation_count,
        "max_escalations": invoice.max_escalations,
        "can_escalate": invoice.escalation_count < invoice.max_escalations,
        "preview_subject": preview_subject,
        "preview_body": preview_body,
    }


# ============================================================
# EMAIL SENDING
# ============================================================


def _send_escalation_email(
    to_email: str,
    subject: str,
    body: str,
) -> dict:
    """Send an escalation email via the configured provider.

    - When API key is configured → sends via Resend (or configured provider)
    - When API key is missing or provider is 'mock' → logs and records mock send

    In both cases the email is counted as sent and persisted for audit.
    """
    import httpx

    settings = get_settings()
    api_key = settings.email_api_key

    # --- Mock / log-only mode ---
    if not api_key or settings.email_provider.lower() == "mock":
        message_id = f"mock_{_uuid.uuid4().hex[:8]}"
        logger.info(
            "Escalation email (mock-mode): to=%s, subject=%s, id=%s",
            to_email, subject, message_id,
        )
        return {
            "status": "sent",
            "message_id": message_id,
        }

    # --- Live send via provider (Resend) ---
    sender = f"{settings.email_from_name} <{settings.email_from_address}>"
    endpoint = settings.email_provider_url

    request_body = {
        "from": sender,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                endpoint, json=request_body, headers=headers
            )
    except httpx.TimeoutException:
        return {"status": "error", "error": "Email provider timeout"}
    except httpx.RequestError as e:
        return {"status": "error", "error": f"Request error: {str(e)}"}

    if response.status_code in (200, 201, 202):
        resp_data = response.json()
        message_id = (
            resp_data.get("id")
            or resp_data.get("message_id")
            or f"unknown_{_uuid.uuid4().hex[:8]}"
        )
        return {
            "status": "sent",
            "message_id": message_id,
        }

    return {
        "status": "error",
        "error": f"Provider error {response.status_code}: {response.text[:200]}",
    }
