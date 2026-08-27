"""No-Response Recovery Scheduler.

Default sequence:
    T+0     Initial recovery message
    T+4h    Reminder 1 (4 hours delay)
    T+12h   Reminder 2 (8 hours after reminder 1)
    T+28h   Reminder 3 (16 hours after reminder 2)
    T+60h   Final reminder (32 hours after reminder 3)
    Then:   STOP COMPLETELY

Before EVERY reminder:
    ✓ Check payment status (recovered? → stop)
    ✓ Check conversation (customer responded? → handle response)
    ✓ Check opt-out (customer opted out? → stop)
    ✓ Check recovery status (terminal? → stop)
    ✓ Check max attempts (reached? → stop)
    ✓ Check deadline (passed? → stop)

If customer responds:
    ✓ Cancel ALL pending generic reminders
    ✓ Process their response through intent detection

If customer says "Stop", "No", etc.:
    ✓ Immediately STOP recovery
    ✓ NEVER send another reminder

No AI involved — pure deterministic scheduling.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.crud.recovery_case import get_recovery_case
from app.crud.scheduled_action import (
    cancel_action,
    cancel_pending_actions_for_case,
    create_scheduled_action,
    get_due_actions,
    get_pending_actions_for_case,
    mark_action_executed,
    get_actions_by_case,
)
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.scheduled_action import ScheduledAction
from app.schemas.scheduled_action import ScheduledActionCreate
from app.services.workflow_engine import _check_stop_conditions

logger = logging.getLogger(__name__)


# --- Default schedule configuration ---
# Exponential backoff: 4h → 8h → 16h → 32h = total 60h
# T+0: initial, T+4: reminder_1, T+12: reminder_2, T+28: reminder_3, T+60: final
DEFAULT_SCHEDULE_CONFIG = [
    {"delay_hours": 0, "action_type": "initial_message", "channel": "whatsapp"},
    {"delay_hours": 4, "action_type": "reminder_1", "channel": "whatsapp"},
    {"delay_hours": 12, "action_type": "reminder_2", "channel": "whatsapp"},
    {"delay_hours": 28, "action_type": "reminder_3", "channel": "whatsapp"},
    {"delay_hours": 60, "action_type": "final_reminder", "channel": "whatsapp"},
]

# Stop request keywords (lowercase)
STOP_KEYWORDS = [
    "stop", "unsubscribe", "don't contact", "do not contact",
    "leave me alone", "don't message", "do not message",
    "i don't want", "no more", "opt out", "optout",
    "रुको", "बंद", "मत भेजो",  # Hindi
    "band karo", "mat bhejo",  # Hinglish
]


def schedule_recovery_workflow(
    db: Session,
    case: RecoveryCase,
    schedule_config: list[dict] | None = None,
) -> list[dict]:
    """Schedule the no-response recovery workflow.

    Creates 5 scheduled actions with exponential backoff:
        T+0 → T+4h → T+12h → T+28h → T+60h → STOP

    Args:
        db: Database session
        case: The recovery case to schedule for
        schedule_config: Optional custom schedule

    Returns:
        List of created scheduled action details
    """
    config = schedule_config or DEFAULT_SCHEDULE_CONFIG
    now = datetime.now(timezone.utc)

    created = []
    for i, step in enumerate(config):
        action = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type=step["action_type"],
                attempt_number=i + 1,
                channel=step["channel"],
                scheduled_for=now + timedelta(hours=step["delay_hours"]),
            ),
        )
        created.append(
            {
                "id": str(action.id),
                "action_type": action.action_type,
                "attempt_number": action.attempt_number,
                "channel": action.channel,
                "scheduled_for": action.scheduled_for.isoformat(),
            }
        )

    logger.info(
        "Scheduled %d actions for case %s", len(created), case.id
    )
    return created


def process_due_actions(db: Session) -> dict:
    """Process all due scheduled actions.

    This should be called periodically (e.g., by a cron job or background task).

    For each due action:
    1. Re-check ALL stop conditions
    2. If stop condition met → cancel this + all remaining
    3. If case is terminal → skip
    4. Otherwise → execute the action

    Returns:
        Summary dict with executed/cancelled/skipped counts
    """
    due_actions = get_due_actions(db)

    results = {
        "total_due": len(due_actions),
        "executed": 0,
        "cancelled": 0,
        "skipped": 0,
        "details": [],
    }

    for action in due_actions:
        detail = process_single_action(db, action)
        results["details"].append(detail)
        results[detail["result"]] += 1

    return results


def process_single_action(db: Session, action: ScheduledAction) -> dict:
    """Process a single scheduled action with ALL pre-reminder checks.

    Checks performed BEFORE every reminder:
    0. Centralized hard stop check (10 conditions)
    1. Case exists?
    2. Case in terminal state?
    3. Payment recovered?
    4. Max attempts reached?
    5. Recovery deadline passed?
    6. Customer opted out?
    7. Customer responded (conversation update)?

    Returns:
        dict with action_id, result (executed/cancelled/skipped), and reason
    """
    # --- Check 0: Centralized Hard Stop ---
    from app.services.hard_stop import check_hard_stop
    hard_stop = check_hard_stop(
        db, action.recovery_case_id,
        action_type=f"scheduled_{action.action_type}",
    )
    if hard_stop.blocked:
        cancel_action(db, action.id, reason=f"hard_stop_{hard_stop.stop_condition}")
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": f"hard_stop_{hard_stop.stop_condition}",
        }

    case = get_recovery_case(db, action.recovery_case_id)

    # --- Check 1: Case exists ---
    if not case:
        cancel_action(db, action.id, reason="case_not_found")
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": "case_not_found",
        }

    # --- Check 2: Terminal state ---
    if case.status in (
        RecoveryStatus.RECOVERED,
        RecoveryStatus.LOST,
        RecoveryStatus.STOPPED,
    ):
        cancel_pending_actions_for_case(
            db, case.id, reason=f"case_terminal_{case.status.value}"
        )
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": f"case_terminal_{case.status.value}",
        }

    # --- Check 3: Payment recovered ---
    if case.remaining_amount <= 0:
        _stop_case(db, case, "payment_recovered")
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": "payment_recovered",
        }

    # --- Check 4: Max attempts reached ---
    if case.attempt_count >= case.max_attempts:
        _stop_case(db, case, "max_attempts_reached")
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": "max_attempts_reached",
        }

    # --- Check 5: Recovery deadline passed ---
    if case.recovery_deadline:
        now = datetime.now(timezone.utc)
        deadline = case.recovery_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            _stop_case(db, case, "deadline_passed")
            return {
                "action_id": str(action.id),
                "result": "cancelled",
                "reason": "deadline_passed",
            }

    # --- Check 6: Customer opted out ---
    if _check_customer_opted_out(db, case):
        _stop_case(db, case, "customer_opted_out")
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": "customer_opted_out",
        }

    # --- Check 7: Customer responded (check conversation) ---
    if _check_customer_responded(db, case):
        # Customer has responded — cancel generic reminders
        cancel_pending_actions_for_case(
            db, case.id, reason="customer_responded"
        )
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": "customer_responded",
        }

    # --- Check 8: Active promise exists (pause generic reminders) ---
    if _check_active_promise(db, case):
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": "active_promise_exists",
        }

    # --- All checks passed — execute the action ---
    mark_action_executed(db, action.id)

    logger.info(
        "Executed action %s (type=%s, channel=%s) for case %s",
        action.id,
        action.action_type,
        action.channel,
        case.id,
    )

    return {
        "action_id": str(action.id),
        "result": "executed",
        "reason": None,
        "action_type": action.action_type,
        "channel": action.channel,
        "attempt_number": action.attempt_number,
    }


def handle_customer_response(
    db: Session,
    case_id,
    message: str,
) -> dict:
    """Handle a customer response to a recovery message.

    Flow:
    1. Check if message contains stop keywords → immediate stop
    2. Cancel all pending generic reminders
    3. Process the response through intent detection
    4. Execute appropriate action

    Args:
        db: Database session
        case_id: UUID of the recovery case
        message: Customer's response message

    Returns:
        dict with handling result
    """
    from app.crud.recovery_case import get_recovery_case as get_case
    from app.services.multilingual import detect_language

    case = get_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    # Check terminal state
    if case.status in (
        RecoveryStatus.RECOVERED,
        RecoveryStatus.LOST,
        RecoveryStatus.STOPPED,
    ):
        return {"status": "skipped", "reason": f"case_terminal_{case.status.value}"}

    # --- Step 1: Check for stop keywords ---
    msg_lower = message.lower().strip()
    is_stop = any(kw in msg_lower for kw in STOP_KEYWORDS)

    if is_stop:
        # Immediate stop — cancel everything
        from app.services.workflow_engine import stop_recovery
        stop_result = stop_recovery(db, case.id, "customer_requested_stop")

        # Cancel all pending actions
        cancelled = cancel_pending_actions_for_case(
            db, case.id, reason="customer_requested_stop"
        )

        logger.info(
            "Customer requested stop for case %s — cancelled %d actions",
            case.id,
            cancelled,
        )

        return {
            "status": "stopped",
            "reason": "customer_requested_stop",
            "actions_cancelled": cancelled,
            "workflow_result": stop_result,
        }

    # --- Step 2: Cancel pending generic reminders ---
    cancelled = cancel_pending_actions_for_case(
        db, case.id, reason="customer_responded"
    )

    # --- Step 3: Detect intent and classify ---
    from app.schemas.intent import IntentDetectionRequest
    from app.services.intent_detector import detect_intent

    language = detect_language(message)
    intent_request = IntentDetectionRequest(
        message=message,
        language=language,
    )
    intent_response = detect_intent(intent_request)
    detected_intent = intent_response.result.intent

    # --- Step 4: Execute action based on intent ---
    from app.services.intent_action_mapper import get_action_for_intent, render_response
    from app.crud.customer import get_customer

    action = get_action_for_intent(detected_intent)
    customer = get_customer(db, case.customer_id)

    # Update case status if needed
    if action.update_case_status:
        new_status = RecoveryStatus(action.update_case_status)
        case.status = new_status
        if action.update_case_status == "STOPPED":
            case.closed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(case)

    # Record the attempt
    from app.services.workflow_engine import record_attempt
    record_attempt(
        db=db,
        case_id=case.id,
        channel="whatsapp",
        result=action.record_attempt_result or "customer_responded",
        extra_data={
            "detected_intent": detected_intent.value,
            "customer_message": message[:500],
            "language": language,
        },
    )

    # Audit
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="customer_response",
            entity_id=case.id,
            action="response_handled",
            new_value={
                "intent": detected_intent.value,
                "action_taken": action.action_type,
                "actions_cancelled": cancelled,
                "language": language,
            },
            extra_data={
                "customer_message": message[:500],
            },
        ),
    )

    logger.info(
        "Customer response handled: case=%s, intent=%s, action=%s, cancelled=%d",
        case.id,
        detected_intent.value,
        action.action_type,
        cancelled,
    )

    return {
        "status": "handled",
        "intent": detected_intent.value,
        "action_taken": action.action_type,
        "actions_cancelled": cancelled,
        "language": language,
    }


def cancel_all_actions_for_case(
    db: Session,
    case_id,
    reason: str,
) -> int:
    """Cancel all pending actions for a case.

    Called when recovery is manually stopped, case is closed, etc.
    Returns number of actions cancelled.
    """
    count = cancel_pending_actions_for_case(db, case_id, reason)
    if count > 0:
        logger.info(
            "Cancelled %d pending actions for case %s (reason: %s)",
            count, case_id, reason,
        )
    return count


def get_schedule_status(db: Session, case_id) -> dict:
    """Get the scheduling status for a recovery case.

    Returns:
        dict with pending/executed/cancelled action counts and details
    """
    all_actions = get_actions_by_case(db, case_id)

    return {
        "case_id": str(case_id),
        "total_actions": len(all_actions),
        "pending": [
            {
                "id": str(a.id),
                "action_type": a.action_type,
                "channel": a.channel,
                "scheduled_for": a.scheduled_for.isoformat(),
                "attempt_number": a.attempt_number,
            }
            for a in all_actions
            if a.status == "pending"
        ],
        "executed": [
            {
                "id": str(a.id),
                "action_type": a.action_type,
                "channel": a.channel,
                "executed_at": a.executed_at.isoformat() if a.executed_at else None,
                "attempt_number": a.attempt_number,
            }
            for a in all_actions
            if a.status == "executed"
        ],
        "cancelled": [
            {
                "id": str(a.id),
                "action_type": a.action_type,
                "channel": a.channel,
                "cancelled_at": a.cancelled_at.isoformat() if a.cancelled_at else None,
                "cancellation_reason": a.cancellation_reason,
                "attempt_number": a.attempt_number,
            }
            for a in all_actions
            if a.status == "cancelled"
        ],
    }


# --- Internal helpers ---


def _check_customer_opted_out(db: Session, case: RecoveryCase) -> bool:
    """Check if customer has opted out of recovery."""
    # Check if case was stopped by customer request
    if case.status == RecoveryStatus.STOPPED:
        return True

    # Check last audit event for opt-out
    from app.crud.audit_event import create_audit_event
    from sqlalchemy import select
    from app.models.audit_event import AuditEvent

    last_audit = db.execute(
        select(AuditEvent)
        .where(AuditEvent.recovery_case_id == case.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if last_audit and last_audit.action == "stop_customer_requested_stop":
        return True

    return False


def _check_customer_responded(db: Session, case: RecoveryCase) -> bool:
    """Check if customer has responded since the last message.

    Looks for inbound messages in the conversation after the last outbound message.
    """
    from app.models.conversation import Conversation, ConversationStatus
    from app.models.conversation_message import ConversationMessage
    from sqlalchemy import select

    # Get the last outbound message time
    last_outbound = db.execute(
        select(ConversationMessage)
        .join(Conversation)
        .where(
            Conversation.recovery_case_id == case.id,
            Conversation.channel == "whatsapp",
            ConversationMessage.direction == "outbound",
        )
        .order_by(ConversationMessage.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not last_outbound:
        return False

    # Check for inbound messages after the last outbound
    inbound_after = db.execute(
        select(ConversationMessage)
        .join(Conversation)
        .where(
            Conversation.recovery_case_id == case.id,
            Conversation.channel == "whatsapp",
            ConversationMessage.direction == "inbound",
            ConversationMessage.created_at > last_outbound.created_at,
        )
        .limit(1)
    ).scalar_one_or_none()

    return inbound_after is not None


def _check_active_promise(db: Session, case: RecoveryCase) -> bool:
    """Check if there's an active promise for this case."""
    from app.crud.promise import get_active_promise_for_case
    promise = get_active_promise_for_case(db, case.id)
    return promise is not None


def _stop_case(db: Session, case: RecoveryCase, reason: str) -> None:
    """Stop a recovery case and cancel all pending actions."""
    # Cancel any active promise
    from app.crud.promise import get_active_promise_for_case, cancel_promise as cancel_promise_db
    active_promise = get_active_promise_for_case(db, case.id)
    if active_promise:
        cancel_promise_db(db, active_promise.id, reason=f"case_stopped_{reason}")

    case.status = RecoveryStatus.STOPPED
    case.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(case)

    cancel_pending_actions_for_case(db, case.id, reason=reason)

    logger.info("Case %s stopped: %s", case.id, reason)
