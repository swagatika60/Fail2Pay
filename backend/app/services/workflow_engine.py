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
from app.crud.recovery_case import get_recovery_case, update_recovery_case_status
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
        RecoveryStatus.PROMISED,
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
    # STOPPED is normally terminal, but a customer-initiated re-engagement
    # (a voluntary message expressing payment intent) re-opens the case.
    RecoveryStatus.STOPPED: {
        RecoveryStatus.PROMISED,
        RecoveryStatus.RECOVERY_IN_PROGRESS,
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
    stop_reason = _check_stop_conditions(case)
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

    # Increment attempt count
    case.attempt_count += 1

    # Check if max attempts reached
    if case.attempt_count >= case.max_attempts:
        return _transition_to_stopped(db, case, "maximum_attempts_reached")

    # Check stop conditions
    stop_reason = _check_stop_conditions(case)
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
        # Full payment received
        case.status = RecoveryStatus.RECOVERED
        case.closed_at = datetime.now(timezone.utc)
    elif result == "partial_paid":
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

    return {
        "status": "recorded",
        "attempt_number": case.attempt_count,
        "result": result,
        "new_status": case.status.value,
    }


def mark_payment_received(db: Session, case_id: uuid.UUID, amount: int) -> dict:
    """Mark a payment as received for a recovery case.

    Updates recovered_amount and transitions state if fully recovered.

    Returns:
        dict with updated amounts and status
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    if case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        return {"status": "skipped", "reason": f"case_already_terminal_{case.status.value}"}

    old_status = case.status
    old_recovered = case.recovered_amount

    # Update amounts
    case.recovered_amount += amount
    case.remaining_amount = max(0, case.original_amount - case.recovered_amount)

    # Check if fully recovered
    if case.remaining_amount <= 0:
        case.status = RecoveryStatus.RECOVERED
        case.closed_at = datetime.now(timezone.utc)
    else:
        case.status = RecoveryStatus.PARTIALLY_RECOVERED

    db.commit()
    db.refresh(case)

    # Audit
    _log_transition(db, case, old_status, case.status, "payment_received")

    return {
        "status": "updated",
        "recovered_amount": case.recovered_amount,
        "remaining_amount": case.remaining_amount,
        "new_status": case.status.value,
        "fully_recovered": case.remaining_amount <= 0,
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


def _check_stop_conditions(case: RecoveryCase) -> str | None:
    """Check all hard stop conditions.

    Returns the reason if a stop condition is met, None otherwise.
    """
    # Max attempts reached
    if case.attempt_count >= case.max_attempts:
        return "maximum_attempts_recovered"

    # Recovery deadline reached
    if case.recovery_deadline:
        now = datetime.now(timezone.utc)
        deadline = case.recovery_deadline
        # Make naive datetimes comparable with aware datetimes
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            return "recovery_deadline_reached"

    # Amount fully recovered (shouldn't happen but check)
    if case.remaining_amount <= 0:
        return "payment_succeeded"

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
