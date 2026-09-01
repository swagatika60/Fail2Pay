"""Email Service for Recovery Workflows.

Handles:
1. Email template rendering (deterministic, no AI)
2. Opt-out / communication preference checks
3. Email sending via provider (SMTP or API)
4. Delivery tracking and logging

AI may personalize wording in the future, but templates and
sending logic remain deterministic and safe.

Email types:
- failed_payment: initial notification after payment failure
- payment_retry: reminder to retry payment
- invoice: send invoice/receipt
- payment_plan_confirmation: confirm payment plan setup
- promise_to_pay_reminder: reminder for promised payment
- payment_success: confirmation of successful payment
"""

import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.email import create_sent_email, update_delivery_status
from app.crud.recovery_case import get_recovery_case
from app.crud.customer import get_customer
from app.models.email import EmailDeliveryStatus, EmailType
from app.schemas.email import SentEmailCreate

logger = logging.getLogger(__name__)


# --- Email Templates ---

EMAIL_TEMPLATES = {
    EmailType.FAILED_PAYMENT.value: {
        "subject": "Payment Update Needed — {amount}",
        "body": (
            "Hi {customer_name},\n\n"
            "Your payment of {amount} could not be completed. "
            "This might be due to insufficient funds, an expired card, or a bank issue.\n\n"
            "You can retry your payment here: {payment_link}\n\n"
            "If you've already paid, please disregard this email.\n\n"
            "Need help? Reply to this email and we'll assist you.\n\n"
            "Best regards,\nFail2Pay Team"
        ),
    },
    EmailType.PAYMENT_RETRY.value: {
        "subject": "Reminder: Complete Your Payment of {amount}",
        "body": (
            "Hi {customer_name},\n\n"
            "Just a friendly reminder — your payment of {amount} is still pending.\n\n"
            "You can complete your payment here: {payment_link}\n\n"
            "If you're facing any issues, reply to this email and we'll help you out.\n\n"
            "Best regards,\nFail2Pay Team"
        ),
    },
    EmailType.INVOICE.value: {
        "subject": "Your Invoice for {amount}",
        "body": (
            "Hi {customer_name},\n\n"
            "Please find your invoice for the amount of {amount}.\n\n"
            "You can view and download your invoice here: {invoice_link}\n\n"
            "If you have any questions about this invoice, please reply to this email.\n\n"
            "Best regards,\nFail2Pay Team"
        ),
    },
    EmailType.PAYMENT_PLAN_CONFIRMATION.value: {
        "subject": "Payment Plan Confirmed — {amount}",
        "body": (
            "Hi {customer_name},\n\n"
            "Your payment plan for {amount} has been confirmed.\n\n"
            "Here's a summary of your plan:\n"
            "{payment_plan_details}\n\n"
            "You'll receive reminders before each installment is due.\n\n"
            "If you have any questions, reply to this email.\n\n"
            "Best regards,\nFail2Pay Team"
        ),
    },
    EmailType.PROMISE_TO_PAY_REMINDER.value: {
        "subject": "Gentle Reminder: Your Promised Payment of {amount}",
        "body": (
            "Hi {customer_name},\n\n"
            "This is a gentle reminder about your promised payment of {amount}.\n\n"
            "You can complete your payment here: {payment_link}\n\n"
            "If you need to reschedule, please reply to this email and we'll work with you.\n\n"
            "Best regards,\nFail2Pay Team"
        ),
    },
    EmailType.PAYMENT_SUCCESS.value: {
        "subject": "Payment Confirmed — {amount}",
        "body": (
            "Hi {customer_name},\n\n"
            "Great news! Your payment of {amount} has been successfully received.\n\n"
            "Thank you for completing your payment. You're all set!\n\n"
            "If you have any questions, reply to this email.\n\n"
            "Best regards,\nFail2Pay Team"
        ),
    },
}


# --- Opt-out Keywords ---

OPT_OUT_KEYWORDS = [
    "stop",
    "unsubscribe",
    "opt out",
    "optout",
    "do not email",
    "don't email",
    "remove me",
    "no more emails",
]


# --- Template Rendering ---


def format_amount(amount_paise: int) -> str:
    """Format amount in paise to human-readable Indian Rupee format."""
    rupees = amount_paise // 100
    s = str(rupees)
    if len(s) <= 3:
        return f"₹{s}"
    last_three = s[-3:]
    remaining = s[:-3]
    formatted = ""
    while len(remaining) > 2:
        formatted = "," + remaining[-2:] + formatted
        remaining = remaining[:-2]
    formatted = remaining + formatted + "," + last_three
    return f"₹{formatted}"


