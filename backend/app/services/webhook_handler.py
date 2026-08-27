"""Razorpay webhook processing service.

Handles webhook signature verification and event processing for:
- payment.failed: Creates RevenueEvent + RecoveryCase with AT_RISK status
- payment.captured: Updates RevenueEvent + marks RecoveryCase RECOVERED if fully paid

All processing is idempotent - duplicate webhooks are detected and skipped.
"""

import hashlib
import hmac
import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.audit_event import create_audit_event
from app.crud.customer import create_customer, get_customer_by_external_id
from app.crud.recovery_case import (
    get_recovery_case,
    get_recovery_cases_by_status,
)
from app.crud.revenue_event import create_revenue_event, get_revenue_events_by_customer
from app.crud.webhook_event import get_webhook_event_by_event_id, store_webhook_event
from app.models.recovery_case import RecoveryStatus
from app.schemas.audit_event import AuditEventCreate
from app.schemas.customer import CustomerCreate
from app.schemas.recovery_case import RecoveryCaseCreate
from app.schemas.revenue_event import RevenueEventCreate

logger = logging.getLogger(__name__)


def verify_webhook_signature(payload_body: bytes, signature: str) -> bool:
    """Verify Razorpay webhook signature using HMAC SHA256.

    Args:
        payload_body: The raw request body bytes
        signature: The X-Razorpay-Signature header value

    Returns:
        True if signature is valid, False otherwise
    """
    settings = get_settings()
    webhook_secret = settings.razorpay_webhook_secret

    if not webhook_secret:
        logger.warning("RAZORPAY_WEBHOOK_SECRET not configured, skipping verification")
        return True

    if not signature:
        return False

    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def is_duplicate_webhook(db: Session, event_id: str) -> bool:
    """Check if a webhook event has already been processed."""
    return get_webhook_event_by_event_id(db, event_id) is not None


def process_payment_failed(db: Session, payload: dict) -> dict:
    """Handle payment.failed webhook event.

    Steps:
    1. Check idempotency (skip if already processed)
    2. Store the revenue/payment event
    3. Find or create the customer
    4. Create a RecoveryCase with AT_RISK status
    5. Store amount and failure information
    6. Create an AuditEvent

    Returns:
        dict with status and case_id if a new case was created
    """
    event_id = payload.get("id", "")
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})

    payment_id = payment.get("id", "")
    order_id = payment.get("order_id", "")
    amount = payment.get("amount", 0)
    currency = payment.get("currency", "INR")
    status = payment.get("status", "failed")
    failure_reason = payment.get("failure_reason", "Unknown")
    failure_code = payment.get("failure_code", "")
    method = payment.get("method", "")

    # customer info from payment
    email = payment.get("email", "")
    phone = payment.get("contact", "")
    customer_external_id = payment.get("customer_id", "")

    # --- Step 1: Idempotency check ---
    if is_duplicate_webhook(db, event_id):
        logger.info("Duplicate webhook event %s, skipping", event_id)
        return {"status": "skipped", "reason": "duplicate_webhook"}

    # Check if revenue event already exists for this payment
    existing_events = get_revenue_events_by_customer(
        db,
        customer_id=_get_or_create_customer_id(
            db, customer_external_id, email, phone
        ),
    )
    for event in existing_events:
        if event.external_event_id == payment_id:
            logger.info("Revenue event for payment %s already exists, skipping", payment_id)
            store_webhook_event(db, event_id, "payment.failed", payment_id)
            return {"status": "skipped", "reason": "duplicate_revenue_event"}

    # --- Step 2: Store the revenue event ---
    customer_id = _get_or_create_customer_id(db, customer_external_id, email, phone)

    revenue_event = create_revenue_event(
        db,
        data=RevenueEventCreate(
            customer_id=customer_id,
            external_event_id=payment_id,
            event_type="payment_failed",
            amount=amount,
            currency=currency,
            status=status,
            source="razorpay",
            extra_data={
                "order_id": order_id,
                "method": method,
                "failure_reason": failure_reason,
                "failure_code": failure_code,
            },
        ),
    )

    # --- Step 3 & 4: Create RecoveryCase ---
    from app.crud.recovery_case import create_recovery_case

    recovery_case = create_recovery_case(
        db,
        data=RecoveryCaseCreate(
            customer_id=customer_id,
            revenue_event_id=revenue_event.id,
            risk_level="high",
            risk_reason=f"Payment failed: {failure_reason}",
            original_amount=amount,
            remaining_amount=amount,
            max_attempts=5,
        ),
    )

    # --- Step 5: Set status to AT_RISK ---
    recovery_case.status = RecoveryStatus.AT_RISK
    db.commit()
    db.refresh(recovery_case)

    # --- Step 6: Store webhook event for idempotency ---
    store_webhook_event(db, event_id, "payment.failed", payment_id)

    # --- Step 7: Create AuditEvent ---
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=recovery_case.id,
            entity_type="recovery_case",
            entity_id=recovery_case.id,
            action="created",
            new_value={
                "status": "AT_RISK",
                "original_amount": amount,
                "failure_reason": failure_reason,
            },
            extra_data={"webhook_event_id": event_id, "payment_id": payment_id},
        ),
    )

    logger.info(
        "Created recovery case %s for failed payment %s (amount: %d)",
        recovery_case.id,
        payment_id,
        amount,
    )

    # --- Step 8: Initiate recovery workflow ---
    # Connect payment failure → recovery case → policy → WhatsApp → schedule
    from app.services.orchestrator import initiate_recovery

    recovery_result = initiate_recovery(db, recovery_case.id)
    logger.info(
        "Recovery initiation result for case %s: %s",
        recovery_case.id,
        recovery_result.get("status"),
    )

    return {
        "status": "processed",
        "case_id": str(recovery_case.id),
        "payment_id": payment_id,
        "recovery_initiated": recovery_result.get("status") == "initiated",
        "recovery_result": recovery_result,
    }


