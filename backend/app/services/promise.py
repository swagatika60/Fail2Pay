"""Promise-to-Pay Service.

Handles:
1. Creating promises when customer says "I'll pay tomorrow"
2. Pausing generic reminders during active promise
3. Fulfilling promises when payment is received
4. Missing promises when payment deadline passes
5. Cancelling promises when customer requests stop
6. Dashboard data for promised revenue

Flow:
  Customer: "I'll pay tomorrow"
  → AI detects PROMISE_TO_PAY
  → Promise created with promised_date + grace window
  → Case status → PROMISED
  → Generic reminders PAUSED
  → Monitor payment until promised date + window
  → If paid: FULFILLED → RECOVERED
  → If missed: MISSED → resume RECOVERY_IN_PROGRESS
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.crud.customer import get_customer
from app.crud.promise import (
    create_promise,
    get_active_promise_for_case,
    mark_promise_fulfilled,
    mark_promise_missed,
    cancel_promise,
    get_expired_promises,
    count_promises_by_status,
    get_promises_by_case,
    get_dashboard_promises,
)
from app.crud.recovery_case import get_recovery_case
from app.models.promise import PromiseStatus
from app.models.recovery_case import RecoveryStatus
from app.schemas.promise import PromiseCreate

logger = logging.getLogger(__name__)

# Default promise window: 72 hours after promised date
DEFAULT_PROMISE_WINDOW_HOURS = 72


def create_promise_for_case(
    db: Session,
    case_id: uuid.UUID,
    customer_message: str | None = None,
    promised_date: datetime | None = None,
    promise_window_hours: int = DEFAULT_PROMISE_WINDOW_HOURS,
    count_attempt: bool = True,
) -> dict:
    """Create a promise for a recovery case.

    Called when customer says "I'll pay tomorrow" or similar.

    Args:
        db: Database session
        case_id: Recovery case ID
        customer_message: What the customer said
        promised_date: When they promise to pay (default: tomorrow)
        promise_window_hours: Grace period after promised date
        count_attempt: Whether this promise counts as a recovery attempt. When
            FALSE (merchant manual override at the attempt cap) the Promise is
            still persisted and reminders still paused, but the case is NOT
            re-stopped by the attempt bookkeeping — a manual action must never
            hard-stop the case or re-arm automation.

    Returns:
        dict with promise details or error
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    customer = get_customer(db, case.customer_id)
    if not customer:
        return {"status": "error", "reason": "customer_not_found"}

    # Check terminal state
    if case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        return {"status": "skipped", "reason": f"case_terminal_{case.status.value}"}

    # Check if there's already an active promise
    existing = get_active_promise_for_case(db, case_id)
    if existing:
        return {
            "status": "skipped",
            "reason": "active_promise_exists",
            "promise_id": str(existing.id),
        }

    # Default promised_date: tomorrow 18:00 UTC
    if not promised_date:
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        promised_date = tomorrow.replace(hour=18, minute=0, second=0, microsecond=0)

    # Set expiry: promised_date + window
    expires_at = promised_date + timedelta(hours=promise_window_hours)

    # Create the promise — use the authoritative remaining amount
    effective_amount = case.remaining_amount if case.remaining_amount > 0 else case.original_amount
    promise = create_promise(
        db,
        data=PromiseCreate(
            recovery_case_id=case.id,
            customer_id=customer.id,
            amount_promised=effective_amount,
            currency="INR",
            promised_date=promised_date,
            promise_window_hours=promise_window_hours,
            customer_message=customer_message,
            extra_data={
                "case_original_amount": case.original_amount,
                "case_remaining_amount": case.remaining_amount,
            },
        ),
    )

    # Set expiry after creation (required NOT NULL field)
    promise.expires_at = expires_at
    db.commit()
    db.refresh(promise)

    # Update case status to PROMISED
    case.status = RecoveryStatus.PROMISED
    db.commit()
    db.refresh(case)

    # Cancel pending generic reminders (promise pauses them)
    from app.crud.scheduled_action import cancel_pending_actions_for_case
    cancelled = cancel_pending_actions_for_case(db, case.id, reason="promise_created")

    # Record the attempt
    from app.services.workflow_engine import record_attempt
    if count_attempt:
        record_attempt(
            db=db,
            case_id=case.id,
            channel="whatsapp",
            result="promised",
            extra_data={
                "promise_id": str(promise.id),
                "promised_date": promised_date.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
        )

    # Audit
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="promise",
            entity_id=promise.id,
            action="promise_created",
            new_value={
                "promise_id": str(promise.id),
                "amount_promised": promise.amount_promised,
                "promised_date": promised_date.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
            extra_data={
                "customer_message": customer_message[:500] if customer_message else None,
            },
        ),
    )

    # Broadcast typed domain events so live dashboards react to real state,
    # regardless of the entry point (real webhook, demo driver, scheduler).
    from app.services.realtime import publish_case_event

    publish_case_event(
        event_type="promise_created",
        case_id=str(case.id),
        data={
            "promise_id": str(promise.id),
            "amount_promised": promise.amount_promised,
            "promised_date": promised_date.isoformat(),
            "expires_at": expires_at.isoformat(),
            "customer_message": customer_message,
        },
    )
    publish_case_event(
        event_type="case_status_changed",
        case_id=str(case.id),
        data={"status": "PROMISED"},
    )

    logger.info(
        "Promise created: case=%s, amount=%d, promised_date=%s, expires=%s",
        case.id, promise.amount_promised, promised_date, expires_at,
    )

    return {
        "status": "created",
        "promise_id": str(promise.id),
        "amount_promised": promise.amount_promised,
        "promised_date": promised_date.isoformat(),
        "expires_at": expires_at.isoformat(),
        "actions_cancelled": cancelled,
        "case_status": case.status.value,
    }


