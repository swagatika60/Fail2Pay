"""Deterministic Recovery Workflow Engine.

Manages recovery attempts, state transitions, and stopping conditions.
No AI or LLM is involved — pure rule-based logic.

State Machine:
    AT_RISK → RECOVERY_IN_PROGRESS → PROMISED → SCHEDULED → PARTIALLY_RECOVERED → RECOVERED

Terminal states (no further transitions):
    RECOVERED, LOST, STOPPED

Hard stop conditions (immediate transition to STOPPED):
    - Payment succeeded (already RECOVERED)
    - Customer requested stop
    - Customer opted out
    - Maximum attempts reached
    - Recovery deadline reached
    - Merchant disabled recovery
    - Payment plan cancelled
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crud.audit_event import create_audit_event
from app.crud.recovery_case import get_recovery_case
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.schemas.audit_event import AuditEventCreate

logger = logging.getLogger(__name__)


# --- Valid state transitions ---

# Map of current state → set of allowed next states
VALID_TRANSITIONS: dict[RecoveryStatus, set[RecoveryStatus]] = {
    RecoveryStatus.AT_RISK: {
        RecoveryStatus.RECOVERY_IN_PROGRESS,
        RecoveryStatus.STOPPED,
        RecoveryStatus.LOST,
    },
    RecoveryStatus.RECOVERY_IN_PROGRESS: {
        RecoveryStatus.ENGAGED,  # customer replied / active dialogue
        RecoveryStatus.PAYMENT_PLAN,  # installment plan accepted
        RecoveryStatus.PROMISED,
        RecoveryStatus.STOPPED,
        RecoveryStatus.LOST,
    },
    # Active dialogue with the customer. Inbound replies and negotiations move
    # the case here (and to PAYMENT_PLAN) WITHOUT consuming an outreach attempt.
    RecoveryStatus.ENGAGED: {
        RecoveryStatus.PAYMENT_PLAN,
        RecoveryStatus.PROMISED,
        RecoveryStatus.RECOVERY_IN_PROGRESS,  # if engagement stalls
        RecoveryStatus.RECOVERED,
        RecoveryStatus.STOPPED,
        RecoveryStatus.LOST,
    },
    RecoveryStatus.PAYMENT_PLAN: {
        RecoveryStatus.PROMISED,
        RecoveryStatus.RECOVERY_IN_PROGRESS,  # if a leg fails
        RecoveryStatus.RECOVERED,
        RecoveryStatus.STOPPED,
        RecoveryStatus.LOST,
    },
    RecoveryStatus.PROMISED: {
        RecoveryStatus.SCHEDULED,
        RecoveryStatus.RECOVERY_IN_PROGRESS,  # if promise broken
        RecoveryStatus.STOPPED,
        RecoveryStatus.LOST,
    },
    RecoveryStatus.SCHEDULED: {
        RecoveryStatus.PARTIALLY_RECOVERED,
        RecoveryStatus.RECOVERED,
        RecoveryStatus.RECOVERY_IN_PROGRESS,  # if scheduled payment fails
        RecoveryStatus.STOPPED,
        RecoveryStatus.LOST,
    },
    RecoveryStatus.PARTIALLY_RECOVERED: {
        RecoveryStatus.RECOVERY_IN_PROGRESS,
        RecoveryStatus.RECOVERED,
        RecoveryStatus.STOPPED,
        RecoveryStatus.LOST,
    },
    RecoveryStatus.RECOVERED: set(),  # terminal
    RecoveryStatus.LOST: set(),  # terminal
    # STOPPED is terminal for *automatic* outreach (no scheduler/orchestrator
    # restart). It may only be re-opened when the customer VOLUNTARILY re-engages
    # with payment intent — the agent layer re-activates it to RECOVERY_IN_PROGRESS,
    # from which PROMISED / RECOVERY_IN_PROGRESS are the allowed next states.
    # It is never re-opened directly to a terminal success/failure state.
    RecoveryStatus.STOPPED: {
        RecoveryStatus.RECOVERY_IN_PROGRESS,  # customer voluntarily re-engages
        RecoveryStatus.PROMISED,
    },
}


def can_transition(current: RecoveryStatus, target: RecoveryStatus) -> bool:
    """Check if a state transition is valid."""
    return target in VALID_TRANSITIONS.get(current, set())


def start_recovery(db: Session, case_id: uuid.UUID) -> dict:
    """Transition a case from AT_RISK to RECOVERY_IN_PROGRESS.

    This is typically called after the webhook creates an AT_RISK case
    and the risk engine determines recovery is appropriate.

    Returns:
        dict with status and any stop condition that was triggered
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    # Check terminal state
    if case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        return {"status": "skipped", "reason": f"case_already_terminal_{case.status.value}"}

    # Check stop conditions first
    stop_reason = _check_stop_conditions(db, case)
    if stop_reason:
        return _transition_to_stopped(db, case, stop_reason)

    # Transition to RECOVERY_IN_PROGRESS
    if not can_transition(case.status, RecoveryStatus.RECOVERY_IN_PROGRESS):
        return {"status": "error", "reason": f"invalid_transition_{case.status.value}_to_RECOVERY_IN_PROGRESS"}

    old_status = case.status
    case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
    case.recovery_started_at = case.recovery_started_at or datetime.now(timezone.utc)
    db.commit()
    db.refresh(case)

    # Audit the transition
    _log_transition(db, case, old_status, RecoveryStatus.RECOVERY_IN_PROGRESS, "start_recovery")

    return {"status": "transitioned", "from": old_status.value, "to": "RECOVERY_IN_PROGRESS"}


