"""Case Detail API endpoints.

Provides detailed data for a recovery case:
- Promise timeline
- Payment plan with installments
- Conversation messages
- Email history
- Hard stop / audit log
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.recovery_case import RecoveryStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cases", tags=["case-detail"])


@router.get("/{case_id}/agent-steps")
def get_case_agent_steps(case_id: UUID, db: Session = Depends(get_db)):
    """Agent Thought Stream for a recovery case (persisted reasoning chain).

    Returns the ordered reasoning steps (Trigger → Diagnosis → Policy →
    Action → Ledger) that drove this case, plus light telemetry. Mirrors what
    is broadcast live over ``/ws/cases/{case_id}``.
    """
    from app.models.recovery_case import RecoveryCase
    from app.services import agent_steps

    case = db.get(RecoveryCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    steps = agent_steps.get_case_steps(db, case_id)
    return {
        "case_id": str(case_id),
        "steps": steps,
        "summary": agent_steps.summarize_steps(steps),
    }


@router.get("/{case_id}/promises")
def get_case_promises(case_id: UUID, db: Session = Depends(get_db)):
    """Get all promises for a recovery case."""
    from app.models.promise import Promise
    from app.models.customer import Customer
    from sqlalchemy import select

    promises = list(
        db.execute(
            select(Promise)
            .where(Promise.recovery_case_id == case_id)
            .order_by(Promise.created_at.desc())
        ).scalars().all()
    )

    return [
        {
            "id": str(p.id),
            "amount_promised": p.amount_promised,
            "currency": p.currency,
            "promised_date": p.promised_date.isoformat() if p.promised_date else None,
            "expires_at": p.expires_at.isoformat() if p.expires_at else None,
            "status": p.status,
            "customer_message": p.customer_message,
            "fulfilled_at": p.fulfilled_at.isoformat() if p.fulfilled_at else None,
            "fulfilled_amount": p.fulfilled_amount,
            "missed_at": p.missed_at.isoformat() if p.missed_at else None,
            "cancelled_at": p.cancelled_at.isoformat() if p.cancelled_at else None,
            "cancellation_reason": p.cancellation_reason,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in promises
    ]


@router.get("/{case_id}/payment-plans")
def get_case_payment_plans(case_id: UUID, db: Session = Depends(get_db)):
    """Get payment plans with installments for a recovery case."""
    from app.models.payment_plan import PaymentPlan
    from app.models.installment import Installment
    from sqlalchemy import select

    plans = list(
        db.execute(
            select(PaymentPlan)
            .where(PaymentPlan.recovery_case_id == case_id)
            .order_by(PaymentPlan.created_at.desc())
        ).scalars().all()
    )

    result = []
    for plan in plans:
        installments = list(
            db.execute(
                select(Installment)
                .where(Installment.payment_plan_id == plan.id)
                .order_by(Installment.installment_number)
            ).scalars().all()
        )

        result.append({
            "id": str(plan.id),
            "total_amount": plan.total_amount,
            "installment_amount": plan.installment_amount,
            "number_of_installments": plan.number_of_installments,
            "frequency": plan.frequency,
            "currency": plan.currency,
            "status": plan.status,
            "amount_paid": plan.amount_paid,
            "installments_paid": plan.installments_paid,
            "installments_failed": plan.installments_failed,
            "first_payment_date": plan.first_payment_date.isoformat() if plan.first_payment_date else None,
            "last_payment_date": plan.last_payment_date.isoformat() if plan.last_payment_date else None,
            "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "installments": [
                {
                    "id": str(inst.id),
                    "installment_number": inst.installment_number,
                    "amount": inst.amount,
                    "due_date": inst.due_date.isoformat() if inst.due_date else None,
                    "status": inst.status,
                    "paid_at": inst.paid_at.isoformat() if inst.paid_at else None,
                    "paid_amount": inst.paid_amount,
                    "failed_at": inst.failed_at.isoformat() if inst.failed_at else None,
                    "failure_reason": inst.failure_reason,
                    "razorpay_payment_id": inst.razorpay_payment_id,
                }
                for inst in installments
            ],
        })

    return result


@router.get("/{case_id}/conversations")
def get_case_conversations(case_id: UUID, db: Session = Depends(get_db)):
    """Get conversation messages for a recovery case."""
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage
    from sqlalchemy import select

    conversations = list(
        db.execute(
            select(Conversation)
            .where(Conversation.recovery_case_id == case_id)
            .order_by(Conversation.created_at.desc())
        ).scalars().all()
    )

    result = []
    for conv in conversations:
        messages = list(
            db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conv.id)
                .order_by(ConversationMessage.created_at)
            ).scalars().all()
        )

        result.append({
            "id": str(conv.id),
            "channel": conv.channel,
            "status": conv.status.value if hasattr(conv.status, "value") else conv.status,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "messages": [
                {
                    "id": str(msg.id),
                    "direction": msg.direction,
                    "content": msg.content,
                    "message_type": msg.message_type,
                    "extra_data": msg.extra_data,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
                for msg in messages
            ],
        })

    return result


@router.get("/{case_id}/emails")
def get_case_emails(case_id: UUID, db: Session = Depends(get_db)):
    """Get email history for a recovery case."""
    from app.models.email import SentEmail
    from sqlalchemy import select

    emails = list(
        db.execute(
            select(SentEmail)
            .where(SentEmail.recovery_case_id == case_id)
            .order_by(SentEmail.created_at.desc())
        ).scalars().all()
    )

    return [
        {
            "id": str(e.id),
            "email_type": e.email_type,
            "recipient_email": e.recipient_email,
            "subject": e.subject,
            "body": e.body,
            "delivery_status": e.delivery_status,
            "provider_message_id": e.provider_message_id,
            "error_message": e.error_message,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            "delivered_at": e.delivered_at.isoformat() if e.delivered_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in emails
    ]


@router.get("/{case_id}/hard-stops")
def get_case_hard_stops(case_id: UUID, db: Session = Depends(get_db)):
    """Get hard stop events for a recovery case."""
    from app.models.audit_event import AuditEvent
    from sqlalchemy import select

    hard_stops = list(
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.recovery_case_id == case_id,
                AuditEvent.entity_type == "hard_stop",
            )
            .order_by(AuditEvent.created_at.desc())
        ).scalars().all()
    )

    return [
        {
            "id": str(hs.id),
            "action": hs.action,
            "new_value": hs.new_value,
            "created_at": hs.created_at.isoformat() if hs.created_at else None,
        }
        for hs in hard_stops
    ]


@router.get("/{case_id}/voice-calls")
def get_case_voice_calls(case_id: UUID, db: Session = Depends(get_db)):
    """Get voice interaction history for a recovery case.

    Every IVR call (inbound / outbound / ivr-action) is logged as a
    ``voice_call`` audit event — surfaced here so the ops console shows the
    full voice recovery thread next to WhatsApp and email.
    """
    from app.models.audit_event import AuditEvent
    from sqlalchemy import select

    events = list(
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.recovery_case_id == case_id,
                AuditEvent.entity_type == "voice_call",
            )
            .order_by(AuditEvent.created_at.desc())
        ).scalars().all()
    )

    result = []
    for ev in events:
        meta = ev.new_value or {}
        result.append(
            {
                "id": str(ev.id),
                "call_sid": meta.get("call_sid", ""),
                "direction": meta.get("direction", ""),
                "duration_seconds": meta.get("duration_seconds", 0),
                "transcription": meta.get("transcription", ""),
                "intent": meta.get("intent", ""),
                "dtmf_input": meta.get("dtmf_input", ""),
                "language": meta.get("language", ""),
                "status": meta.get("status", ""),
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
        )
    return result


@router.get("/{case_id}/timeline")
def get_case_timeline(case_id: UUID, db: Session = Depends(get_db)):
    """Get the full recovery timeline for a case.

    Returns all audit events sorted chronologically with
    human-readable descriptions — a judge should be able to
    understand exactly what happened, when, why, and what the system did.
    """
    from app.services.audit_logger import get_recovery_timeline
    return get_recovery_timeline(db, case_id)


@router.get("/{case_id}/schedule")
def get_case_schedule(case_id: UUID, db: Session = Depends(get_db)):
    """Get the automated touchpoint / reminder queue for a recovery case.

    Returns the full scheduled-action state plus the *next pending* touchpoint
    with a human-friendly label, so the ops console can show a countdown or a
    scheduled timestamp (e.g. "Next Ping: Tomorrow at 10:00 AM").
    """
    from datetime import datetime, timezone

    from app.services.scheduler import get_schedule_status

    status = get_schedule_status(db, case_id)

    pending = status["pending"]
    next_action = None
    if pending:
        def _as_dt(s):
            try:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                return None

        due = [p for p in pending if _as_dt(p["scheduled_for"])]
        due.sort(key=lambda p: _as_dt(p["scheduled_for"]) or datetime.max.replace(tzinfo=timezone.utc))
        earliest = due[0] if due else None
        if earliest:
            next_action = {
                "action_id": earliest["id"],
                "action_type": earliest["action_type"],
                "attempt_number": earliest["attempt_number"],
                "channel": earliest["channel"],
                "scheduled_for": earliest["scheduled_for"],
                "due": bool(_as_dt(earliest["scheduled_for"]).replace(tzinfo=None) <= datetime.now(timezone.utc).replace(tzinfo=None)),
            }

    return {
        "case_id": str(case_id),
        "total_actions": status["total_actions"],
        "pending_count": len(status["pending"]),
        "executed_count": len(status["executed"]),
        "cancelled_count": len(status["cancelled"]),
        "next_action": next_action,
        "pending": status["pending"],
    }


# ============================================================
# POLICY TRACE / DECISION AUDIT TRAIL
# ============================================================


@router.get("/{case_id}/policy-trace")
def get_case_policy_trace(case_id: UUID, db: Session = Depends(get_db)):
    """Get the structured decision audit trail for a recovery case.

    Reconstructs the AI/Policy decision chain into labeled layers so a
    judge can verify HOW each action was decided:

      - trigger       : the initiating failed-payment event (reason)
      - ai_judgment   : bounded AI intent classification (confidence/source)
      - policy        : deterministic policy rules applied (why allowed/denied)
      - action        : the dispatched action (channel, tone, payload summary)
      - outcome       : the resulting outcome (recovered / blocked / etc.)

    Every event carries its source layer, human-readable reason, and the
    money impact (only verified captured payments are revenue).
    """
    from app.models.audit_event import AuditEvent
    from app.models.recovery_case import RecoveryCase
    from sqlalchemy import select

    case = db.execute(
        select(RecoveryCase).where(RecoveryCase.id == case_id)
    ).scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    events = list(
        db.execute(
            select(AuditEvent)
            .where(AuditEvent.recovery_case_id == case_id)
            .order_by(AuditEvent.created_at.asc())
        ).scalars().all()
    )

    chain = []
    for event in events:
        meta = event.extra_data or {}
        event_type = event.action

        node = {
            "id": str(event.id),
            "event_type": event_type,
            "timestamp": event.created_at.isoformat() if event.created_at else None,
            "reason": meta.get("reason", ""),
            "result": meta.get("result", ""),
            "amount": meta.get("amount"),
            "amount_formatted": meta.get("amount_formatted"),
            "metadata": meta,
            "old_value": event.old_value,
            "new_value": event.new_value,
            "layer": _classify_policy_layer(event_type),
        }
        chain.append(node)

    return {
        "case_id": str(case.id),
        "original_amount": case.original_amount,
        "recovered_amount": case.recovered_amount,
        "remaining_amount": case.remaining_amount,
        "status": case.status.value if hasattr(case.status, "value") else case.status,
        "chain": chain,
        "layer_counts": _count_layers(chain),
    }


def _classify_policy_layer(event_type: str) -> str:
    """Classify an audit event type into a decision-layer label.

    Layers used by the Inspector UI:
      trigger, ai_judgment, policy, action, outcome
    """
    from app.services.audit_logger import AuditEventType as T

    if event_type in (T.REVENUE_DETECTED, T.RISK_DETECTED):
        return "trigger"
    if event_type in (T.INTENT_DETECTED, T.AI_ERROR):
        return "ai_judgment"
    if event_type in (
        T.RECOVERY_STARTED,
        T.STRATEGY_SELECTED,
        T.ACTION_SCHEDULED,
        T.ACTION_CANCELLED,
        T.PAYMENT_PLAN_PROPOSED,
        T.PAYMENT_PLAN_ACCEPTED,
        T.INSTALLMENT_CREATED,
        T.RECOVERY_STOPPED,
        T.RECOVERY_EXPIRED,
    ):
        return "policy"
    if event_type in (
        T.MESSAGE_SENT,
        T.MESSAGE_FAILED,
        T.CUSTOMER_REPLIED,
        T.PROMISE_CREATED,
        T.INVOICE_REQUESTED,
        T.INVOICE_SENT,
        T.PAYMENT_RETRIED,
    ):
        return "action"
    if event_type in (T.INSTALLMENT_PAID, T.PAYMENT_RECOVERED, T.EXTERNAL_API_ERROR):
        return "outcome"
    # Any hard_stop events (entity_type == "hard_stop") are policy decisions
    if event_type.startswith("hard_stop"):
        return "policy"
    return "policy"


def _count_layers(chain: list[dict]) -> dict:
    counts = {}
    for node in chain:
        layer = node["layer"]
        counts[layer] = counts.get(layer, 0) + 1
    return counts


# ============================================================
# SIMULATED CUSTOMER MESSAGE / OPT-OUT TRIGGERS
# ============================================================


class SimulateMessageRequest(BaseModel):
    trigger: str  # one of: promise, stop, wrong_bill, installments, pay_link, support, language
    message: str | None = None  # optional override text
    promise_date: datetime | None = None  # for "Choose a Date" promise option


# mirror of the hard stop condition label we surface to judges
STOP_GUARDRAIL = (
    "Policy Guardrail: Opt-out detected. "
    "All automated outreach and retries halted immediately."
)


def _promote_status(case, target: RecoveryStatus) -> None:
    """Promote a case toward ENGAGED / PAYMENT_PLAN during an active dialogue.

    Inbound replies and negotiations must never exhaust the outreach attempt
    counter — instead the case moves to an engaged state as long as it has not
    already committed further (a promise or plan) and is not terminal.

    Plan creation commits the case as PROMISED (an existing invariant), so the
    explicit PAYMENT_PLAN membership still wins on the console route; any other
    committed state (PROMISED -> ENGAGED, etc.) is never regressed.
    """
    if case.status in (RecoveryStatus.AT_RISK, RecoveryStatus.RECOVERY_IN_PROGRESS):
        case.status = target
    elif target == RecoveryStatus.PAYMENT_PLAN and case.status == RecoveryStatus.PROMISED:
        case.status = target


def _detect_language_request(message: str) -> str | None:
    """Detect an explicit language-switch request from free text.

    Returns ``"hi"`` for a Hinglish/Hindi request, ``"en"`` for an English
    request, or ``None`` if the message is not about switching language.

    This lets a customer type "Hindi mein baat karein" (or "baat karein"/
    "hindi/hinglish") and the agent switches — and STAYS — in Hinglish, while
    an explicit English request switches back.
    """
    if not message:
        return None
    lower = message.strip().lower()
    want_hi = any(tok in lower for tok in ("hindi", "hinglish", "baat karein"))
    want_en_hi = "english" in lower or lower.startswith("english")
    want_en = (
        ("english" in lower)
        or ("in english" in lower)
        or lower in ("english", "talk in english", "speak english", "baat english mein")
    )
    if want_hi and not want_en_hi and not want_en:
        return "hi"
    if want_en:
        return "en"
    return None


@router.post("/{case_id}/simulate-message")
def simulate_customer_message(
    case_id: UUID,
    body: SimulateMessageRequest,
    db: Session = Depends(get_db),
):
    """Inject a synthetic customer message for demo/testing.

    Drives the full multi-turn dialogue cycle: it persists the customer's
    inbound bubble, runs the REAL bounded intent pipeline (detect_intent ->
    deterministic handling), then writes back a contextual Agent reply (with a
    structured action payload for quick-reply buttons / payment card).

    Triggers:
      - "promise"      -> PROMISE_TO_PAY        -> real Promise + reminder tomorrow
      - "stop"         -> STOP_REQUEST          -> hard stop #2 (opt-out)
      - "wrong_bill"   -> QUESTION              -> escalate to human (no hard stop)
      - "installments" -> PAYMENT_PLAN_REQUEST  -> real 2-EMI split plan
      - "pay_link"     -> PAYMENT_LINK_REQUEST  -> re-send payment link
      - "support"      -> SUPPORT               -> hand off to a human
      - "language"     -> replies in Hinglish

    Returns the resulting case status, intent, guardrail note, the contextual
    Agent reply text, and its action payload.
    """
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage
    from app.models.customer import Customer
    from app.models.recovery_case import RecoveryCase, RecoveryStatus
    from app.schemas.intent import IntentDetectionRequest
    from app.services import agent_engine, agent_flow
    from app.services.audit_logger import (
        log_customer_replied,
        log_intent_detected,
    )
    from app.services.intent_detector import detect_intent
    from sqlalchemy import select

    case = db.get(RecoveryCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    customer = db.get(Customer, case.customer_id) if case.customer_id else None

    # --- Choose the synthetic inbound message text ---
    trigger = body.trigger or "promise"
    TRIGGER_TEXT = {
        "promise": "Kal pakka karunga",
        "pay_later": "Can I pay later?",
        "promise_tomorrow": "I can pay tomorrow at 11 AM",
        "promise_3days": "I can pay in 3 days",
        "promise_custom": "I'd like to choose a promise date",
        "stop": "Stop messaging me",
        "wrong_bill": "Wrong bill amount, please check",
        "installments": "Can I pay in installments?",
        "pay_link": "Please send me the payment link",
        "support": "I need to talk to support",
        "language": "Hindi mein baat karein",
        "language_hi": "Hindi mein baat karein",
        "language_en": "Switch to English please",
        "pay_now": "I want to pay now",
        "split_2": "Can I pay in 2 installments?",
        "split_4": "Can I pay in 4 installments?",
        "split_3": "Can I pay in 3 installments?",
    }
    message_text = body.message or TRIGGER_TEXT.get(trigger, TRIGGER_TEXT["promise"])

    # Resolve a "split_<n>" trigger to its installment count.
    split_count = None
    if trigger.startswith("split_"):
        try:
            split_count = int(trigger.split("_", 1)[1])
        except (ValueError, IndexError):
            split_count = None

    invoice_id = agent_engine.invoice_id_for_case(str(case.id))
    amount = case.original_amount
    failure_reason = case.extra_data.get("failure_reason") if case.extra_data else None
    customer_name = customer.name if customer else None

    # --- Step 1: persist an inbound conversation message (if a conversation exists) ---
    conversation = (
        db.execute(
            select(Conversation)
            .where(
                Conversation.recovery_case_id == case.id,
                Conversation.channel == "whatsapp",
            )
            .order_by(Conversation.created_at.desc())
        ).scalars().first()
    )
    if conversation:
        inbound_msg = ConversationMessage(
            conversation_id=conversation.id,
            direction="inbound",
            content=message_text,
            message_type="text",
            extra_data={
                "source": "demo_simulation",
                "from_phone": customer.phone if customer else None,
                "simulated_trigger": trigger,
            },
        )
        db.add(inbound_msg)
        db.commit()
        db.refresh(inbound_msg)

        # Broadcast the inbound customer message via WebSocket so the live
        # dashboard shows the customer bubble instantly (not just after the
        # agent reply triggers an API refresh).
        from app.services.realtime import publish_message_event
        publish_message_event(
            conversation_id=str(conversation.id),
            case_id=str(case.id),
            message_id=str(inbound_msg.id),
            direction="inbound",
            content=message_text,
            message_type="text",
            created_at=inbound_msg.created_at.isoformat() if inbound_msg.created_at else "",
            extra_data=inbound_msg.extra_data,
        )

    # --- Step 2: audit the customer reply ---
    log_customer_replied(
        db,
        case.id,
        case.customer_id,
        message_text,
        language="en",
    )

    # --- Step 3: run bounded intent detection (AI w/ rule fallback) ---
    intent_request = IntentDetectionRequest(
        message=message_text,
        language="en",
        conversation_history=[],
    )
    intent_response = detect_intent(intent_request)
    detected_intent = intent_response.result.intent.value
    log_intent_detected(
        db,
        case.id,
        detected_intent,
        intent_response.result.confidence,
        intent_response.source,
        message_text,
    )

    # Broadcast typing indicator + reasoning stream to live dashboard
    from app.services.realtime import (
        publish_typing_indicator,
        publish_reasoning_stream,
    )

    publish_typing_indicator(case_id=str(case.id), is_typing=True)

    publish_reasoning_stream(
        case_id=str(case.id),
        stage="INTENT_PARSING",
        label=f"Intent: {detected_intent.replace('_', ' ').title()}",
        detail=f"Confidence: {intent_response.result.confidence:.2f}, Source: {intent_response.source}",
        confidence=intent_response.result.confidence,
        metadata={"intent": detected_intent, "source": intent_response.source, "message": message_text[:200]},
    )

    # --- Step 4: deterministic handling per intent (policy layer) ---
    guardrail_note = None
    escalated_to_human = False
    promise_scheduled = None
    split_plan = None
    recovered = False
    hard_stopped = False
    reply_intent = detected_intent
    promise_at = None
    pay_today = None
    nested_split_details = None
    # Attempt cap reached -> the merchant drives the case manually. Automation
    # (reminders) stays stopped and manual actions never re-arm it.
    monitor_mode = case.attempt_count >= case.max_attempts

    # Track the preferred language (persisted on the case) so the agent keeps
    # replying in Hinglish once the customer switches, no matter what they say.
    #
    # The customer can switch language via:
    #   - an explicit `language_<hi|en>` trigger (dedicated chip), or
    #   - free text ("Hindi mein baat karein", "baat English mein", ...).
    # An explicit switch is applied (never toggled), so repeated "Hindi mein
    # baat karein" requests stay in Hinglish and only an English request
    # reverts to English templates.
    case.extra_data = dict(case.extra_data or {})
    current_lang = case.extra_data.get("language", "en")

    if trigger.startswith("language_"):
        requested = trigger.split("_", 1)[1]
        current_lang = "hi" if requested in ("hi", "hi-en") else "en"
    else:
        text_lang = _detect_language_request(message_text)
        if text_lang is not None:
            current_lang = text_lang

    case.extra_data["language"] = current_lang
    db.commit()
    language = current_lang

    # Record whether this conversational turn was an explicit free-text language
    # switch (e.g. "Hindi mein baat karein"). Used below so the reply is routed
    # to the LANGUAGE_SWITCHED acknowledgment instead of falling through to the
    # UNCLEAR payment-link branch (which would re-spam the split card). Chip
    # triggers (language_hi/language_en/support) are handled deterministically
    # below and are excluded here.
    free_text_language_switch = bool(
        message_text and _detect_language_request(message_text) is not None
    ) and not trigger.startswith("language_")


    if trigger in ("support",):
        reply_intent = "SUPPORT"
    elif split_count and detected_intent == "PAYMENT_PLAN_REQUEST":
        reply_intent = "PAYMENT_PLAN_REQUEST"
    elif trigger == "pay_later":
        # "Pay Later" is a promise-to-pay: record a real Promise + reminder.
        detected_intent = "PROMISE_TO_PAY"
        reply_intent = "PROMISE_TO_PAY"
    elif trigger in ("promise_tomorrow", "promise_3days", "promise_custom"):
        # Contextual promise-date options from the "Can I pay later?" chips.
        # These resolve to the same verified promise pipeline; the chosen date
        # is persisted deterministically by the handling block below.
        detected_intent = "PROMISE_TO_PAY"
        reply_intent = "PROMISE_TO_PAY"
    elif trigger.startswith("language_") or free_text_language_switch:
        # Language switch (chip or free text like "Hindi mein baat karein"):
        # deterministic ack in the chosen language, no side effects (the case
        # already persisted the preference above). Free text is routed here
        # instead of falling through to the UNCLEAR/link split-card branch.
        reply_intent = "LANGUAGE_SWITCHED"

    # Block further outreach once the case is hard-stopped.
    if (
        case.status == RecoveryStatus.STOPPED
        and detected_intent != "STOP_REQUEST"
        and trigger != "stop"
    ):
        guardrail_note = (
            "Policy Guardrail: Case is HARD-STOPPED. No further outreach or "
            "retries are permitted."
        )
        reply_intent = "STOP_REQUEST"
        reply_text = agent_engine.build_reply(
            case_id=str(case.id),
            customer_name=customer_name,
            amount_paise=case.remaining_amount,
            intent="STOP_REQUEST",
            invoice_id=invoice_id,
            language=language,
        )["text"]
        agent_flow.persist_agent_reply(db, case, reply_text, None)
        return {
            "case_id": str(case.id),
            "trigger": trigger,
            "message": message_text,
            "detected_intent": detected_intent,
            "intent_source": intent_response.source,
            "intent_confidence": round(intent_response.result.confidence, 3),
            "case_status": "STOPPED",
            "hard_stopped": True,
            "guardrail_note": guardrail_note,
            "opt_out_triggered": True,
            "reply_text": reply_text,
            "agent_payload": None,
            "escalated_to_human": False,
            "promise_scheduled": None,
            "split_plan": None,
            "recovered": False,
            "recovered_amount": case.recovered_amount,
            "remaining_amount": case.remaining_amount,
            "recovery_rate": (
                round(case.recovered_amount / case.original_amount * 100, 1)
                if case.original_amount else 0
            ),
            "attempt_count": case.attempt_count,
        }

    # --- Pay Now: full verified recovery ---
    if trigger in ("pay_now", "pay_link"):
        from app.services.workflow_engine import finalize_recovered_case

        if case.remaining_amount > 0:
            finalize_recovered_case(db, case, reason="simulate_pay_now")
            from app.services.audit_logger import log_payment_recovered
            log_payment_recovered(db, case.id, case.original_amount)
            # Record a verified captured Payment row — the same ground truth a
            # ``payment.captured`` webhook would write — so the Impact Ledger /
            # Revenue Map count this as real recovered money (messages and
            # promises never count; only captured payments do). Idempotent per
            # case so repeated pay-now taps never double-count.
            from uuid import uuid4 as _uuid4

            from sqlalchemy import select

            from app.models.payment import Payment

            existing_payment = db.execute(
                select(Payment).where(Payment.recovery_case_id == case.id)
            ).scalar_one_or_none()
            if existing_payment is None:
                payment_id = f"pay_sim_{_uuid4().hex[:12]}"
                db.add(
                    Payment(
                        recovery_case_id=case.id,
                        razorpay_payment_id=payment_id,
                        razorpay_order_id=f"order_sim_{case.id.hex[:8]}",
                        amount=case.original_amount,
                        currency="INR",
                        status="captured",
                        method="simulated",
                        paid_at=datetime.now(timezone.utc),
                        extra_data={
                            "source": "simulation",
                            "channel": "whatsapp",
                            "trigger": trigger,
                        },
                    )
                )
                db.commit()
            recovered = True
            reply_intent = "PAYMENT_LINK_REQUEST"
            db.refresh(case)
        else:
            # Already fully settled — a pay request on a recovered case is just
            # a "you're all paid up" acknowledgement, never a new payment card.
            recovered = True
            reply_intent = "ALREADY_PAID"
            db.refresh(case)

    # Terminal guard: a late reply on an already-closed case must NOT spawn a
    # promise, plan, escalation or payment card. It only acknowledges the
    # closed state.
    if (
        not recovered
        and case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST)
    ):
        recovered = True
        reply_intent = (
            "ALREADY_PAID"
            if case.status == RecoveryStatus.RECOVERED
            else "STOP_REQUEST"
        )
        guardrail_note = (
            "Policy Guardrail: Case is closed. No further outreach or "
            "payment requests are permitted."
        )
        db.refresh(case)

    if not recovered:
        if detected_intent == "STOP_REQUEST":
            from app.services.hard_stop import handle_stop_intent
            handle_stop_intent(
                db,
                case.id,
                intent="STOP_REQUEST",
                customer_message=message_text,
            )
            case.extra_data = dict(case.extra_data or {})
            case.extra_data["hard_stopped"] = True
            case.extra_data["opt_out_reason"] = message_text
            db.commit()
            hard_stopped = True
            guardrail_note = STOP_GUARDRAIL
            db.refresh(case)
        elif detected_intent == "PROMISE_TO_PAY":
            from app.services.promise import create_promise_for_case

            # Deterministic promised date from the chosen option — persisted into
            # the Promise record so the UI shows the exact commitment.
            if trigger == "promise_tomorrow":
                promise_at = agent_flow.promise_date_for("tomorrow")
            elif trigger == "promise_3days":
                promise_at = agent_flow.promise_date_for("3days")
            elif trigger == "promise_custom":
                promise_at = agent_flow.promise_date_for("custom", body.promise_date)
            else:
                promise_at = None

            prom = create_promise_for_case(
                db,
                case.id,
                customer_message=message_text,
                promised_date=promise_at,
                count_attempt=not monitor_mode,
            )
            if prom.get("status") == "created":
                if monitor_mode:
                    # Attempt cap reached — merchant drives the case manually.
                    # Record the promise but NEVER queue a new automated
                    # reminder: a manual action must not restart the automatic
                    # reminder sequence.
                    promise_scheduled = {
                        "skipped": True,
                        "reason": "monitor_mode_max_attempts",
                        "promised_date": promise_at.isoformat() if promise_at else None,
                    }
                elif promise_at is not None:
                    promise_scheduled = agent_flow.schedule_reminder_tomorrow(
                        db, case.id, at=promise_at
                    )
                else:
                    promise_scheduled = agent_flow.schedule_reminder_tomorrow(db, case.id)
            db.refresh(case)
        elif detected_intent == "PAYMENT_PLAN_REQUEST":
            count = split_count or 2
            # Rule 2 (nested installments): a free-text "I want to pay Part 1
            # (₹499) now in 2 installments" picks a specific part of an existing
            # plan and re-splits it into a new, smaller breakdown. Paranoid that
            # free text never renders the full-balance UNCLEAR card.
            nested = (
                agent_engine.parse_nested_split(message_text)
                if split_count is None
                else None
            )
            if nested:
                part_amount = nested["amount_paise"]
                part_count = nested["count"]
                amounts = agent_engine.calculate_installments(part_amount, part_count)
                pay_today = amounts[0]
                nested_split_details = agent_engine.split_plan_payload(
                    part_amount, count=part_count
                )
                split_count = part_count
                reply_intent = "PAYMENT_PLAN_REQUEST"
                _promote_status(case, RecoveryStatus.PAYMENT_PLAN)
                db.commit()
                db.refresh(case)

                # Broadcast the sub-split plan update to live dashboards
                from app.services.realtime import (
                    publish_payment_plan_updated,
                    publish_plan_modification,
                    publish_case_state_updated,
                )
                nested_plan_payload = agent_engine._build_payment_plan_payload(
                    total_amount_paise=part_amount,
                    count=part_count,
                    case_id=str(case.id),
                )
                publish_payment_plan_updated(
                    case_id=str(case.id),
                    plan=nested_plan_payload,
                    installment_breakdown=nested_split_details,
                    policy_action={
                        "increment_attempt_counter": False,
                        "next_state": "PAYMENT_PLAN_PENDING",
                    },
                    action="sub_split",
                )
                publish_plan_modification(
                    case_id=str(case.id),
                    new_count=part_count,
                    modification_type="sub_split",
                    customer_message=message_text,
                )
                publish_case_state_updated(
                    case_id=str(case.id),
                    new_status="PAYMENT_PLAN",
                    remaining_amount=case.remaining_amount,
                )

                # Analytics: log the sub-split event
                from app.services.audit_logger import (
                    log_sub_split_created,
                    log_negotiation_pattern,
                )
                from app.services.agent_engine import assess_sentiment

                sentiment = assess_sentiment(message_text)
                log_sub_split_created(
                    db,
                    case.id,
                    part_number=nested["part"],
                    part_amount=part_amount,
                    sub_split_count=part_count,
                    parent_count=2,  # Default parent count
                    total_amount=case.original_amount,
                    customer_message=message_text,
                )
                # Track negotiation pattern for sub-splits
                log_negotiation_pattern(
                    db,
                    case.id,
                    pattern_type="sub_split",
                    total_negotiation_turns=case.attempt_count + 1,
                    plan_changes=1,
                    final_count=part_count,
                    sentiment_history=[sentiment],
                    outcome="ongoing",
                )
            else:
                split_plan = agent_flow.create_split_plan(
                    db, case, split_count=count, days_apart=15
                )
                reply_intent = "PAYMENT_PLAN_REQUEST"
                # Rule 1 (dynamic amount): the payment card must carry the exact
                # installment due today, never the full remaining balance.
                pay_today = (split_plan or {}).get("amounts", [None])[0]
                _promote_status(case, RecoveryStatus.PAYMENT_PLAN)
                # create_split_plan commits the case as PROMISED; the plan state
                # must win, so persist the promotion before refreshing.
                db.commit()
                db.refresh(case)
        elif detected_intent in ("QUESTION", "INVOICE_REQUEST") or trigger == "wrong_bill":
            # Wrong-bill / dispute -> escalate to human, pause follow-ups.
            escalated_to_human = True
            reply_intent = "QUESTION"
            case.extra_data = dict(case.extra_data or {})
            case.extra_data["escalated_to_human"] = True
            case.extra_data["escalation_reason"] = message_text
            _promote_status(case, RecoveryStatus.ENGAGED)
            db.commit()
            db.refresh(case)
        else:
            # SUPPORT / link / retry / unclear / informational turns are active
            # negotiation: engage the case without consuming an outreach attempt.
            wordy_intents = (
                "SUPPORT",
                "PAYMENT_LINK_REQUEST",
                "PAYMENT_RETRY_REQUEST",
                "UNCLEAR",
                "INVOICE_REQUEST",
            )
            if reply_intent in wordy_intents or reply_intent == detected_intent:
                _promote_status(case, RecoveryStatus.ENGAGED)
                db.commit()
            db.refresh(case)

    # NOTE: inbound replies / active negotiations intentionally do NOT increment
    # the outreach attempt counter. Attempts advance only via real outbound
    # outreach (record_attempt in the orchestrator / scheduler) and recorded
    # promises — engagement instead promotes the case to ENGAGED / PAYMENT_PLAN.

    # --- Gather recent inbound history so repeated queries are acknowledged ---
    # The just-persisted inbound message is EXCLUDED: acknowledgements must
    # reflect PRIOR turns, otherwise even the first "Can I pay later?" counts as
    # a repeat and the engine loops on "As mentioned earlier" instead of
    # acknowledging and offering the promise-date options.
    history = []
    if conversation:
        recent_msgs = db.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.id != inbound_msg.id,
            )
            .order_by(ConversationMessage.created_at.desc())
            .limit(6)
        ).scalars().all()
        from app.services.intent_detector import detect_intent as _di
        from app.schemas.intent import IntentDetectionRequest as _IDR
        for m in recent_msgs:
            if m.direction == "inbound":
                try:
                    intent_ev = _di(_IDR(message=m.content, language=language)).result.intent.value
                    history.append(intent_ev)
                except Exception:
                    history.append(m.content or "")
        history = list(reversed(history))
    else:
        history = []

    # --- Stream policy evaluation + diagnostic reasoning ---
    remaining = case.remaining_amount
    attempt_str = f"{case.attempt_count}/{case.max_attempts}"
    publish_reasoning_stream(
        case_id=str(case.id),
        stage="POLICY_EVALUATION",
        label=f"Attempt {attempt_str} · Remaining ₹{remaining // 100}",
        detail=f"Active attempt {attempt_str} -> response dispatched",
        confidence=0.95,
        metadata={"attempt_count": case.attempt_count, "remaining": remaining},
    )
    status_val = case.status.value if hasattr(case.status, "value") else str(case.status)
    publish_reasoning_stream(
        case_id=str(case.id),
        stage="DIAGNOSTIC_SYNC",
        label=f"State: {status_val.replace('_', ' ').title()}",
        detail=f"Updated state: {status_val}, Remaining: ₹{remaining // 100}",
        confidence=0.98,
        metadata={"status": status_val},
    )

    # Clear typing indicator before building reply
    publish_typing_indicator(case_id=str(case.id), is_typing=False)

    # --- Step 5: build & persist the contextual Agent reply with action payload ---
    agent_payload = agent_engine.build_reply(
        case_id=str(case.id),
        customer_name=customer_name,
        amount_paise=case.remaining_amount,
        intent=reply_intent,
        invoice_id=invoice_id,
        language=language,
        split_details=(nested_split_details or (split_plan or {}).get("split")),
        split_count=split_count,
        pay_today=pay_today if reply_intent == "PAYMENT_PLAN_REQUEST" else None,
        customer_message=message_text,
        escalate_note=("Our billing desk has been notified. A revised "
                       "breakdown is on its way to your email.") if escalated_to_human else None,
        history=history,
        promise_at=promise_at,
        monitor_mode=monitor_mode,
    )
    reply_text = agent_payload["text"]
    agent_flow.persist_agent_reply(db, case, reply_text, agent_payload)

    return {
        "case_id": str(case.id),
        "trigger": trigger,
        "message": message_text,
        "detected_intent": detected_intent,
        "intent_source": intent_response.source,
        "intent_confidence": round(intent_response.result.confidence, 3),
        "case_status": (
            case.status.value if hasattr(case.status, "value") else case.status
        ),
        "guardrail_note": guardrail_note,
        "opt_out_triggered": detected_intent in ("STOP_REQUEST", "NEGATIVE") or hard_stopped,
        "reply_text": reply_text,
        "agent_payload": agent_payload,
        "escalated_to_human": escalated_to_human,
        "promise_scheduled": promise_scheduled,
        "split_plan": split_plan,
        "language": language,
        "recovered": recovered,
        "hard_stopped": hard_stopped,
        "recovered_amount": case.recovered_amount,
        "remaining_amount": case.remaining_amount,
        "recovery_rate": (
            round(case.recovered_amount / case.original_amount * 100, 1)
            if case.original_amount else 0
        ),
        "attempt_count": case.attempt_count,
    }


# ============================================================
# INITIAL AGENT TRIGGER + SYNCHRONIZED EMAIL THREAD
# ============================================================


@router.post("/{case_id}/agent-initial")
def generate_agent_initial(
    case_id: UUID,
    db: Session = Depends(get_db),
):
    """Build the contextual first-touch Agent message for a case.

    Returns the rendered outbound payload (quick replies + payment card) and,
    if a customer email exists, generates the matching synchronized
    transactional email (Emails tab). Idempotent: does not duplicate the
    trigger bubble.
    """
    from app.models.customer import Customer
    from app.models.recovery_case import RecoveryCase
    from app.services import agent_engine, agent_flow
    from sqlalchemy import select

    case = db.get(RecoveryCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    customer = db.get(Customer, case.customer_id) if case.customer_id else None
    invoice_id = agent_engine.invoice_id_for_case(str(case.id))
    failure_reason = case.extra_data.get("failure_reason") if case.extra_data else None

    payload = agent_engine.build_initial_outbound(
        case_id=str(case.id),
        customer_name=customer.name if customer else None,
        amount_paise=case.original_amount,
        failure_reason=failure_reason,
        invoice_id=invoice_id,
    )

    # Persist the trigger bubble only if the thread is empty.
    from app.models.conversation import Conversation
    conversation = (
        db.execute(
            select(Conversation)
            .where(
                Conversation.recovery_case_id == case.id,
                Conversation.channel == "whatsapp",
            )
        ).scalars().first()
    )
    already_sent = False
    if conversation is None:
        agent_flow.persist_agent_reply(db, case, payload["text"], payload)
    else:
        already_sent = True

    email = _generate_matching_email(db, case, customer, invoice_id)

    return {
        "case_id": str(case.id),
        "message": payload["text"],
        "agent_payload": payload,
        "already_sent": already_sent,
        "email": email,
    }


@router.post("/{case_id}/generate-email")
def generate_case_email(
    case_id: UUID,
    db: Session = Depends(get_db),
):
    """Generate the synchronized transactional email for a case (Emails tab).

    Also persists the version tag so the tab always shows the matching thread.
    """
    from app.models.customer import Customer
    from app.models.recovery_case import RecoveryCase
    from app.services import agent_engine

    case = db.get(RecoveryCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    customer = db.get(Customer, case.customer_id) if case.customer_id else None
    invoice_id = agent_engine.invoice_id_for_case(str(case.id))
    email = _generate_matching_email(db, case, customer, invoice_id)
    return {"case_id": str(case.id), "email": email}


def _generate_matching_email(db, case, customer, invoice_id: str) -> dict | None:
    """Create (once) the matching HTML transaction email and return its summary.

    Only creates the record when a customer email address is known, so the
    Emails tab shows a real synchronized thread.
    """
    from app.crud.email import create_sent_email
    from app.models.email import EmailType
    from app.schemas.email import SentEmailCreate
    from app.services import agent_engine
    from sqlalchemy import select

    recipient = customer.email if customer else None
    if not recipient:
        return None

    from app.models.email import SentEmail
    exists = (
        db.execute(
            select(SentEmail).where(
                SentEmail.recipient_email == recipient,
                SentEmail.email_type == EmailType.FAILED_PAYMENT.value,
            )
        ).scalars().first()
    )
    if exists:
        return {
            "id": str(exists.id),
            "email_type": exists.email_type,
            "subject": exists.subject,
            "recipient_email": exists.recipient_email,
            "delivery_status": exists.delivery_status,
        }

    failure_reason = case.extra_data.get("failure_reason") if case.extra_data else None
    subject = agent_engine.build_email_subject(case.original_amount, invoice_id)
    html_body = agent_engine.render_payment_failed_email_html(
        customer_name=customer.name if customer else None,
        amount_paise=case.original_amount,
        invoice_id=invoice_id,
        case_id=str(case.id),
        failure_reason=failure_reason,
    )

    email = create_sent_email(
        db,
        data=SentEmailCreate(
            recovery_case_id=case.id,
            recipient_email=recipient,
            subject=subject,
            body=html_body,
            email_type=EmailType.FAILED_PAYMENT.value,
        ),
    )
    return {
        "id": str(email.id),
        "email_type": email.email_type,
        "subject": email.subject,
        "recipient_email": email.recipient_email,
        "delivery_status": email.delivery_status,
    }