def process_payment_captured(db: Session, payload: dict) -> dict:
    """Handle payment.captured webhook event.

    Steps:
    1. Check idempotency (skip if already processed)
    2. Update payment/revenue event
    3. Find related recovery case
    4. Increase recovered_amount
    5. Mark recovery case RECOVERED if fully paid
    6. Stop any future recovery workflow
    7. Write an AuditEvent

    Returns:
        dict with status and case_id if a case was updated
    """
    event_id = payload.get("id", "")
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})

    payment_id = payment.get("id", "")
    amount = payment.get("amount", 0)
    status = payment.get("status", "captured")

    # --- Step 1: Idempotency check ---
    if is_duplicate_webhook(db, event_id):
        logger.info("Duplicate webhook event %s, skipping", event_id)
        return {"status": "skipped", "reason": "duplicate_webhook"}

    # Find the revenue event for this payment
    from sqlalchemy import select
    from app.models.revenue_event import RevenueEvent

    revenue_event = db.execute(
        select(RevenueEvent).where(RevenueEvent.external_event_id == payment_id)
    ).scalar_one_or_none()

    if not revenue_event:
        logger.warning("No revenue event found for payment %s", payment_id)
        store_webhook_event(db, event_id, "payment.captured", payment_id)
        return {"status": "skipped", "reason": "no_revenue_event"}

    # --- Step 2: Update revenue event status ---
    revenue_event.status = status
    db.commit()

    # --- Step 3: Find related recovery case ---
    # Search all non-terminal statuses (case may have moved from AT_RISK to RECOVERY_IN_PROGRESS)
    recovery_cases = (
        get_recovery_cases_by_status(db, RecoveryStatus.AT_RISK)
        + get_recovery_cases_by_status(db, RecoveryStatus.RECOVERY_IN_PROGRESS)
        + get_recovery_cases_by_status(db, RecoveryStatus.PARTIALLY_RECOVERED)
        + get_recovery_cases_by_status(db, RecoveryStatus.PROMISED)
        + get_recovery_cases_by_status(db, RecoveryStatus.SCHEDULED)
    )

    target_case = None
    for case in recovery_cases:
        if case.revenue_event_id == revenue_event.id:
            target_case = case
            break

    if not target_case:
        logger.warning(
            "No recovery case found for revenue event %s", revenue_event.id
        )
        store_webhook_event(db, event_id, "payment.captured", payment_id)
        return {"status": "skipped", "reason": "no_recovery_case"}

    # --- Step 4: Increase recovered_amount ---
    old_recovered = target_case.recovered_amount
    target_case.recovered_amount += amount
    target_case.remaining_amount = max(
        0, target_case.original_amount - target_case.recovered_amount
    )

    # --- Step 5 & 6: Mark RECOVERED if fully paid ---
    old_status = target_case.status
    if target_case.remaining_amount <= 0:
        target_case.status = RecoveryStatus.RECOVERED
        from datetime import datetime, timezone

        target_case.closed_at = datetime.now(timezone.utc)
        logger.info(
            "Recovery case %s fully recovered (amount: %d)",
            target_case.id,
            target_case.recovered_amount,
        )
    else:
        target_case.status = RecoveryStatus.PARTIALLY_RECOVERED

    db.commit()
    db.refresh(target_case)

    # --- Step 7: Store webhook event ---
    store_webhook_event(db, event_id, "payment.captured", payment_id)

    # --- Step 8: Create AuditEvent ---
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=target_case.id,
            entity_type="recovery_case",
            entity_id=target_case.id,
            action="updated",
            old_value={
                "status": str(old_status.value),
                "recovered_amount": old_recovered,
            },
            new_value={
                "status": str(target_case.status.value),
                "recovered_amount": target_case.recovered_amount,
                "remaining_amount": target_case.remaining_amount,
            },
            extra_data={"webhook_event_id": event_id, "payment_id": payment_id},
        ),
    )

    return {
        "status": "processed",
        "case_id": str(target_case.id),
        "payment_id": payment_id,
        "recovered_amount": target_case.recovered_amount,
        "remaining_amount": target_case.remaining_amount,
    }


def _get_or_create_customer_id(
    db: Session, external_id: str, email: str, phone: str
) -> "uuid.UUID":
    """Find existing customer or create a new one."""
    import uuid

    if external_id:
        customer = get_customer_by_external_id(db, external_id)
        if customer:
            return customer.id

    # Create customer with available info
    customer = create_customer(
        db,
        data=CustomerCreate(
            external_id=external_id or f"unknown_{uuid.uuid4().hex[:12]}",
            email=email or None,
            phone=phone or None,
            name=None,
        ),
    )
    return customer.id