def record_attempt(
    db: Session,
    case_id: uuid.UUID,
    channel: str,
    result: str,
    extra_data: dict | None = None,
) -> dict:
    """Record a recovery attempt and handle state transitions.

    Args:
        case_id: The recovery case ID
        channel: Communication channel used (e.g. "whatsapp", "email", "sms")
        result: Outcome of the attempt ("paid", "promised", "no_response", "failed")
        extra_data: Optional metadata about the attempt

    Returns:
        dict with status, attempt details, and any state change
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    # Check terminal state
    if case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        return {"status": "skipped", "reason": f"case_already_terminal_{case.status.value}"}

    # ALWAYS increment attempts — cooperative negotiation does NOT override
    # the attempt limit. When max is reached, automatic outreach stops.
    case.attempt_count += 1

    # Check if max attempts reached — HARD STOP
    if case.attempt_count >= case.max_attempts:
        return _transition_to_stopped(db, case, "maximum_attempts_reached")

    # Check stop conditions
    stop_reason = _check_stop_conditions(db, case)
    if stop_reason:
        return _transition_to_stopped(db, case, stop_reason)

    # Record the attempt
    from app.models.recovery_attempt import RecoveryAttempt

    attempt = RecoveryAttempt(
        recovery_case_id=case.id,
        attempt_number=case.attempt_count,
        channel=channel,
        status="completed",
        result=result,
        extra_data=extra_data,
    )
    db.add(attempt)

    # Handle result-based transitions
    old_status = case.status
    if result == "paid":
        # Full verified payment received. A case may only become RECOVERED through
        # the deterministic finalizer (which settles plans, fulfils promises,
        # cancels outreach/emails, expires links and marks invoices paid), so we
        # do not assign RECOVERED inline here.
        _settle_as_recovered = True
    else:
        _settle_as_recovered = False

    if not _settle_as_recovered:
        if result == "partial_paid":
            # Partial payment received
            case.status = RecoveryStatus.PARTIALLY_RECOVERED
        elif result == "promised":
            # Customer promised to pay
            case.status = RecoveryStatus.PROMISED
        elif result == "scheduled":
            # Payment scheduled for later
            case.status = RecoveryStatus.SCHEDULED
        elif result in ("no_response", "failed", "declined"):
            # No response or failure - stay in RECOVERY_IN_PROGRESS
            case.status = RecoveryStatus.RECOVERY_IN_PROGRESS

    db.commit()
    db.refresh(case)

    # Audit the attempt
    _log_transition(db, case, old_status, case.status, f"attempt_{result}")

    # A verified full payment is settled through the deterministic finalizer so
    # the terminal RECOVERED transition (and its cleanup) stay single-sourced.
    if _settle_as_recovered:
        finalize_recovered_case(db, case, reason="attempt_paid")
        db.refresh(case)

    return {
        "status": "recorded",
        "attempt_number": case.attempt_count,
        "result": result,
        "new_status": case.status.value,
    }


def mark_payment_received(db: Session, case_id: uuid.UUID, amount: int) -> dict:
    """Mark a verified payment as received for a recovery case.

    Only updates recovered_amount/remaining_amount and reflects a PARTIAL
    settlement. It NEVER sets the case to the terminal RECOVERED state on its
    own — a case may only become RECOVERED through a verified ``payment.captured``
    event, which is the sole authority that runs ``finalize_recovered_case``.
    Callers that observe ``fully_recovered`` must invoke the deterministic
    finalizer to complete the terminal transition.

    Never counts ₹0 payments or non-positive amounts.

    Returns:
        dict with updated amounts and status
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    if case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        return {"status": "skipped", "reason": f"case_already_terminal_{case.status.value}"}

    # Guard: never count ₹0 or negative payments
    if amount <= 0:
        return {"status": "skipped", "reason": "invalid_amount"}

    old_status = case.status

    # Update amounts
    case.recovered_amount += amount
    case.remaining_amount = max(0, case.original_amount - case.recovered_amount)

    # Reflect partial settlement only. Full settlement (remaining <= 0) is left
    # for the caller to finalize via the verified RECOVERED transition, so the
    # invariant "RECOVERED only from a verified payment.captured" holds.
    if case.remaining_amount > 0 and case.status not in (
        RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED
    ):
        case.status = RecoveryStatus.PARTIALLY_RECOVERED

    db.commit()
    db.refresh(case)

    # Audit every credit (full or partial), regardless of whether the case's
    # ownership status advanced — RECOVERED is recorded by the verified finalizer.
    fully_recovered = case.remaining_amount <= 0
    _log_transition(db, case, old_status, case.status, "payment_received")
    db.commit()
    db.refresh(case)

    return {
        "status": "updated",
        "recovered_amount": case.recovered_amount,
        "remaining_amount": case.remaining_amount,
        "new_status": case.status.value,
        "fully_recovered": fully_recovered,
    }


