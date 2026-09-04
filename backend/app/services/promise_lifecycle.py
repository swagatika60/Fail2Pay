"""Promise Lifecycle Management.

Handles:
1. Promise Monitoring & Expiration
   - Worker checks for expired promises (promised_date < now, status == ACTIVE)
   - Marks expired promises as BROKEN
   - Triggers audit event: PROMISE_MISSED

2. Transition Strategy
   - High-value transactions (>= threshold): Propose payment plan via WhatsApp
   - Standard transactions: Send polite expiry reminder, resume sequence

3. Promise History & Timeline
   - Records every promise attempt, agreed date, and fulfillment status
   - Exposes timeline data to frontend recovery case view

4. Hard Stop Enforcement
   - Active promise strictly suppresses generic 4h/8h/16h/32h reminders

Architecture:
  Worker runs periodically → check_and_process_expired_promises()
    → For each expired promise:
      → Mark as BROKEN
      → Audit: PROMISE_MISSED
      → Evaluate: high-value? → propose_payment_plan
                  standard? → send_expiry_reminder
      → Resume recovery sequence
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.audit_event import create_audit_event
from app.crud.customer import get_customer
from app.crud.promise import (
    get_promises_by_case,
    count_promises_by_status,
)
from app.crud.recovery_case import get_recovery_case
from app.models.promise import Promise, PromiseStatus
from app.models.recovery_case import RecoveryStatus
from app.schemas.audit_event import AuditEventCreate

logger = logging.getLogger(__name__)

# High-value threshold: transactions >= this amount get payment plan proposal
# Default: ₹10,000 (1000000 paise)
HIGH_VALUE_THRESHOLD_PAISE = 1_000_000


def get_high_value_threshold() -> int:
    """Get the high-value threshold in paise from config."""
    settings = get_settings()
    return getattr(settings, "promise_high_value_threshold_paise", HIGH_VALUE_THRESHOLD_PAISE)


def check_and_process_expired_promises(db: Session) -> dict:
    """Main worker: check for expired promises and process each one.

    This is the primary entry point for the promise lifecycle worker.
    Should be called periodically (e.g., every 15 minutes).

    For each expired promise:
    1. Mark as BROKEN
    2. Audit: PROMISE_MISSED
    3. Evaluate transition strategy
    4. Resume recovery

    Returns:
        dict with processing results
    """
    from app.crud.promise import get_expired_promises

    expired = get_expired_promises(db)

    results = {
        "total_expired": len(expired),
        "processed": 0,
        "high_value_escalated": 0,
        "standard_reminded": 0,
        "resumed": 0,
    }

    for promise in expired:
        result = process_expired_promise(db, promise)
        results["processed"] += 1

        if result.get("escalation") == "payment_plan":
            results["high_value_escalated"] += 1
        elif result.get("escalation") == "expiry_reminder":
            results["standard_reminded"] += 1

        if result.get("resumed"):
            results["resumed"] += 1

    return results


def process_expired_promise(db: Session, promise: Promise) -> dict:
    """Process a single expired promise.

    Steps:
    1. Mark as BROKEN
    2. Audit: PROMISE_MISSED
    3. Evaluate transition strategy
    4. Resume recovery

    Args:
        db: Database session
        promise: The expired Promise object

    Returns:
        dict with processing result
    """
    case = get_recovery_case(db, promise.recovery_case_id)
    if not case:
        logger.error("Case not found for expired promise %s", promise.id)
        return {"status": "error", "reason": "case_not_found"}

    # --- Step 1: Mark promise as BROKEN ---
    promise.status = PromiseStatus.BROKEN.value
    promise.missed_at = datetime.now(timezone.utc)
    promise.extra_data = promise.extra_data or {}
    promise.extra_data["broken_at"] = datetime.now(timezone.utc).isoformat()
    promised_dt = promise.promised_date
    if promised_dt and promised_dt.tzinfo is None:
        promised_dt = promised_dt.replace(tzinfo=timezone.utc)
    if promised_dt:
        promise.extra_data["days_since_promised"] = (
            datetime.now(timezone.utc) - promised_dt
        ).days
    else:
        promise.extra_data["days_since_promised"] = 0
    db.commit()
    db.refresh(promise)

    # --- Step 2: Audit PROMISE_MISSED ---
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="promise",
            entity_id=promise.id,
            action="promise_missed",
            new_value={
                "promise_id": str(promise.id),
                "amount_promised": promise.amount_promised,
                "promised_date": promise.promised_date.isoformat(),
                "missed_at": promise.missed_at.isoformat(),
                "days_since_promised": promise.extra_data.get("days_since_promised"),
            },
            extra_data={
                "customer_message": promise.customer_message,
                "total_promises_for_case": count_promises_by_status(
                    db, case.id, PromiseStatus.BROKEN.value
                ) + count_promises_by_status(db, case.id, PromiseStatus.MISSED.value),
            },
        ),
    )

    logger.info(
        "Promise BROKEN: case=%s, promise=%s, amount=%d",
        case.id, promise.id, promise.amount_promised,
    )

    # --- Step 3: Evaluate transition strategy ---
    escalation = _evaluate_escalation(db, case, promise)

    # --- Step 4: Resume recovery ---
    if case.status == RecoveryStatus.PROMISED:
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        db.commit()
        db.refresh(case)

        # Reschedule recovery workflow
        from app.services.scheduler import schedule_recovery_workflow
        schedule_recovery_workflow(db, case)

        logger.info("Recovery resumed for case %s after broken promise", case.id)

    return {
        "status": "processed",
        "promise_id": str(promise.id),
        "case_id": str(case.id),
        "escalation": escalation.get("type", "none"),
        "resumed": case.status == RecoveryStatus.RECOVERY_IN_PROGRESS,
    }


def _evaluate_escalation(db: Session, case, promise: Promise) -> dict:
    """Evaluate what escalation strategy to use for a broken promise.

    Strategy:
    - High-value (>= threshold): Propose payment plan via WhatsApp
    - Standard: Send polite expiry reminder

    Args:
        db: Database session
        case: RecoveryCase object
        promise: Broken Promise object

    Returns:
        dict with escalation type and details
    """
    threshold = get_high_value_threshold()

    if promise.amount_promised >= threshold:
        # High-value: propose payment plan
        return _escalate_to_payment_plan(db, case, promise)
    else:
        # Standard: send expiry reminder
        return _escalate_with_expiry_reminder(db, case, promise)


def _escalate_to_payment_plan(db: Session, case, promise: Promise) -> dict:
    """Escalate broken promise to payment plan proposal.

    For high-value transactions, proposes a split payment plan.

    Args:
        db: Database session
        case: RecoveryCase object
        promise: Broken Promise object

    Returns:
        dict with escalation details
    """
    customer = get_customer(db, case.customer_id)
    if not customer or not customer.phone:
        logger.warning("Cannot propose payment plan: no phone for case %s", case.id)
        return {"type": "payment_plan", "sent": False, "reason": "no_phone"}

    # Calculate suggested plan (3 installments)
    installment_amount = promise.amount_promised // 3
    remainder = promise.amount_promised % 3

    from app.services.multilingual import get_response_template
    from app.services.message_templates import format_amount

    formatted_amount = format_amount(promise.amount_promised)
    formatted_installment = format_amount(installment_amount + remainder)

    template = get_response_template("payment_plan", "en")
    message = template.format(
        customer_name=customer.name or "Customer",
        amount=formatted_amount,
        payment_link=f"{get_settings().payment_link_base_url}/pay/{case.id}",
    )

    # Send via WhatsApp
    from app.services.whatsapp import send_text_message
    send_result = send_text_message(
        db=db,
        phone_number=customer.phone,
        message=message,
        recovery_case_id=case.id,
    )

    # Audit
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="promise",
            entity_id=promise.id,
            action="payment_plan_proposed",
            new_value={
                "promise_id": str(promise.id),
                "amount": promise.amount_promised,
                "installments": 3,
                "installment_amount": installment_amount,
                "escalation_reason": "high_value_broken_promise",
            },
        ),
    )

    logger.info(
        "Payment plan proposed for high-value broken promise: case=%s, amount=%d",
        case.id, promise.amount_promised,
    )

    return {
        "type": "payment_plan",
        "sent": send_result.get("status") == "sent",
        "installments": 3,
        "installment_amount": installment_amount,
    }


def _escalate_with_expiry_reminder(db: Session, case, promise: Promise) -> dict:
    """Escalate broken promise with a polite expiry reminder.

    For standard transactions, sends a single reminder before resuming sequence.

    Args:
        db: Database session
        case: RecoveryCase object
        promise: Broken Promise object

    Returns:
        dict with escalation details
    """
    customer = get_customer(db, case.customer_id)
    if not customer or not customer.phone:
        logger.warning("Cannot send expiry reminder: no phone for case %s", case.id)
        return {"type": "expiry_reminder", "sent": False, "reason": "no_phone"}

    from app.services.message_templates import format_amount
    from app.config import get_settings

    formatted_amount = format_amount(promise.amount_promised)
    payment_link = f"{get_settings().payment_link_base_url}/pay/{case.id}"

    message = (
        f"Hi {customer.name or 'Customer'},\n\n"
        f"We noticed your promised payment of {formatted_amount} hasn't been received yet.\n\n"
        f"We understand things come up. You can complete your payment here:\n{payment_link}\n\n"
        f"If you need more time or want to set up a payment plan, just reply to this message."
    )

    # Send via WhatsApp
    from app.services.whatsapp import send_text_message
    send_result = send_text_message(
        db=db,
        phone_number=customer.phone,
        message=message,
        recovery_case_id=case.id,
    )

    # Audit
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="promise",
            entity_id=promise.id,
            action="expiry_reminder_sent",
            new_value={
                "promise_id": str(promise.id),
                "amount": promise.amount_promised,
                "escalation_reason": "standard_broken_promise",
            },
        ),
    )

    logger.info(
        "Expiry reminder sent for broken promise: case=%s, amount=%d",
        case.id, promise.amount_promised,
    )

    return {
        "type": "expiry_reminder",
        "sent": send_result.get("status") == "sent",
    }


def get_promise_timeline(db: Session, case_id: uuid.UUID) -> dict:
    """Get promise timeline data for frontend display.

    Returns a chronological timeline of all promise events for a case.

    Args:
        db: Database session
        case_id: Recovery case ID

    Returns:
        dict with timeline events and summary
    """
    promises = get_promises_by_case(db, case_id)

    # Build timeline events
    timeline = []
    for promise in promises:
        # Creation event
        timeline.append({
            "type": "promise_created",
            "promise_id": str(promise.id),
            "timestamp": promise.created_at.isoformat() if promise.created_at else None,
            "data": {
                "amount_promised": promise.amount_promised,
                "promised_date": promise.promised_date.isoformat(),
                "customer_message": promise.customer_message,
            },
        })

        # Status-specific events
        if promise.status == PromiseStatus.FULFILLED.value:
            timeline.append({
                "type": "promise_fulfilled",
                "promise_id": str(promise.id),
                "timestamp": promise.fulfilled_at.isoformat() if promise.fulfilled_at else None,
                "data": {
                    "fulfilled_amount": promise.fulfilled_amount,
                    "amount_promised": promise.amount_promised,
                },
            })
        elif promise.status == PromiseStatus.BROKEN.value:
            timeline.append({
                "type": "promise_broken",
                "promise_id": str(promise.id),
                "timestamp": promise.missed_at.isoformat() if promise.missed_at else None,
                "data": {
                    "amount_promised": promise.amount_promised,
                    "days_since_promised": promise.extra_data.get("days_since_promised") if promise.extra_data else None,
                },
            })
        elif promise.status == PromiseStatus.MISSED.value:
            timeline.append({
                "type": "promise_missed",
                "promise_id": str(promise.id),
                "timestamp": promise.missed_at.isoformat() if promise.missed_at else None,
                "data": {
                    "amount_promised": promise.amount_promised,
                },
            })
        elif promise.status == PromiseStatus.CANCELLED.value:
            timeline.append({
                "type": "promise_cancelled",
                "promise_id": str(promise.id),
                "timestamp": promise.cancelled_at.isoformat() if promise.cancelled_at else None,
                "data": {
                    "reason": promise.cancellation_reason,
                },
            })

    # Sort by timestamp
    timeline.sort(key=lambda x: x["timestamp"] or "", reverse=True)

    # Summary
    total_promised = sum(p.amount_promised for p in promises)
    fulfilled = [p for p in promises if p.status == PromiseStatus.FULFILLED.value]
    broken = [p for p in promises if p.status == PromiseStatus.BROKEN.value]
    active = [p for p in promises if p.status == PromiseStatus.ACTIVE.value]

    return {
        "case_id": str(case_id),
        "timeline": timeline,
        "summary": {
            "total_promises": len(promises),
            "active_count": len(active),
            "fulfilled_count": len(fulfilled),
            "broken_count": len(broken),
            "total_promised_amount": total_promised,
            "total_fulfilled_amount": sum(p.fulfilled_amount for p in fulfilled),
            "fulfillment_rate": (
                round(len(fulfilled) / len(promises) * 100, 1)
                if promises else 0
            ),
        },
    }


def get_promise_history_for_customer(
    db: Session,
    customer_id: uuid.UUID,
) -> list[dict]:
    """Get promise history for a customer across all cases.

    Returns:
        list of promise history entries
    """
    from app.crud.promise import get_promises_by_customer

    promises = get_promises_by_customer(db, customer_id)

    return [
        {
            "id": str(p.id),
            "recovery_case_id": str(p.recovery_case_id),
            "amount_promised": p.amount_promised,
            "promised_date": p.promised_date.isoformat(),
            "status": p.status,
            "fulfilled_at": p.fulfilled_at.isoformat() if p.fulfilled_at else None,
            "fulfilled_amount": p.fulfilled_amount,
            "missed_at": p.missed_at.isoformat() if p.missed_at else None,
            "cancelled_at": p.cancelled_at.isoformat() if p.cancelled_at else None,
            "customer_message": p.customer_message,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in promises
    ]