def fulfill_promise(
    db: Session,
    case_id: uuid.UUID,
    amount_paid: int,
) -> dict:
    """Fulfill a promise when payment is received.

    Called when payment webhook confirms payment for a PROMISED case.

    Args:
        db: Database session
        case_id: Recovery case ID
        amount_paid: Amount received in paise

    Returns:
        dict with fulfillment result
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    promise = get_active_promise_for_case(db, case_id)
    if not promise:
        return {"status": "skipped", "reason": "no_active_promise"}

    # Mark promise as fulfilled
    mark_promise_fulfilled(db, promise.id, amount_paid)

    # Update case with payment
    from app.services.workflow_engine import mark_payment_received
    payment_result = mark_payment_received(db, case_id, amount_paid)

    # Full recovery → run the deterministic finalizer so the settled case
    # leaves zero footprint (close plans, cancel emails/actions, expire links,
    # mark invoices paid).
    if payment_result.get("fully_recovered"):
        from app.services.workflow_engine import finalize_recovered_case
        finalize_recovered_case(db, case, reason="promise_fulfilled")

    # Audit
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="promise",
            entity_id=promise.id,
            action="promise_fulfilled",
            new_value={
                "promise_id": str(promise.id),
                "amount_paid": amount_paid,
                "new_status": payment_result.get("new_status"),
            },
        ),
    )

    logger.info(
        "Promise fulfilled: case=%s, promise=%s, amount=%d",
        case.id, promise.id, amount_paid,
    )

    return {
        "status": "fulfilled",
        "promise_id": str(promise.id),
        "amount_paid": amount_paid,
        "new_status": payment_result.get("new_status"),
        "fully_recovered": payment_result.get("fully_recovered", False),
    }


def check_and_expire_promises(db: Session) -> dict:
    """Check for expired promises and mark them as missed.

    Should be called periodically (e.g., by a cron job).

    Returns:
        dict with expiry results
    """
    expired = get_expired_promises(db)

    results = {
        "total_expired": len(expired),
        "expired": 0,
        "resumed": 0,
    }

    for promise in expired:
        # Mark as missed
        mark_promise_missed(db, promise.id)

        # Resume recovery (transition back to RECOVERY_IN_PROGRESS)
        case = get_recovery_case(db, promise.recovery_case_id)
        if case and case.status == RecoveryStatus.PROMISED:
            case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
            db.commit()
            db.refresh(case)

            # Reschedule recovery workflow
            from app.services.scheduler import schedule_recovery_workflow
            schedule_recovery_workflow(db, case)

            results["resumed"] += 1

            logger.info(
                "Promise missed, recovery resumed: case=%s, promise=%s",
                case.id, promise.id,
            )

        results["expired"] += 1

    return results


def cancel_promise_for_case(
    db: Session,
    case_id: uuid.UUID,
    reason: str = "customer_cancelled",
) -> dict:
    """Cancel an active promise.

    Called when customer requests stop or when case is stopped.

    Args:
        db: Database session
        case_id: Recovery case ID
        reason: Why the promise is being cancelled

    Returns:
        dict with cancellation result
    """
    promise = get_active_promise_for_case(db, case_id)
    if not promise:
        return {"status": "skipped", "reason": "no_active_promise"}

    cancel_promise(db, promise.id, reason)

    # Audit
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case_id,
            entity_type="promise",
            entity_id=promise.id,
            action="promise_cancelled",
            new_value={
                "promise_id": str(promise.id),
                "reason": reason,
            },
        ),
    )

    logger.info("Promise cancelled: case=%s, reason=%s", case_id, reason)

    return {
        "status": "cancelled",
        "promise_id": str(promise.id),
        "reason": reason,
    }


def get_promise_status(db: Session, case_id: uuid.UUID) -> dict:
    """Get promise status for a recovery case.

    Returns:
        dict with promise information
    """
    active = get_active_promise_for_case(db, case_id)
    promises = get_promises_by_case(db, case_id)

    if not active:
        return {
            "has_active_promise": False,
            "total_promises": len(promises),
            "active_count": count_promises_by_status(db, case_id, PromiseStatus.ACTIVE.value),
            "fulfilled_count": count_promises_by_status(db, case_id, PromiseStatus.FULFILLED.value),
            "missed_count": count_promises_by_status(db, case_id, PromiseStatus.MISSED.value),
        }

    return {
        "has_active_promise": True,
        "promise_id": str(active.id),
        "amount_promised": active.amount_promised,
        "promised_date": active.promised_date.isoformat(),
        "expires_at": active.expires_at.isoformat(),
        "customer_message": active.customer_message,
        "status": active.status,
        "total_promises": len(promises),
        "active_count": count_promises_by_status(db, case_id, PromiseStatus.ACTIVE.value),
        "fulfilled_count": count_promises_by_status(db, case_id, PromiseStatus.FULFILLED.value),
        "missed_count": count_promises_by_status(db, case_id, PromiseStatus.MISSED.value),
    }


def get_dashboard_data(db: Session, limit: int = 50) -> dict:
    """Get dashboard data for promised revenue.

    Returns:
        dict with dashboard metrics and promise list
    """
    from app.models.promise import PromiseStatus

    promises = get_dashboard_promises(db, limit)

    # Calculate metrics
    active_promises = [p for p in promises if p["status"] == PromiseStatus.ACTIVE.value]
    fulfilled = [p for p in promises if p["status"] == PromiseStatus.FULFILLED.value]
    missed = [p for p in promises if p["status"] == PromiseStatus.MISSED.value]

    total_promised = sum(p["amount_promised"] for p in active_promises)
    total_fulfilled = sum(p["fulfilled_amount"] for p in fulfilled)

    return {
        "metrics": {
            "total_promised_amount": total_promised,
            "total_fulfilled_amount": total_fulfilled,
            "active_count": len(active_promises),
            "fulfilled_count": len(fulfilled),
            "missed_count": len(missed),
            "fulfillment_rate": (
                round(len(fulfilled) / (len(fulfilled) + len(missed)) * 100, 1)
                if (len(fulfilled) + len(missed)) > 0
                else 0
            ),
        },
        "promises": promises,
    }