def stop_recovery(db: Session, case_id: uuid.UUID, reason: str) -> dict:
    """Manually stop recovery for a case.

    Args:
        case_id: The recovery case ID
        reason: Why recovery is being stopped (e.g. "customer_requested_stop", "merchant_disabled")

    Returns:
        dict with status
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    if case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        return {"status": "skipped", "reason": f"case_already_terminal_{case.status.value}"}

    return _transition_to_stopped(db, case, reason)


def finalize_recovered_case(
    db: Session,
    case: RecoveryCase,
    *,
    reason: str = "payment_recovered",
) -> dict:
    """Deterministically finalize a fully-settled recovery case (RECOVERED).

    A recovered case is only truly settled when *everything* behind it is torn
    down — otherwise the ops console still shows dead promises, an open
    installment plan, queued reminders/emails, live payment links or unpaid
    invoices even though the balance is zero. This helper makes the RECOVERED
    state airtight (idempotent, so callers may run it repeatedly):

    - Remaining balance forced to 0; status ``RECOVERED`` + ``closed_at`` set.
    - Any ACTIVE promise is fulfilled (the capture redeemed it).
    - Any PROPOSED/ACCEPTED/ACTIVE payment plan is closed as COMPLETED.
    - Every pending ScheduledAction is cancelled (empties Next Touchpoint /
      Pipeline Queue, which are derived from pending actions).
    - Every PENDING email is cancelled (no stale outreach after settling).
    - Every ACTIVE payment link is expired (no stale pay URL reuse).
    - Every non-PAID invoice for the case is marked PAID.
    - A ``recovery_finalized`` audit event records the cleanup, and a realtime
      ``case_status_changed`` event is broadcast so live consoles reconcile.

    Returns counts so callers can feed typed domain events (e.g. the webhook's
    ``recovery_completed`` payload).
    """
    from datetime import datetime, timezone

    was_recovered = case.status == RecoveryStatus.RECOVERED

    # Settle amounts + terminal state.
    case.remaining_amount = 0
    if case.recovered_amount == 0:
        case.recovered_amount = case.original_amount or 0
    if case.status != RecoveryStatus.RECOVERED:
        case.status = RecoveryStatus.RECOVERED
    if case.closed_at is None:
        case.closed_at = datetime.now(timezone.utc)
    case.extra_data = dict(case.extra_data or {})
    case.extra_data["recovery_finalized"] = True
    case.extra_data["recovery_finalized_reason"] = reason

    # Fulfill any ACTIVE promise: a captured, verified payment satisfies it.
    from sqlalchemy import select

    from app.models.promise import Promise, PromiseStatus

    fulfilled = []
    promises = list(
        db.execute(
            select(Promise).where(
                Promise.recovery_case_id == case.id,
                Promise.status == PromiseStatus.ACTIVE.value,
            )
        ).scalars().all()
    )
    now = datetime.now(timezone.utc)
    for promise in promises:
        promise.status = PromiseStatus.FULFILLED.value
        promise.fulfilled_at = now
        promise.fulfilled_amount = promise.amount_promised
        fulfilled.append(str(promise.id))

    # Close any open payment plan (PROPOSED/ACCEPTED/ACTIVE → COMPLETED).
    from app.crud.payment_plan import (
        get_active_plan_for_case,
        update_plan_status,
    )
    from app.models.payment_plan import PaymentPlanStatus

    plan = get_active_plan_for_case(db, case.id)
    plans_closed = 0
    if plan and plan.status != PaymentPlanStatus.COMPLETED.value:
        update_plan_status(db, plan.id, PaymentPlanStatus.COMPLETED.value)
        plans_closed = 1

    # Cancel pending scheduled actions (Next Touchpoint / Pipeline Queue are
    # derived from pending actions, so cancelling clears them).
    from app.crud.email import cancel_pending_emails_for_case
    from app.crud.invoice import get_invoices_by_case, mark_invoice_paid
    from app.crud.payment_link import expire_stale_links_for_case
    from app.crud.scheduled_action import cancel_pending_actions_for_case

    actions_cancelled = cancel_pending_actions_for_case(
        db, case.id, reason=f"finalized_{reason}"
    )
    emails_cancelled = cancel_pending_emails_for_case(db, case.id)
    links_expired = expire_stale_links_for_case(db, case.id)

    invoices = list(get_invoices_by_case(db, case.id))
    if not invoices:
        # Materialize the failed-payment invoice on finalization so every
        # settled case carries a real Invoice that flips to PAID here.
        from app.services.invoice import create_recovery_invoice
        create_result = create_recovery_invoice(
            db,
            case.id,
            description=f"Invoice for recovered payment of {case.original_amount}",
        )
        if create_result.get("status") == "created":
            invoices = list(get_invoices_by_case(db, case.id))

    invoices_paid = 0
    for invoice in invoices:
        if invoice.status in ("PAID", "CANCELLED"):
            continue
        mark_invoice_paid(db, invoice.id)
        invoices_paid += 1

    # Audit the finalization.
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="recovery_case",
            entity_id=case.id,
            action="recovery_finalized",
            old_value={"status": case.status.value, "recovered_before": was_recovered},
            new_value={
                "status": case.status.value,
                "remaining_amount": 0,
                "promises_fulfilled": fulfilled,
                "plan_closed": str(plan.id) if plan else None,
                "actions_cancelled": actions_cancelled,
                "emails_cancelled": emails_cancelled,
                "links_expired": links_expired,
                "invoices_paid": invoices_paid,
                "reason": reason,
            },
            extra_data={"reason": reason},
        ),
    )

    db.commit()
    db.refresh(case)

    # Send the automatic payment-success email to the customer, but only on the
    # transition into RECOVERED (this finalizer is idempotent and re-runs, so we
    # avoid spamming the customer on every repeat invocation).
    if not was_recovered:
        try:
            from app.services.email import EmailType, send_recovery_email
            from app.services.agent_engine import payment_url_for_case

            send_recovery_email(
                db=db,
                case_id=case.id,
                email_type=EmailType.PAYMENT_SUCCESS.value,
                payment_link=payment_url_for_case(str(case.id)),
            )
        except Exception:
            logger.warning(
                "Failed to auto-send payment-success email for case %s",
                case.id,
                exc_info=True,
            )

    # Broadcast the terminal transition so live consoles reconcile without a poll.
    from app.services.realtime import publish_case_event

    publish_case_event(
        event_type="recovery_completed",
        case_id=str(case.id),
        data={
            "status": case.status.value,
            "recovered_amount": case.recovered_amount,
            "remaining_amount": 0,
            "cancelled_emails": emails_cancelled,
            "fulfilled_promises": fulfilled,
            "plans_closed": plans_closed,
            "links_expired": links_expired,
            "invoices_paid": invoices_paid,
        },
    )
    publish_case_event(
        event_type="case_status_changed",
        case_id=str(case.id),
        data={"status": case.status.value, "finalized": True},
    )

    logger.info(
        "Recovery finalized: case=%s reason=%s promises=%d plan_closed=%d "
        "actions=%d emails=%d links=%d invoices=%d",
        case.id, reason, len(fulfilled), plans_closed,
        actions_cancelled, emails_cancelled, links_expired, invoices_paid,
    )

    return {
        "status": "finalized",
        "case_id": str(case.id),
        "promises_fulfilled": fulfilled,
        "plans_closed": plans_closed,
        "actions_cancelled": actions_cancelled,
        "emails_cancelled": emails_cancelled,
        "links_expired": links_expired,
        "invoices_paid": invoices_paid,
    }


def mark_lost(db: Session, case_id: uuid.UUID, reason: str = "recovery_failed") -> dict:
    """Mark a case as LOST (revenue not recoverable).

    Args:
        case_id: The recovery case ID
        reason: Why the case is being marked as lost

    Returns:
        dict with status
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    if case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        return {"status": "skipped", "reason": f"case_already_terminal_{case.status.value}"}

    old_status = case.status
    case.status = RecoveryStatus.LOST
    case.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(case)

    _log_transition(db, case, old_status, RecoveryStatus.LOST, f"mark_lost_{reason}")

    return {"status": "transitioned", "to": "LOST", "reason": reason}


