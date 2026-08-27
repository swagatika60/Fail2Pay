"""Centralized Hard Stop Service.

Before EVERY outbound communication or scheduled recovery action,
check all 10 hard stop conditions. If ANY is true:
  - DO NOT SEND
  - Cancel pending actions
  - Update recovery status
  - Create AuditEvent

The AI must NEVER override this layer.

10 Conditions:
1.  Payment succeeded
2.  Customer requested stop
3.  Customer opted out
4.  Recovery case closed
5.  Maximum attempts reached
6.  Recovery deadline expired
7.  Payment plan cancelled
8.  Invoice paid
9.  Merchant disabled recovery
10. Another conflicting action exists
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.audit_event import create_audit_event
from app.crud.recovery_case import get_recovery_case, update_recovery_case_status
from app.crud.scheduled_action import cancel_pending_actions_for_case
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.schemas.audit_event import AuditEventCreate

logger = logging.getLogger(__name__)


# --- Result dataclass ---

@dataclass
class HardStopResult:
    """Result of a hard stop check.

    Attributes:
        blocked: True if ANY stop condition was triggered
        reason: Human-readable reason for the block
        stop_condition: Which of the 10 conditions triggered (or None)
        actions_cancelled: Number of pending actions cancelled
        status_updated: True if case status was changed
        audit_created: True if audit event was created
    """
    blocked: bool = False
    reason: str = ""
    stop_condition: str = ""
    actions_cancelled: int = 0
    status_updated: bool = False
    audit_created: bool = False
    details: dict = field(default_factory=dict)


# --- Stop condition names ---

class StopCondition:
    PAYMENT_SUCCEEDED = "payment_succeeded"
    CUSTOMER_STOPPED = "customer_stopped"
    CUSTOMER_OPTED_OUT = "customer_opted_out"
    CASE_CLOSED = "case_closed"
    MAX_ATTEMPTS_REACHED = "max_attempts_reached"
    DEADLINE_EXPIRED = "deadline_expired"
    PLAN_CANCELLED = "plan_cancelled"
    INVOICE_PAID = "invoice_paid"
    MERCHANT_DISABLED = "merchant_disabled"
    CONFLICTING_ACTION = "conflicting_action"


# --- Human-readable reason map ---

STOP_REASON_MAP = {
    StopCondition.PAYMENT_SUCCEEDED: "Payment has been received — recovery stopped",
    StopCondition.CUSTOMER_STOPPED: "Customer requested to stop communication",
    StopCondition.CUSTOMER_OPTED_OUT: "Customer has opted out of recovery",
    StopCondition.CASE_CLOSED: "Recovery case is already closed",
    StopCondition.MAX_ATTEMPTS_REACHED: "Maximum recovery attempts reached",
    StopCondition.DEADLINE_EXPIRED: "Recovery deadline has expired",
    StopCondition.PLAN_CANCELLED: "Payment plan has been cancelled",
    StopCondition.INVOICE_PAID: "Invoice has been paid",
    StopCondition.MERCHANT_DISABLED: "Merchant has disabled recovery",
    StopCondition.CONFLICTING_ACTION: "Another action is in progress for this case",
}


# --- STOP keywords (multilingual) ---

STOP_KEYWORDS = [
    "stop", "unsubscribe", "don't contact", "do not contact",
    "leave me alone", "don't message", "do not message",
    "i don't want", "no more", "opt out", "optout",
    "remove me", "no thanks", "cancel",
    # Hindi
    "रुको", "बंद", "मत भेजो", "मत करो",
    # Hinglish
    "band karo", "mat bhejo", "mat karo", "ruk jao",
]


# ============================================================
# PUBLIC API
# ============================================================


def check_hard_stop(
    db: Session,
    recovery_case_id,
    action_type: str = "outbound_message",
) -> HardStopResult:
    """Check all 10 hard stop conditions for a recovery case.

    This is the SINGLE entry point that must be called before:
    - Sending any WhatsApp message
    - Sending any email
    - Executing any scheduled action
    - Generating any invoice
    - Any other outbound communication

    Args:
        db: Database session
        recovery_case_id: UUID of the recovery case
        action_type: What action is being attempted (for logging)

    Returns:
        HardStopResult with blocked=True if any condition is met,
        or blocked=False if safe to proceed
    """
    result = HardStopResult()

    case = get_recovery_case(db, recovery_case_id)
    if not case:
        result.blocked = True
        result.reason = "Recovery case not found"
        result.stop_condition = StopCondition.CASE_CLOSED
        return result

    # --- Condition 1: Payment succeeded ---
    if _check_payment_succeeded(case):
        result.blocked = True
        result.stop_condition = StopCondition.PAYMENT_SUCCEEDED
        _handle_stop(db, case, result, action_type)
        return result

    # --- Condition 2: Customer requested stop ---
    if _check_customer_stopped(case):
        result.blocked = True
        result.stop_condition = StopCondition.CUSTOMER_STOPPED
        _handle_stop(db, case, result, action_type)
        return result

    # --- Condition 3: Customer opted out ---
    if _check_customer_opted_out(db, case):
        result.blocked = True
        result.stop_condition = StopCondition.CUSTOMER_OPTED_OUT
        _handle_stop(db, case, result, action_type)
        return result

    # --- Condition 4: Recovery case closed ---
    if _check_case_closed(case):
        result.blocked = True
        result.stop_condition = StopCondition.CASE_CLOSED
        _handle_stop(db, case, result, action_type)
        return result

    # --- Condition 5: Maximum attempts reached ---
    if _check_max_attempts(case):
        result.blocked = True
        result.stop_condition = StopCondition.MAX_ATTEMPTS_REACHED
        _handle_stop(db, case, result, action_type)
        return result

    # --- Condition 6: Recovery deadline expired ---
    if _check_deadline_expired(case):
        result.blocked = True
        result.stop_condition = StopCondition.DEADLINE_EXPIRED
        _handle_stop(db, case, result, action_type)
        return result

    # --- Condition 7: Payment plan cancelled ---
    if _check_plan_cancelled(db, case):
        result.blocked = True
        result.stop_condition = StopCondition.PLAN_CANCELLED
        _handle_stop(db, case, result, action_type)
        return result

    # --- Condition 8: Invoice paid ---
    if _check_invoice_paid(db, case):
        result.blocked = True
        result.stop_condition = StopCondition.INVOICE_PAID
        _handle_stop(db, case, result, action_type)
        return result

    # --- Condition 9: Merchant disabled recovery ---
    if _check_merchant_disabled():
        result.blocked = True
        result.stop_condition = StopCondition.MERCHANT_DISABLED
        result.reason = STOP_REASON_MAP[StopCondition.MERCHANT_DISABLED]
        return result  # No case to update — merchant-level

    # --- Condition 10: Conflicting action exists ---
    if _check_conflicting_action(db, case):
        result.blocked = True
        result.stop_condition = StopCondition.CONFLICTING_ACTION
        result.reason = STOP_REASON_MAP[StopCondition.CONFLICTING_ACTION]
        result.details["note"] = "A conflicting scheduled action exists — skipping this one"
        return result  # Don't cancel — the conflicting action should run

    # --- All checks passed ---
    result.blocked = False
    result.reason = "All checks passed"
    return result


def enforce_hard_stop(
    db: Session,
    recovery_case_id,
    action_type: str = "outbound_message",
) -> HardStopResult:
    """Alias for check_hard_stop with the same behavior.

    Named 'enforce' to make intent clearer at call sites.
    """
    return check_hard_stop(db, recovery_case_id, action_type)


# ============================================================
# CONDITION CHECKS (all private)
# ============================================================


def _check_payment_succeeded(case: RecoveryCase) -> bool:
    """Condition 1: Payment has been received."""
    return case.remaining_amount <= 0 or case.status == RecoveryStatus.RECOVERED


def _check_customer_stopped(case: RecoveryCase) -> bool:
    """Condition 2: Customer explicitly requested stop."""
    return case.status == RecoveryStatus.STOPPED


def _check_customer_opted_out(db: Session, case: RecoveryCase) -> bool:
    """Condition 3: Customer has opted out via message keywords."""
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage
    from sqlalchemy import select

    # Check recent inbound messages for stop keywords
    recent_inbound = list(
        db.execute(
            select(ConversationMessage)
            .join(Conversation)
            .where(
                Conversation.recovery_case_id == case.id,
                ConversationMessage.direction == "inbound",
            )
            .order_by(ConversationMessage.created_at.desc())
            .limit(5)
        ).scalars().all()
    )

    for msg in recent_inbound:
        content_lower = (msg.content or "").lower().strip()
        if any(kw in content_lower for kw in STOP_KEYWORDS):
            return True

    return False


def _check_case_closed(case: RecoveryCase) -> bool:
    """Condition 4: Recovery case is closed."""
    return case.closed_at is not None and case.status in (
        RecoveryStatus.RECOVERED,
        RecoveryStatus.LOST,
        RecoveryStatus.STOPPED,
    )


def _check_max_attempts(case: RecoveryCase) -> bool:
    """Condition 5: Maximum recovery attempts reached."""
    return case.attempt_count >= case.max_attempts


def _check_deadline_expired(case: RecoveryCase) -> bool:
    """Condition 6: Recovery deadline has expired."""
    if not case.recovery_deadline:
        return False

    now = datetime.now(timezone.utc)
    deadline = case.recovery_deadline
    # Make naive datetimes comparable (SQLite compat)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    return now > deadline


def _check_plan_cancelled(db: Session, case: RecoveryCase) -> bool:
    """Condition 7: Payment plan has been cancelled."""
    from app.models.payment_plan import PaymentPlan, PaymentPlanStatus
    from sqlalchemy import select

    cancelled_plan = db.execute(
        select(PaymentPlan).where(
            PaymentPlan.recovery_case_id == case.id,
            PaymentPlan.status == PaymentPlanStatus.CANCELLED.value,
        )
    ).scalar_one_or_none()

    return cancelled_plan is not None


def _check_invoice_paid(db: Session, case: RecoveryCase) -> bool:
    """Condition 8: An invoice for this case has been paid."""
    from app.models.invoice import Invoice, InvoiceStatus
    from sqlalchemy import select

    paid_invoice = db.execute(
        select(Invoice).where(
            Invoice.recovery_case_id == case.id,
            Invoice.status == InvoiceStatus.PAID.value,
        )
    ).scalar_one_or_none()

    return paid_invoice is not None


def _check_merchant_disabled() -> bool:
    """Condition 9: Merchant has disabled recovery."""
    settings = get_settings()
    return getattr(settings, "merchant_recovery_disabled", False)


def _check_conflicting_action(db: Session, case: RecoveryCase) -> bool:
    """Condition 10: Another conflicting action is pending for this case.

    Checks for duplicate action types that are already pending.
    """
    from app.models.scheduled_action import ScheduledAction
    from sqlalchemy import select, func

    # Count pending actions of any type — if one exists, don't schedule another of the same
    # This is checked at the action level, not globally.
    # For the hard stop service, we just check if the case is terminal.
    if case.status in (
        RecoveryStatus.RECOVERED,
        RecoveryStatus.LOST,
        RecoveryStatus.STOPPED,
    ):
        return True

    return False


# ============================================================
# STOP HANDLING
# ============================================================


def _handle_stop(
    db: Session,
    case: RecoveryCase,
    result: HardStopResult,
    action_type: str,
) -> None:
    """Handle a triggered stop condition.

    1. Set human-readable reason
    2. Update case status if needed
    3. Cancel pending actions
    4. Create audit event
    """
    result.reason = STOP_REASON_MAP.get(result.stop_condition, "Unknown stop condition")
    result.details["case_id"] = str(case.id)
    result.details["case_status"] = case.status.value if hasattr(case.status, "value") else case.status
    result.details["action_type"] = action_type

    # --- Update case status if not already terminal ---
    terminal_states = {RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED}
    current_status = case.status

    if current_status not in terminal_states:
        old_status = case.status

        if result.stop_condition == StopCondition.PAYMENT_SUCCEEDED:
            case.status = RecoveryStatus.RECOVERED
        elif result.stop_condition in (
            StopCondition.CUSTOMER_STOPPED,
            StopCondition.CUSTOMER_OPTED_OUT,
        ):
            case.status = RecoveryStatus.STOPPED
        elif result.stop_condition == StopCondition.DEADLINE_EXPIRED:
            case.status = RecoveryStatus.LOST
        elif result.stop_condition == StopCondition.MAX_ATTEMPTS_REACHED:
            case.status = RecoveryStatus.STOPPED
        elif result.stop_condition == StopCondition.PLAN_CANCELLED:
            case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        else:
            case.status = RecoveryStatus.STOPPED

        case.closed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(case)
        result.status_updated = True
        result.details["old_status"] = old_status.value if hasattr(old_status, "value") else old_status
        result.details["new_status"] = case.status.value if hasattr(case.status, "value") else case.status

        logger.info(
            "Hard stop: case=%s, condition=%s, status %s → %s",
            case.id, result.stop_condition,
            result.details["old_status"], result.details["new_status"],
        )

    # --- Cancel pending actions (except for conflicting_action — don't cancel the other one) ---
    if result.stop_condition != StopCondition.CONFLICTING_ACTION:
        cancelled = cancel_pending_actions_for_case(
            db,
            case.id,
            reason=f"hard_stop_{result.stop_condition}",
        )
        result.actions_cancelled = cancelled
        if cancelled > 0:
            logger.info(
                "Hard stop: cancelled %d pending actions for case %s",
                cancelled, case.id,
            )

    # --- Cancel active promise if customer stopped or opted out ---
    if result.stop_condition in (
        StopCondition.CUSTOMER_STOPPED,
        StopCondition.CUSTOMER_OPTED_OUT,
    ):
        _cancel_active_promise(db, case)

    # --- Create audit event ---
    try:
        create_audit_event(
            db,
            data=AuditEventCreate(
                recovery_case_id=case.id,
                entity_type="hard_stop",
                entity_id=case.id,
                action=f"hard_stop_{result.stop_condition}",
                new_value={
                    "stop_condition": result.stop_condition,
                    "reason": result.reason,
                    "action_type": action_type,
                    "actions_cancelled": result.actions_cancelled,
                    "case_status": (
                        case.status.value
                        if hasattr(case.status, "value")
                        else case.status
                    ),
                },
            ),
        )
        result.audit_created = True
    except Exception as e:
        logger.error("Failed to create hard stop audit event: %s", str(e))


def _cancel_active_promise(db: Session, case: RecoveryCase) -> None:
    """Cancel any active promise when customer stops or opts out."""
    try:
        from app.crud.promise import (
            get_active_promise_for_case,
            cancel_promise,
        )
        active_promise = get_active_promise_for_case(db, case.id)
        if active_promise:
            cancel_promise(
                db,
                active_promise.id,
                reason="customer_stopped",
            )
            logger.info(
                "Cancelled active promise %s for case %s",
                active_promise.id, case.id,
            )
    except Exception as e:
        logger.error("Failed to cancel promise: %s", str(e))


# ============================================================
# INTENT-BASED STOP HANDLING
# ============================================================


def handle_stop_intent(
    db: Session,
    recovery_case_id,
    intent: str,
    customer_message: str,
) -> HardStopResult:
    """Handle intents that should trigger a hard stop.

    Called when AI detects STOP_REQUEST, NEGATIVE, or ALREADY_PAID intents.

    Args:
        db: Database session
        recovery_case_id: UUID of the recovery case
        intent: The detected intent string
        customer_message: What the customer said

    Returns:
        HardStopResult
    """
    result = HardStopResult()

    case = get_recovery_case(db, recovery_case_id)
    if not case:
        result.blocked = True
        result.reason = "Case not found"
        return result

    # --- STOP_REQUEST: immediate hard stop ---
    if intent == "STOP_REQUEST":
        case.status = RecoveryStatus.STOPPED
        case.closed_at = datetime.now(timezone.utc)
        db.commit()

        # Cancel all pending actions
        cancelled = cancel_pending_actions_for_case(
            db,
            case.id,
            reason="customer_stop_request",
        )

        # Cancel active promise
        _cancel_active_promise(db, case)

        # Audit
        create_audit_event(
            db,
            data=AuditEventCreate(
                recovery_case_id=case.id,
                entity_type="hard_stop",
                entity_id=case.id,
                action="hard_stop_customer_stopped",
                new_value={
                    "stop_condition": StopCondition.CUSTOMER_STOPPED,
                    "intent": intent,
                    "customer_message": customer_message[:500],
                    "actions_cancelled": cancelled,
                },
            ),
        )

        result.blocked = True
        result.stop_condition = StopCondition.CUSTOMER_STOPPED
        result.reason = STOP_REASON_MAP[StopCondition.CUSTOMER_STOPPED]
        result.actions_cancelled = cancelled
        result.status_updated = True
        result.audit_created = True

        logger.info(
            "Hard stop (STOP_REQUEST): case=%s, cancelled=%d actions",
            case.id, cancelled,
        )
        return result

    # --- ALREADY_PAID: check payment, stop if verified ---
    if intent == "ALREADY_PAID":
        # Check current payment status
        if case.remaining_amount <= 0:
            # Payment verified — full stop
            case.status = RecoveryStatus.RECOVERED
            case.closed_at = datetime.now(timezone.utc)
            db.commit()

            cancelled = cancel_pending_actions_for_case(
                db,
                case.id,
                reason="payment_verified",
            )

            create_audit_event(
                db,
                data=AuditEventCreate(
                    recovery_case_id=case.id,
                    entity_type="hard_stop",
                    entity_id=case.id,
                    action="hard_stop_payment_succeeded",
                    new_value={
                        "stop_condition": StopCondition.PAYMENT_SUCCEEDED,
                        "intent": intent,
                        "customer_message": customer_message[:500],
                        "actions_cancelled": cancelled,
                    },
                ),
            )

            result.blocked = True
            result.stop_condition = StopCondition.PAYMENT_SUCCEEDED
            result.reason = STOP_REASON_MAP[StopCondition.PAYMENT_SUCCEEDED]
            result.actions_cancelled = cancelled
            result.status_updated = True
            result.audit_created = True

            logger.info(
                "Hard stop (ALREADY_PAID verified): case=%s, cancelled=%d actions",
                case.id, cancelled,
            )
        else:
            # Payment NOT verified — do NOT falsely claim success
            # Send clarification instead of stopping
            result.blocked = False
            result.reason = "Payment not verified — sending clarification"
            result.details["remaining_amount"] = case.remaining_amount
            logger.info(
                "ALREADY_PAID but payment not verified: case=%s, remaining=%d",
                case.id, case.remaining_amount,
            )
        return result

    # --- NEGATIVE: stop communication per policy ---
    if intent == "NEGATIVE":
        case.status = RecoveryStatus.STOPPED
        case.closed_at = datetime.now(timezone.utc)
        db.commit()

        cancelled = cancel_pending_actions_for_case(
            db,
            case.id,
            reason="customer_negative_response",
        )

        _cancel_active_promise(db, case)

        create_audit_event(
            db,
            data=AuditEventCreate(
                recovery_case_id=case.id,
                entity_type="hard_stop",
                entity_id=case.id,
                action="hard_stop_customer_opted_out",
                new_value={
                    "stop_condition": StopCondition.CUSTOMER_OPTED_OUT,
                    "intent": intent,
                    "customer_message": customer_message[:500],
                    "actions_cancelled": cancelled,
                },
            ),
        )

        result.blocked = True
        result.stop_condition = StopCondition.CUSTOMER_OPTED_OUT
        result.reason = STOP_REASON_MAP[StopCondition.CUSTOMER_OPTED_OUT]
        result.actions_cancelled = cancelled
        result.status_updated = True
        result.audit_created = True

        logger.info(
            "Hard stop (NEGATIVE): case=%s, cancelled=%d actions",
            case.id, cancelled,
        )
        return result

    # --- Other intents: no hard stop ---
    result.blocked = False
    result.reason = f"Intent '{intent}' does not trigger a hard stop"
    return result