def render_email(
    email_type: str,
    customer_name: str | None,
    amount_paise: int,
    payment_link: str = "",
    invoice_link: str = "",
    payment_plan_details: str = "",
) -> dict:
    """Render an email template with customer-specific data.

    Returns:
        dict with 'subject' and 'body' keys
    """
    template = EMAIL_TEMPLATES.get(email_type)
    if not template:
        logger.warning("Email template not found: %s", email_type)
        return {"subject": "", "body": ""}

    formatted_amount = format_amount(amount_paise)
    name = customer_name or "Customer"

    subject = template["subject"].format(
        customer_name=name,
        amount=formatted_amount,
    )
    body = template["body"].format(
        customer_name=name,
        amount=formatted_amount,
        payment_link=payment_link,
        invoice_link=invoice_link,
        payment_plan_details=payment_plan_details,
    )

    return {"subject": subject, "body": body}


# --- Opt-out Check ---


def is_opted_out(db: Session, case_id: uuid.UUID) -> bool:
    """Check if a customer has opted out of email communication.

    Checks:
    1. Case status is STOPPED
    2. Last audit event is a stop request
    3. Conversation has a stop keyword in recent messages
    """
    from app.models.recovery_case import RecoveryStatus
    from app.models.audit_event import AuditEvent
    from app.models.conversation_message import ConversationMessage
    from app.models.conversation import Conversation
    from sqlalchemy import select

    case = get_recovery_case(db, case_id)
    if not case:
        return True  # If case doesn't exist, don't send

    # Check terminal state
    if case.status == RecoveryStatus.STOPPED:
        return True

    # Check last audit event for stop request
    last_audit = db.execute(
        select(AuditEvent)
        .where(AuditEvent.recovery_case_id == case_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if last_audit and "stop" in (last_audit.action or "").lower():
        return True

    # Check recent inbound messages for opt-out keywords
    recent_inbound = db.execute(
        select(ConversationMessage)
        .join(Conversation)
        .where(
            Conversation.recovery_case_id == case_id,
            ConversationMessage.direction == "inbound",
        )
        .order_by(ConversationMessage.created_at.desc())
        .limit(5)
    ).scalars().all()

    for msg in recent_inbound:
        content_lower = (msg.content or "").lower()
        if any(kw in content_lower for kw in OPT_OUT_KEYWORDS):
            return True

    return False


# --- Email Sending ---


def send_recovery_email(
    db: Session,
    case_id: uuid.UUID,
    email_type: str,
    payment_link: str = "",
    invoice_link: str = "",
    payment_plan_details: str = "",
    language: str = "en",
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
) -> dict:
    """Send a recovery email with policy and opt-out checks.

    This is the ONLY way to send recovery emails. It:
    1. Checks communication preferences (opt-out)
    2. Renders the email template
    3. Sends via the configured provider
    4. Logs the email in the database
    5. Returns the result

    Args:
        db: Database session
        case_id: Recovery case ID
        email_type: One of EmailType values
        payment_link: Link to payment page
        invoice_link: Link to invoice
        payment_plan_details: Payment plan summary text
        language: Language code

    Returns:
        dict with status, email_id, and any error details
    """
    # --- Step 1: Get case and customer ---
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    customer = get_customer(db, case.customer_id)
    if not customer:
        return {"status": "error", "reason": "customer_not_found"}

    if not customer.email:
        return {"status": "error", "reason": "no_email_address"}

    # --- Step 1.5: Hard Stop Check ---
    # A payment-success confirmation is deliberately exempt from the hard-stop
    # "payment_succeeded" rule: that rule exists to stop *outreach* (reminders /
    # retries) once a case is settled — it must not block the thank-you email that
    # confirms the very payment that settled the case. Genuine customer opt-out is
    # still enforced below in Step 2.
    if email_type != EmailType.PAYMENT_SUCCESS.value:
        from app.services.hard_stop import check_hard_stop
        hard_stop = check_hard_stop(db, case_id, action_type="email_send")
        if hard_stop.blocked:
            logger.info(
                "Email blocked by hard stop: case=%s, condition=%s",
                case_id, hard_stop.stop_condition,
            )
            return {
                "status": "blocked",
                "reason": hard_stop.reason,
                "stop_condition": hard_stop.stop_condition,
            }

    # --- Step 2: Check opt-out ---
    if is_opted_out(db, case_id):
        logger.info("Email blocked: customer opted out for case %s", case_id)
        return {"status": "blocked", "reason": "customer_opted_out"}

    # --- Step 3: Check for duplicate emails ---
    from app.crud.email import count_emails_by_case_and_type
    existing_count = count_emails_by_case_and_type(db, case_id, email_type)
    if existing_count > 0 and email_type != EmailType.PAYMENT_SUCCESS.value:
        logger.info(
            "Email skipped: %s already sent %d times for case %s",
            email_type, existing_count, case_id,
        )
        return {"status": "skipped", "reason": "already_sent", "count": existing_count}

    # --- Step 4: Render email ---
    rendered = render_email(
        email_type=email_type,
        customer_name=customer.name or "Customer",
        amount_paise=case.original_amount,
        payment_link=payment_link,
        invoice_link=invoice_link,
        payment_plan_details=payment_plan_details,
    )

    if not rendered["subject"] or not rendered["body"]:
        return {"status": "error", "reason": "template_not_found"}

    # --- Step 5: Create email record (pending) ---
    email_record = create_sent_email(
        db,
        data=SentEmailCreate(
            recovery_case_id=case_id,
            recipient_email=customer.email,
            subject=rendered["subject"],
            body=rendered["body"],
            email_type=email_type,
        ),
    )

    # --- Step 6: Send via provider ---
    send_result = _send_via_provider(
        to_email=customer.email,
        subject=rendered["subject"],
        body=rendered["body"],
        attachment_bytes=attachment_bytes,
        attachment_filename=attachment_filename,
    )

    # --- Step 7: Update record with result ---
    if send_result["status"] == "sent":
        update_delivery_status(
            db,
            email_record.id,
            status=EmailDeliveryStatus.SENT.value,
            provider_message_id=send_result.get("message_id"),
            provider_response=send_result.get("provider_response"),
        )
        logger.info(
            "Email sent: type=%s, to=%s, case=%s, message_id=%s",
            email_type, customer.email, case_id, send_result.get("message_id"),
        )
    else:
        update_delivery_status(
            db,
            email_record.id,
            status=EmailDeliveryStatus.FAILED.value,
            error_message=send_result.get("error"),
        )
        logger.error(
            "Email failed: type=%s, to=%s, case=%s, error=%s",
            email_type, customer.email, case_id, send_result.get("error"),
        )

    return {
        "status": send_result["status"],
        "email_id": str(email_record.id),
        "recipient": customer.email,
        "email_type": email_type,
        "message_id": send_result.get("message_id"),
    }


def _send_via_provider(
    to_email: str,
    subject: str,
    body: str,
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
) -> dict:
    """Send email via the configured provider.

    Supports:
    1. Resend (default) — REST API at ``EmailProviderUrl`` with a Bearer key
    2. Falls back to logging if no API key is configured

    Returns:
        dict with status, message_id, and any error details
    """
    settings = get_settings()
    api_key = settings.email_api_key

    if not api_key or settings.email_provider.lower() == "mock":
        logger.warning("Email API key not configured — logging email only")
        attachment_info = None
        if attachment_bytes and attachment_filename:
            attachment_info = {
                "filename": attachment_filename,
                "size_bytes": len(attachment_bytes),
            }
        return {
            "status": "sent",
            "message_id": f"mock_{uuid.uuid4().hex[:8]}",
            "provider_response": {
                "mock": True,
                "reason": "no_api_key" if not api_key else "provider_mock",
                "attachment": attachment_info,
            },
        }

    provider = settings.email_provider.lower()
    endpoint = settings.email_provider_url
    sender = f"{settings.email_from_name} <{settings.email_from_address}>"

    request_body = {
        "from": sender,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }

    # Add attachment if provided (base64 encoded)
    if attachment_bytes and attachment_filename:
        import base64
        request_body["attachments"] = [{
            "filename": attachment_filename,
            "content": base64.b64encode(attachment_bytes).decode("utf-8"),
        }]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=request_body, headers=headers)
    except httpx.TimeoutException:
        return {"status": "error", "error": "Email provider timeout"}
    except httpx.RequestError as e:
        return {"status": "error", "error": f"Email provider request error: {str(e)}"}

    if response.status_code in (200, 201, 202):
        resp_data = response.json()
        message_id = (
            resp_data.get("id")
            or resp_data.get("message_id")
            or resp_data.get("data", {}).get("id", "")
        )
        return {
            "status": "sent",
            "message_id": message_id or f"unknown_{uuid.uuid4().hex[:8]}",
            "provider_response": resp_data,
        }

    error_msg = response.text
    try:
        error_data = response.json()
        error_msg = (
            error_data.get("message")
            or error_data.get("error")
            or str(error_data.get("errors", response.text))
        )
    except Exception:
        pass

    return {
        "status": "error",
        "error": f"Provider error {response.status_code}: {error_msg}",
    }


def get_email_history(db: Session, case_id: uuid.UUID) -> list[dict]:
    """Get email history for a recovery case.

    Returns:
        List of email summaries
    """
    from app.crud.email import get_emails_by_case

    emails = get_emails_by_case(db, case_id)
    return [
        {
            "id": str(e.id),
            "email_type": e.email_type,
            "recipient": e.recipient_email,
            "subject": e.subject,
            "delivery_status": e.delivery_status,
            "provider_message_id": e.provider_message_id,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in emails
    ]
