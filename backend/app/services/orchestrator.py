"""Recovery Workflow Orchestrator.

Connects WhatsApp messaging to the recovery workflow:
  Payment failed → RecoveryCase AT_RISK → Recovery Policy → WhatsApp message → schedule next action

This is the main entry point for initiating and progressing recovery.
Every message is logged. RecoveryAttempt increments after sending.
Next action is scheduled automatically.

No AI involved — deterministic rule-based orchestration.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.crud.audit_event import create_audit_event
from app.crud.recovery_case import get_recovery_case
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.schemas.audit_event import AuditEventCreate
from app.schemas.policy import PolicyInput
from app.services.message_templates import (
    get_payment_link,
    get_template_for_attempt,
    render_message,
)
from app.services.policy_engine import evaluate_single_action
from app.services.workflow_engine import start_recovery, record_attempt

logger = logging.getLogger(__name__)


def initiate_recovery(
    db: Session,
    case_id: uuid.UUID,
    payment_link_base_url: str | None = None,
) -> dict:
    """Initiate the full recovery workflow for a case.

    Flow:
    1. Start recovery (AT_RISK → RECOVERY_IN_PROGRESS)
    2. Evaluate policy to check if WhatsApp is allowed
    3. Render appropriate message template
    4. Send WhatsApp message
    5. Record recovery attempt
    6. Schedule next action

    Args:
        db: Database session
        case_id: UUID of the recovery case
        payment_link_base_url: Base URL for payment links

    Returns:
        dict with full recovery initiation result
    """
    result = {
        "case_id": str(case_id),
        "steps": [],
    }

    # --- Step 1: Start recovery ---
    start_result = start_recovery(db, case_id)
    result["steps"].append({"step": "start_recovery", "result": start_result})

    if start_result["status"] == "error":
        result["status"] = "error"
        result["error"] = start_result["reason"]
        return result

    if start_result["status"] == "skipped":
        result["status"] = "skipped"
        result["reason"] = start_result["reason"]
        return result

    # --- Step 2: Evaluate policy ---
    case = get_recovery_case(db, case_id)
    if not case:
        result["status"] = "error"
        result["error"] = "case_not_found_after_start"
        return result

    policy_result = _evaluate_policy_for_case(db, case)
    result["steps"].append({"step": "evaluate_policy", "result": policy_result})

    # --- Step 3: Check if WhatsApp is the recommended action ---
    if policy_result.get("recommended_action") != "SEND_WHATSAPP":
        # Email fallback: if WhatsApp is blocked but customer has email, send email
        from app.crud.customer import get_customer as _get_cust
        _cust = _get_cust(db, case.customer_id)
        if _cust and _cust.email:
            from app.services.email import EmailType, send_recovery_email
            from app.services.agent_engine import payment_url_for_case
            email_result = send_recovery_email(
                db=db,
                case_id=case.id,
                email_type=EmailType.FAILED_PAYMENT.value,
                payment_link=payment_url_for_case(str(case.id)),
            )
            result["email_fallback"] = email_result.get("status") == "sent"
            result["email_id"] = email_result.get("email_id")
        result["status"] = "action_not_whatsapp"
        result["recommended_action"] = policy_result.get("recommended_action")
        result["reason"] = policy_result.get("reason", "policy_denied_whatsapp")
        return result

    # --- Step 4: Send WhatsApp message ---
    # Resolve the payment URL from the environment configuration when not provided.
    if not payment_link_base_url:
        from app.services.agent_engine import get_pay_host
        payment_link_base_url = get_pay_host()
    send_result = _send_recovery_message(db, case, payment_link_base_url)
    result["steps"].append({"step": "send_whatsapp", "result": send_result})

    if send_result["status"] != "sent":
        result["status"] = send_result["status"]
        result["error"] = send_result.get("reason", send_result.get("error"))
        return result

    # --- Step 5: Record recovery attempt ---
    attempt_result = record_attempt(
        db,
        case_id=case_id,
        channel="whatsapp",
        result="no_response",  # We just sent, no response yet
        extra_data={
            "message_id": send_result.get("message_id"),
            "template_stage": send_result.get("template_stage"),
            "conversation_id": send_result.get("conversation_id"),
        },
    )
    result["steps"].append({"step": "record_attempt", "result": attempt_result})

    # --- Step 6: Schedule next action ---
    schedule_result = _schedule_next_action(db, case)
    result["steps"].append({"step": "schedule_next", "result": schedule_result})

    result["status"] = "initiated"
    result["message_sent"] = True
    result["message_id"] = send_result.get("message_id")
    result["conversation_id"] = send_result.get("conversation_id")
    result["template_stage"] = send_result.get("template_stage")

    # Audit the initiation
    _audit_recovery_initiated(db, case, send_result)

    logger.info(
        "Recovery initiated: case=%s, message_id=%s, template=%s",
        case_id,
        send_result.get("message_id"),
        send_result.get("template_stage"),
    )

    return result


def process_scheduled_action(
    db: Session,
    action_id: uuid.UUID,
    payment_link_base_url: str | None = None,
) -> dict:
    """Process a scheduled recovery action (e.g., reminder).

    Called by the scheduler when a due action needs execution.
    Re-checks policy before sending.

    Args:
        db: Database session
        action_id: UUID of the scheduled action
        payment_link_base_url: Base URL for payment links

    Returns:
        dict with processing result
    """
    from app.crud.scheduled_action import get_scheduled_action, mark_action_executed

    action = get_scheduled_action(db, action_id)
    if not action:
        return {"status": "error", "reason": "action_not_found"}

    case = get_recovery_case(db, action.recovery_case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    # Check terminal state
    if case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        return {"status": "skipped", "reason": f"case_terminal_{case.status.value}"}

    # Re-evaluate policy
    policy_result = _evaluate_policy_for_case(db, case)
    if policy_result.get("recommended_action") != "SEND_WHATSAPP":
        return {
            "status": "skipped",
            "reason": "policy_not_whatsapp",
            "recommended_action": policy_result.get("recommended_action"),
        }

    # Send message
    send_result = _send_recovery_message(db, case, payment_link_base_url)
    if send_result["status"] != "sent":
        return {"status": "send_failed", "error": send_result.get("error")}

    # Record attempt
    attempt_result = record_attempt(
        db,
        case_id=case.id,
        channel="whatsapp",
        result="no_response",
        extra_data={
            "message_id": send_result.get("message_id"),
            "template_stage": send_result.get("template_stage"),
            "scheduled_action_id": str(action_id),
        },
    )

    # Mark action as executed
    mark_action_executed(db, action_id)

    # Schedule the next action in the recovery sequence
    schedule_result = _schedule_next_action(db, case)

    return {
        "status": "executed",
        "message_id": send_result.get("message_id"),
        "template_stage": send_result.get("template_stage"),
        "attempt_number": case.attempt_count,
        "next_action": schedule_result,
    }


def _evaluate_policy_for_case(db: Session, case: RecoveryCase) -> dict:
    """Evaluate the policy engine for a recovery case."""
    # Get customer
    from app.crud.customer import get_customer
    customer = get_customer(db, case.customer_id)

    # Determine previous response
    previous_response = None
    if case.recovery_attempts:
        last_attempt = case.recovery_attempts[-1]
        previous_response = last_attempt.result

    policy_input = PolicyInput(
        amount=case.original_amount,
        risk_level=case.risk_level.upper() if case.risk_level else "MEDIUM",
        attempt_count=case.attempt_count,
        max_attempts=case.max_attempts,
        previous_response=previous_response,
        payment_status="failed" if case.remaining_amount > 0 else "captured",
        case_status=case.status.value,
        has_phone=bool(customer and customer.phone),
        has_email=bool(customer and customer.email),
    )

    # Check SEND_WHATSAPP
    whatsapp_result = evaluate_single_action(policy_input, "SEND_WHATSAPP")
    return {
        "recommended_action": "SEND_WHATSAPP" if whatsapp_result.allowed else None,
        "allowed": whatsapp_result.allowed,
        "reason": whatsapp_result.reason,
        "priority": whatsapp_result.priority,
    }


def _send_recovery_message(
    db: Session,
    case: RecoveryCase,
    payment_link_base_url: str,
) -> dict:
    """Send a WhatsApp recovery message using the appropriate template."""
    from app.crud.customer import get_customer
    from app.services.whatsapp import send_text_message

    customer = get_customer(db, case.customer_id)
    if not customer or not customer.phone:
        return {"status": "error", "reason": "no_phone_number"}

    # Determine template based on attempt number
    next_attempt = case.attempt_count + 1
    template_stage = get_template_for_attempt(next_attempt)

    # Render message
    payment_link = get_payment_link(payment_link_base_url, str(case.id))
    # The first contact names the actual gateway failure reason (when known) so
    # the outreach explains the payment issue naturally instead of guessing.
    failure_reason = (
        (case.extra_data or {}).get("failure_reason")
        if template_stage == "initial_payment_failed"
        else None
    )
    rendered = render_message(
        stage=template_stage,
        customer_name=customer.name or "Customer",
        amount_paise=case.original_amount,
        payment_link=payment_link,
        failure_reason=failure_reason,
    )

    if not rendered:
        return {"status": "error", "reason": "template_not_found"}

    # --- AI Assist (optional, non-authoritative) ---
    # Rephrase the deterministic first-touch so it reads naturally in the
    # customer's language when an LLM provider is configured. The payment link
    # and amounts are preserved verbatim by validation; any timeout/failure/
    # invalid output falls back to the deterministic template body. Policy
    # decisions, attempt bookkeeping and scheduling stay untouched.
    from app.services.ai_assist import (
        personalize_message,
        explain_failure_reason,
        suggest_intervention_rank,
    )

    personalization = personalize_message(
        text=rendered.body,
        language=rendered.language,
        intent="OUTBOUND_" + template_stage.upper(),
        customer_name=customer.name or "Customer",
        amount_paise=case.original_amount,
        case_id=str(case.id),
        failure_reason=failure_reason,
    )
    if personalization["meta"].get("personalized"):
        rendered.body = personalization["text"]
        logger.info(
            "AI personalization applied to %s for case %s",
            template_stage,
            case.id,
        )

    # Advisory AI diagnosis + intervention ranking, streamed to the Agent
    # Thought Stream on the first touch. Purely non-binding: the deterministic
    # policy engine still decides what gets sent, and AI output that fails
    # validation falls back silently (meta.source stays "deterministic").
    if template_stage == "initial_payment_failed" and failure_reason:
        diagnosis = explain_failure_reason(failure_reason, language=rendered.language)
        if diagnosis["meta"].get("source") == "ai":
            from app.services.realtime import publish_reasoning_stream

            publish_reasoning_stream(
                case_id=str(case.id),
                stage="AI_DIAGNOSIS",
                label="Root cause explained",
                detail=diagnosis["text"],
                confidence=0.85,
                metadata={"failure_reason": failure_reason, "source": "ai"},
            )

    suggestion = suggest_intervention_rank(
        amount_paise=case.original_amount,
        risk_level=case.risk_level.upper() if case.risk_level else "MEDIUM",
        failure_reason=failure_reason,
        attempt_count=case.attempt_count,
    )
    if suggestion["meta"].get("source") == "ai":
        from app.services.realtime import publish_reasoning_stream

        publish_reasoning_stream(
            case_id=str(case.id),
            stage="AI_SUGGESTION",
            label="Intervention suggestion (non-binding)",
            detail="Suggested order: " + " → ".join(suggestion["ranked"]),
            confidence=0.7,
            metadata={"ranked": suggestion["ranked"], "binding": False},
        )

    # Send via WhatsApp (this also checks policy internally)
    send_result = send_text_message(
        db,
        phone_number=customer.phone,
        message=rendered.body,
        recovery_case_id=case.id,
        language=rendered.language,
    )

    # Attach template info
    send_result["template_stage"] = template_stage
    return send_result


def _schedule_next_action(db: Session, case: RecoveryCase) -> dict:
    """Schedule the next recovery action based on current attempt count."""
    from app.crud.scheduled_action import cancel_pending_actions_for_case

    # Cancel any existing pending actions for this case
    cancel_pending_actions_for_case(db, case.id, reason="rescheduling_after_attempt")

    # Determine next template stage
    next_attempt = case.attempt_count + 1
    if next_attempt > case.max_attempts:
        return {"status": "no_more_actions", "reason": "max_attempts_reached"}

    template_stage = get_template_for_attempt(next_attempt)

    # Calculate delay — merchant RecoverySetting sequence with spaced-out fallback.
    # Cadence: T0+2h, T0+4h, T0+8h, T0+16h, T0+24h, T0+36h, T0+48h (absolute from
    # failure). The template ladder maps each stage to a position in that
    # sequence: the initial message is position 0, reminder_N is position N, and
    # the final notice sits in the last (48h) slot — so the first scheduled
    # reminder lands on the 2h slot instead of skipping it.
    from app.services.recovery_settings import get_or_create

    reminder_sequence = (get_or_create(db).default_reminder_sequence) or [2, 4, 8, 16, 24, 36, 48]
    template_ladder = [
        "initial_payment_failed", "reminder_1", "reminder_2", "reminder_3",
        "reminder_4", "reminder_5", "reminder_6", "final_notice",
    ]
    position = template_ladder.index(template_stage) if template_stage in template_ladder else 1
    delay_hours = (
        reminder_sequence[min(max(position - 1, 0), len(reminder_sequence) - 1)]
        if reminder_sequence else 2
    )

    # Create the scheduled action.
    # Use case.created_at (T0) as the base so each reminder is anchored to
    # the original failure time.  Using ``now`` causes cumulative drift:
    # e.g. T+8h fires and schedules ``now + 16h`` = T+24h instead of T+16h.
    from app.crud.scheduled_action import create_scheduled_action
    from app.schemas.scheduled_action import ScheduledActionCreate

    t0 = case.created_at or datetime.now(timezone.utc)
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    scheduled_action = create_scheduled_action(
        db,
        data=ScheduledActionCreate(
            recovery_case_id=case.id,
            action_type=template_stage,
            attempt_number=next_attempt,
            channel="whatsapp",
            scheduled_for=t0 + timedelta(hours=delay_hours),
            extra_data={
                "template_stage": template_stage,
                "delay_hours": delay_hours,
            },
        ),
    )

    return {
        "status": "scheduled",
        "action_id": str(scheduled_action.id),
        "action_type": template_stage,
        "scheduled_for": scheduled_action.scheduled_for.isoformat(),
        "delay_hours": delay_hours,
    }


def _audit_recovery_initiated(
    db: Session,
    case: RecoveryCase,
    send_result: dict,
) -> None:
    """Log the recovery initiation to the audit trail."""
    # The outbound WhatsApp message itself is an audit event (MESSAGE_SENT),
    # so the policy trace's action layer reflects what was actually sent.
    from app.services.audit_logger import log_message_sent

    log_message_sent(db, case.id, channel="whatsapp")
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="recovery_case",
            entity_id=case.id,
            action="recovery_initiated",
            new_value={
                "status": case.status.value,
                "attempt_count": case.attempt_count,
                "message_sent": True,
                "message_id": send_result.get("message_id"),
                "template_stage": send_result.get("template_stage"),
            },
            extra_data={
                "channel": "whatsapp",
                "original_amount": case.original_amount,
                "remaining_amount": case.remaining_amount,
            },
        ),
    )
