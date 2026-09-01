"""No-Response Recovery Scheduler.

Spaced-out reminder cadence (absolute from T0):
    T+0      Initial recovery message
    T+4h     Reminder 1 (4 hours after failure)
    T+8h     Reminder 2 (8 hours after failure)
    T+16h    Reminder 3 (16 hours after failure)
    T+24h    Reminder 4 (24 hours after failure)
    T+48h    Final reminder (48 hours after failure)
    Then:    STOP COMPLETELY

Pre-Send Settlement Check:
    Before dispatching EACH scheduled reminder, the system verifies
    payment status. If the payment is already SETTLED or PAID, all
    remaining pending reminders are cancelled and no message is sent.

Before EVERY reminder:
    ✓ Check payment status (recovered/settled/paid? → stop)
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

import asyncio
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
from app.services.agent_engine import format_amount
from app.services.workflow_engine import _check_stop_conditions

logger = logging.getLogger(__name__)


# --- Default schedule configuration ---
# Spaced-out cadence (absolute from T0):
# T+0      Initial message (sent by orchestrator)
# T+4h     Reminder 1
# T+8h     Reminder 2
# T+16h    Reminder 3
# T+24h    Reminder 4
# T+48h    Final reminder
# Then: STOP COMPLETELY
DEFAULT_SCHEDULE_CONFIG = [
    {"delay_hours": 0, "action_type": "initial_message", "channel": "whatsapp"},
    {"delay_hours": 4, "action_type": "reminder_1", "channel": "whatsapp"},
    {"delay_hours": 8, "action_type": "reminder_2", "channel": "whatsapp"},
    {"delay_hours": 16, "action_type": "reminder_3", "channel": "whatsapp"},
    {"delay_hours": 24, "action_type": "reminder_4", "channel": "whatsapp"},
    {"delay_hours": 48, "action_type": "final_reminder", "channel": "whatsapp"},
]

# Stop request keywords (lowercase)
STOP_KEYWORDS = [
    "stop", "unsubscribe", "don't contact", "do not contact",
    "leave me alone", "don't message", "do not message",
    "i don't want", "no more", "opt out", "optout",
    "रुको", "बंद", "मत भेजो",  # Hindi
    "band karo", "mat bhejo",  # Hinglish
]

# --- WhatsApp audit touchpoint schedule ---
# Used by the live WhatsApp recovery stream: the first touchpoint is dispatched
# immediately on payment_failed and two automated reminders follow at 24h and
# 72h (so the case reaches a human auditor / final escalation within the SLA).
WHATSAPP_TOUCHPOINT_CONFIG = [
    {"delay_hours": 0, "action_type": "touchpoint_immediate", "channel": "whatsapp"},
    {"delay_hours": 24, "action_type": "touchpoint_24h", "channel": "whatsapp"},
    {"delay_hours": 72, "action_type": "touchpoint_72h", "channel": "whatsapp"},
]


def schedule_recovery_workflow(
    db: Session,
    case: RecoveryCase,
    schedule_config: list[dict] | None = None,
) -> list[dict]:
    """Schedule the no-response recovery workflow.

    Creates 6 scheduled actions with spaced-out cadence (absolute from T0):
        T+0 → T+4h → T+8h → T+16h → T+24h → T+48h → STOP

    Before each reminder, the scheduler checks payment status. If the
    payment is already SETTLED or PAID, all remaining reminders are
    cancelled and no message is sent.

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
        # Support both delay_hours and delay_minutes for fine-grained scheduling.
        delay_h = step.get("delay_hours", 0)
        delay_m = step.get("delay_minutes", 0)
        delay = timedelta(hours=delay_h, minutes=delay_m)
        action = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type=step["action_type"],
                attempt_number=i + 1,
                channel=step["channel"],
                scheduled_for=now + delay,
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


def schedule_whatsapp_touchpoints(
    db: Session,
    case: RecoveryCase,
) -> list[dict]:
    """Schedule the WhatsApp audit touchpoint sequence (0h / 24h / 72h).

    Called when a real Meta payment.failed webhook creates a recovery case.
    Touchpoint #1 (immediate) is dispatched by the orchestrator right away;
    the 24h and 72h entries are queued here for the background worker.
    """
    return schedule_recovery_workflow(db, case, schedule_config=WHATSAPP_TOUCHPOINT_CONFIG)


def schedule_followup_touchpoints(
    db: Session,
    case: RecoveryCase,
) -> list[dict]:
    """Queue the follow-up touchpoints (24h / 72h) AFTER the immediate ping.

    Called post-ingestion once the first touch has already been dispatched by
    the orchestrator, so we only queue the two later escalations for the
    background worker — the immediate (T+0) entry is not re-created.
    """
    followup_config = WHATSAPP_TOUCHPOINT_CONFIG[1:]  # 24h, 72h
    return schedule_recovery_workflow(db, case, schedule_config=followup_config)