def get_workflow_status(db: Session, case_id: uuid.UUID) -> dict:
    """Get current workflow status for a case.

    Returns:
        dict with current state, attempts, and next valid actions
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    current = case.status
    terminal = current in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED)

    return {
        "case_id": str(case.id),
        "current_status": current.value,
        "is_terminal": terminal,
        "attempt_count": case.attempt_count,
        "max_attempts": case.max_attempts,
        "recovered_amount": case.recovered_amount,
        "remaining_amount": case.remaining_amount,
        "original_amount": case.original_amount,
        "recovery_started_at": case.recovery_started_at.isoformat() if case.recovery_started_at else None,
        "recovery_deadline": case.recovery_deadline.isoformat() if case.recovery_deadline else None,
        "closed_at": case.closed_at.isoformat() if case.closed_at else None,
        "valid_next_states": [s.value for s in VALID_TRANSITIONS.get(current, set())],
    }


# --- Internal helpers ---


def _is_cooperatively_negotiating(db: Session, case: RecoveryCase) -> bool:
    """Check if the customer is actively negotiating with cooperative sentiment.

    Returns True when the most recent inbound message has cooperative signals
    (willingness to pay, requesting adjustments, etc.) AND the case is in an
    engaged state (ENGAGED or PAYMENT_PLAN). This prevents marking a case as
    LOST/STOPPED when the customer is still at the table.
    """
    from app.services.agent_engine import assess_sentiment
    from sqlalchemy import select

    try:
        from app.models.conversation import Conversation
        from app.models.conversation_message import ConversationMessage

        conv = (
            db.execute(
                select(Conversation)
                .where(
                    Conversation.recovery_case_id == case.id,
                    Conversation.channel == "whatsapp",
                )
                .order_by(Conversation.created_at.desc())
            ).scalars().first()
        )
        if conv is None:
            return False

        # Get the most recent inbound message
        last_inbound = (
            db.execute(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == conv.id,
                    ConversationMessage.direction == "inbound",
                )
                .order_by(ConversationMessage.created_at.desc())
                .limit(1)
            ).scalars().first()
        )
        if last_inbound is None:
            return False

        sentiment = assess_sentiment(last_inbound.content)
        return sentiment == "Cooperative"
    except Exception:  # noqa: BLE001 - never let sentiment check break recovery
        return False


def _check_stop_conditions(db: Session, case: RecoveryCase) -> str | None:
    """Check all hard stop conditions.

    Returns the reason if a stop condition is met, None otherwise.

    CRITICAL RULE: When attempts reach max_attempts, automatic outreach
    MUST stop completely. No cooperative negotiation can override this.
    The case enters monitor_mode (STOPPED) but merchant manual actions
    remain available.
    """
    # Amount fully recovered (shouldn't happen but check)
    if case.remaining_amount <= 0:
        return "payment_succeeded"

    # Max attempts reached — HARD STOP, no override
    # Automatic outreach stops completely. Merchant manual input remains.
    if case.attempt_count >= case.max_attempts:
        return "maximum_attempts_reached"

    # Recovery deadline reached
    if case.recovery_deadline:
        now = datetime.now(timezone.utc)
        deadline = case.recovery_deadline
        # Make naive datetimes comparable with aware datetimes
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            return "recovery_deadline_reached"

    return None


def _transition_to_stopped(db: Session, case: RecoveryCase, reason: str) -> dict:
    """Transition a case to STOPPED with a reason."""
    old_status = case.status
    case.status = RecoveryStatus.STOPPED
    case.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(case)

    _log_transition(db, case, old_status, RecoveryStatus.STOPPED, f"stop_{reason}")

    return {
        "status": "stopped",
        "reason": reason,
        "from": old_status.value,
        "to": "STOPPED",
    }


def _log_transition(
    db: Session,
    case: RecoveryCase,
    old_status: RecoveryStatus,
    new_status: RecoveryStatus,
    action: str,
) -> None:
    """Log a state transition to the audit trail."""
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="recovery_case",
            entity_id=case.id,
            action="status_changed",
            old_value={"status": old_status.value},
            new_value={"status": new_status.value},
            extra_data={
                "action": action,
                "attempt_count": case.attempt_count,
                "recovered_amount": case.recovered_amount,
                "remaining_amount": case.remaining_amount,
            },
        ),
    )