def schedule_promise_reminder(
    db: Session,
    case: RecoveryCase,
    reminder_for: datetime,
) -> dict:
    """Queue a single promise reminder at an absolute timestamp.

    Used when a customer makes a promise-to-pay: a friendly reminder is
    scheduled just before the promised date so the customer is nudged when
    their commitment is due (and paused before then since the promise is live).
    """
    action = create_scheduled_action(
        db,
        data=ScheduledActionCreate(
            recovery_case_id=case.id,
            action_type="promise_reminder",
            attempt_number=1,
            channel="whatsapp",
            scheduled_for=reminder_for,
        ),
    )
    logger.info(
        "Scheduled promise reminder %s for case %s at %s",
        action.id, case.id, action.scheduled_for,
    )
    return {
        "id": str(action.id),
        "action_type": action.action_type,
        "channel": action.channel,
        "scheduled_for": action.scheduled_for.isoformat(),
    }


def process_due_actions(db: Session) -> dict:
    """Process all due scheduled actions AND the B2B receivables escalation cycle.

    This is the single heartbeat of the autonomous scheduler:
      1. Process all due recovery-case scheduled actions (WhatsApp reminders, etc.)
      2. Run the B2B receivables chaser batch (overdue detection + escalation emails)

    Returns:
        Summary dict with executed/cancelled/skipped counts + receivables results
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

    # --- B2B Receivables Chaser ---
    # Detect overdue invoices and send escalation emails automatically.
    try:
        from app.services.receivables_chaser import run_batch_escalation

        receivables_result = run_batch_escalation(db)
        results["receivables"] = receivables_result
    except Exception as exc:
        logger.error("Receivables chaser batch failed: %s", exc, exc_info=True)
        results["receivables"] = {"error": str(exc)}

    return results


# --- Background polling loop -----------------------------------------------

# Default poll cadence for the autonomous scheduler loop (in seconds).
SCHEDULER_POLL_INTERVAL_SECONDS = 30

# Each poll opens a fresh DB session (via the app's session factory) so the loop
# never shares a session across requests and can safely run as a long-lived task.
_scheduler_session_factory = None


def set_scheduler_session_factory(factory) -> None:
    """Optional: provide the app's DB session factory to the scheduler loop.

    When set, ``run_scheduler_loop`` opens a fresh session per poll through
    this factory. Otherwise it falls back to ``SessionLocal`` from app.database.
    """
    global _scheduler_session_factory
    _scheduler_session_factory = factory


async def run_scheduler_loop(
    poll_interval: float = SCHEDULER_POLL_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
    on_tick=None,
) -> None:
    """Long-lived background loop that polls for and processes due actions.

    Runs ``process_due_actions`` every ``poll_interval`` seconds until
    ``stop_event`` is set (or indefinitely when none is provided). Each tick is
    run in a thread executor so the blocking SQLAlchemy work never stalls the
    event loop. ``on_tick(results)`` is invoked after every successful poll
    (useful for tests / observability).

    This is consumed by the FastAPI app lifespan and can also be spawned by a
    supervisor process when a web worker's lifespan is not available.
    """
    import asyncio

    logger.info("Autonomous scheduler loop started (poll=%ss)", poll_interval)
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break

            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, run_one_due_poll)
            if on_tick is not None:
                on_tick(results)

            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    continue
            else:
                await asyncio.sleep(poll_interval)
    finally:
        logger.info("Autonomous scheduler loop stopped")


def run_one_due_poll() -> dict:
    """Run a single scheduler poll against a fresh DB session.

    Safe to call from any context (a test, a manual ops endpoint, or the loop's
    thread executor). Opens its own session and always closes it.
    """
    session = _open_scheduler_session()
    try:
        return process_due_actions(session)
    finally:
        session.close()


def _open_scheduler_session():
    """Open a session from the configured factory (or the app default)."""
    if _scheduler_session_factory is not None:
        return _scheduler_session_factory()
    from app.database import SessionLocal

    return SessionLocal()


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

    # --- Check 3: Payment recovered (remaining amount zero) ---
    if case.remaining_amount <= 0:
        _stop_case(db, case, "payment_recovered")
        cancel_pending_actions_for_case(
            db, case.id, reason="payment_recovered"
        )
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": "payment_recovered",
        }

    # --- Check 3b: Pre-send settlement check (PAID / SETTLED status) ---
    # Before dispatching each reminder, verify the payment status on the
    # revenue event. If Razorpay (or any gateway) already marked the
    # payment as captured/settled, cancel all remaining reminders.
    if _check_payment_settled(db, case):
        _stop_case(db, case, "payment_settled")
        cancel_pending_actions_for_case(
            db, case.id, reason="payment_settled"
        )
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": "payment_settled",
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

    # --- Check 6b: Case is under active dispute / escalated to a human ---
    # A wrong-bill / chargeback / dispute is NOT a terminal stop: it pauses
    # outreach while a human resolves it. Any eager scheduled touchpoint or
    # reminder is cancelled so the agent does not keep pinging a customer
    # whose bill is being contested.
    if _check_case_disputed(db, case):
        cancel_action(db, action.id, reason="case_disputed_escalated")
        return {
            "action_id": str(action.id),
            "result": "cancelled",
            "reason": "case_disputed_escalated",
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
    now = datetime.now(timezone.utc)
    action.scheduled_at = now
    send_result = _dispatch_action(db, case, action)
    db.flush()

    mark_action_executed(db, action.id)

    # Notify live dashboards that a scheduled touchpoint ran.
    from app.services.realtime import publish_message_event, publish_case_event

    publish_message_event(
        conversation_id="",
        case_id=str(case.id),
        message_id=str(action.id),
        direction="system",
        content=f"scheduled_action:{action.action_type}",
        message_type="scheduled_action",
        created_at=now.isoformat(),
        extra_data={
            "action_type": action.action_type,
            "attempt_number": action.attempt_number,
            "channel": action.channel,
            "send_status": send_result.get("status") if send_result else None,
        },
    )

    # Typed domain event so the live console can badge the reminder as sent.
    if action.action_type in ("reminder_1", "reminder_2", "reminder_3", "final_reminder"):
        publish_case_event(
            event_type="reminder_sent",
            case_id=str(case.id),
            data={
                "action_type": action.action_type,
                "attempt_number": action.attempt_number,
                "channel": action.channel,
                "scheduled_at": now.isoformat(),
                "sent": bool(send_result and send_result.get("status") in ("sent", "sent_no_whatsapp")),
            },
        )

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
        "reason": send_result.get("reason") if send_result else None,
        "send_status": send_result.get("status") if send_result else None,
        "action_type": action.action_type,
        "channel": action.channel,
        "attempt_number": action.attempt_number,
    }


def _dispatch_action(db: Session, case: RecoveryCase, action: ScheduledAction) -> dict | None:
    """Actually dispatch a scheduled touchpoint to its channel.

    For whatsapp-channel actions this sends the reminder through the standard
    policy + hard-stop gateway (send_text_message), which also persists the
    outbound message. Returns the transport result (never raises on a
    not-configured transport, so scheduled actions still record as executed).

    When WhatsApp is unavailable (not configured, no phone, blocked by policy),
    falls back to sending an email reminder so the customer is never left
    unreached.
    """
    if action.channel != "whatsapp":
        return None

    from app.crud.customer import get_customer

    customer = get_customer(db, case.customer_id)
    phone = customer.phone if customer else None

    text = _build_reminder_text(case, customer.name if customer else None, action)

    # --- Try WhatsApp first ---
    if phone:
        from app.services.whatsapp import send_text_message
        result = send_text_message(
            db,
            phone_number=phone,
            message=text,
            recovery_case_id=case.id,
        )
        if result and result.get("status") in ("sent", "stored"):
            return result
        # WhatsApp failed or not configured — fall through to email
        logger.info(
            "WhatsApp unavailable for case %s (status=%s), falling back to email",
            case.id, result.get("status") if result else "no_result",
        )

    # --- Email fallback ---
    if customer and customer.email:
        from app.services.email import EmailType, send_recovery_email
        from app.services.agent_engine import payment_url_for_case

        email_type = EmailType.PAYMENT_RETRY.value
        if action.action_type == "initial_message":
            email_type = EmailType.FAILED_PAYMENT.value
        elif action.action_type == "final_reminder":
            email_type = EmailType.PAYMENT_RETRY.value

        email_result = send_recovery_email(
            db=db,
            case_id=case.id,
            email_type=email_type,
            payment_link=payment_url_for_case(str(case.id)),
        )
        return {
            "status": "sent_email",
            "channel": "email",
            "email_status": email_result.get("status"),
            "email_id": email_result.get("email_id"),
        }

    return {"status": "skipped", "reason": "no_phone_and_no_email"}


def _build_reminder_text(case: RecoveryCase, customer_name: str | None, action: ScheduledAction) -> str:
    """Deterministic reminder copy for a scheduled touchpoint.

    Copy varies by action type to match the spec cadence:
    - initial_message: Gentle heads-up with root cause advice (sent by orchestrator)
    - reminder_1 (T+4h): First follow-up
    - reminder_2 (T+12h): Second follow-up
    - reminder_3 (T+28h): Third follow-up
    - final_reminder (T+60h): Final check-in before STOP
    """
    amount = format_amount(case.remaining_amount) if case.remaining_amount else ""
    name = customer_name or ""
    prefix = f"Hi {name}, " if name else "Hi there, "

    # Root cause specific advice when available
    root_cause = (case.extra_data or {}).get("root_cause") if case.extra_data else None
    cause_hint = ""
    if root_cause == "daily_limit_exceeded":
        cause_hint = "You can try Net Banking or Credit Card, or split the payment. "
    elif root_cause in ("insufficient_funds", "insufficient balance"):
        cause_hint = "We understand — you can tell us a preferred date to retry. "
    elif root_cause in ("bank_timeout", "payment_gateway_timeout", "network_error"):
        cause_hint = "If any amount was deducted, it will be reversed automatically. "

    if action.action_type == "initial_message":
        return f"{prefix}Your payment of {amount} is pending. {cause_hint}Please complete it now to resolve this."
    elif action.action_type == "reminder_1":
        # First follow-up — 4 hours after initial
        return (
            f"{prefix}Your payment of {amount} is still pending. "
            f"{cause_hint}Please complete it to avoid further follow-ups."
        )
    elif action.action_type == "reminder_2":
        # Second follow-up — 12 hours after initial
        return (
            f"{prefix}Your payment of {amount} remains unresolved. "
            f"{cause_hint}You can split into installments or tell us a preferred date."
        )
    elif action.action_type == "reminder_3":
        # Third follow-up — 28 hours after initial
        return (
            f"{prefix}We haven't heard from you about the pending payment of {amount}. "
            f"Please reply or pay to keep your account in good standing."
        )
    elif action.action_type == "final_reminder":
        # Final check-in — 60 hours after initial, before STOP
        return (
            f"{prefix}This is your final reminder for payment of {amount}. "
            f"After this, automated follow-ups will stop. Please reply or pay now."
        )
    # Default fallback
    return f"{prefix}Your payment of {amount} is still pending. Please complete it at your earliest convenience."


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


def _check_case_disputed(db: Session, case: RecoveryCase) -> bool:
    """Check if the case is under active dispute / escalated to a human.

    A case is treated as disputed when a customer raised a wrong-bill /
    chargeback / dispute that escalated to the billing desk. The agent pauses
    automated outreach (cancelling eager touchpoints) while the human owns it.

    Detection sources (in priority order):
      1. The ``escalated_to_human`` flag persisted on the case when a QUESTION
         / wrong-bill intent escalates to the human billing desk.
      2. A dispute/chargeback keyword in the stored failure/risk reasons.
    """
    extra = case.extra_data or {}
    if extra.get("escalated_to_human") or extra.get("is_disputed"):
        return True

    reason_blob = f"{extra.get('failure_reason') or ''} {case.risk_reason or ''}".lower()
    if any(
        token in reason_blob
        for token in ("dispute", "chargeback", "wrong.bill", "wrong bill", "not.mine", "not mine")
    ):
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


def _check_payment_settled(db: Session, case: RecoveryCase) -> bool:
    """Check if the payment for this case has been settled/paid.

    Verifies across multiple sources:
      1. Revenue event status is 'captured' (Razorpay confirmed)
      2. A verified Payment row with status 'captured' exists
      3. Invoice status is PAID (if invoices are tracked)

    Returns True if any source confirms the payment is settled.
    """
    from sqlalchemy import select

    # Source 1: Revenue event marked as captured
    if case.revenue_event_id:
        from app.models.revenue_event import RevenueEvent

        rev_event = db.execute(
            select(RevenueEvent).where(RevenueEvent.id == case.revenue_event_id)
        ).scalar_one_or_none()
        if rev_event and rev_event.status in ("captured", "settled", "paid"):
            logger.info(
                "Payment settled via revenue event %s (status=%s) for case %s",
                rev_event.id, rev_event.status, case.id,
            )
            return True

    # Source 2: Verified Payment row with captured status
    from app.models.payment import Payment

    captured_payment = db.execute(
        select(Payment).where(
            Payment.recovery_case_id == case.id,
            Payment.status == "captured",
        )
    ).scalar_one_or_none()
    if captured_payment:
        logger.info(
            "Payment settled via captured payment %s for case %s",
            captured_payment.id, case.id,
        )
        return True

    # Source 3: Invoice marked as PAID
    from app.models.invoice import Invoice, InvoiceStatus

    paid_invoice = db.execute(
        select(Invoice).where(
            Invoice.recovery_case_id == case.id,
            Invoice.status == InvoiceStatus.PAID.value,
        )
    ).scalar_one_or_none()
    if paid_invoice:
        logger.info(
            "Payment settled via paid invoice %s for case %s",
            paid_invoice.id, case.id,
        )
        return True

    return False


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
