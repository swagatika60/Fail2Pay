"""Case Detail API endpoints.

Provides detailed data for a recovery case:
- Promise timeline
- Payment plan with installments
- Conversation messages
- Email history
- Hard stop / audit log
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cases", tags=["case-detail"])


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


@router.get("/{case_id}/timeline")
def get_case_timeline(case_id: UUID, db: Session = Depends(get_db)):
    """Get the full recovery timeline for a case.

    Returns all audit events sorted chronologically with
    human-readable descriptions — a judge should be able to
    understand exactly what happened, when, why, and what the system did.
    """
    from app.services.audit_logger import get_recovery_timeline
    return get_recovery_timeline(db, case_id)


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


# mirror of the hard stop condition label we surface to judges
STOP_GUARDRAIL = (
    "Policy Guardrail: Opt-out detected. "
    "All automated outreach and retries halted immediately."
)


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
        "stop": "Stop messaging me",
        "wrong_bill": "Wrong bill amount, please check",
        "installments": "Can I pay in installments?",
        "pay_link": "Please send me the payment link",
        "support": "I need to talk to support",
        "language": "Hindi mein baat karein",
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
        db.add(
            ConversationMessage(
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
        )
        db.commit()

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

    # --- Step 4: deterministic handling per intent (policy layer) ---
    guardrail_note = None
    escalated_to_human = False
    promise_scheduled = None
    split_plan = None
    recovered = False
    hard_stopped = False
    reply_intent = detected_intent

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

    if trigger in ("support",):
        reply_intent = "SUPPORT"
    elif split_count and detected_intent == "PAYMENT_PLAN_REQUEST":
        reply_intent = "PAYMENT_PLAN_REQUEST"

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
        from app.crud.scheduled_action import cancel_pending_actions_for_case

        if case.remaining_amount > 0:
            from datetime import datetime, timezone as _tz
            case.recovered_amount = case.original_amount
            case.remaining_amount = 0
            case.status = RecoveryStatus.RECOVERED
            case.closed_at = datetime.now(_tz.utc)
            db.commit()
            cancel_pending_actions_for_case(
                db, case.id, reason="payment_recovered"
            )
            from app.services.audit_logger import log_payment_recovered
            log_payment_recovered(db, case.id, case.original_amount)
            recovered = True
            reply_intent = "PAYMENT_LINK_REQUEST"
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
            create_promise_for_case(db, case.id, customer_message=message_text)
            promise_scheduled = agent_flow.schedule_reminder_tomorrow(db, case.id)
            db.refresh(case)
        elif detected_intent == "PAYMENT_PLAN_REQUEST":
            count = split_count or 2
            split_plan = agent_flow.create_split_plan(db, case, split_count=count, days_apart=15)
            reply_intent = "PAYMENT_PLAN_REQUEST"
            db.refresh(case)
            amount = case.original_amount
        elif detected_intent in ("QUESTION", "INVOICE_REQUEST") or trigger == "wrong_bill":
            # Wrong-bill / dispute -> escalate to human, pause follow-ups.
            escalated_to_human = True
            reply_intent = "QUESTION"
            case.extra_data = dict(case.extra_data or {})
            case.extra_data["escalated_to_human"] = True
            case.extra_data["escalation_reason"] = message_text
            case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
            db.commit()
            db.refresh(case)
        else:
            db.commit()
            db.refresh(case)

    # --- Track attempts (outreach turns), unless terminal or language switch ---
    # PROMISE_TO_PAY already counts an attempt via workflow_engine.record_attempt,
    # so skip the manual increment there to avoid double counting.
    if (
        trigger != "language"
        and detected_intent != "PROMISE_TO_PAY"
        and case.status not in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST)
        and not recovered
    ):
        if case.attempt_count < case.max_attempts:
            case.attempt_count += 1
            db.commit()
            db.refresh(case)

    # --- Gather recent inbound history so repeated queries are acknowledged ---
    history = []
    if conversation:
        recent_msgs = db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
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

    # --- Step 5: build & persist the contextual Agent reply with action payload ---
    agent_payload = agent_engine.build_reply(
        case_id=str(case.id),
        customer_name=customer_name,
        amount_paise=case.remaining_amount if recovered else amount,
        intent=reply_intent,
        invoice_id=invoice_id,
        language=language,
        split_details=(split_plan or {}).get("split"),
        split_count=split_count,
        escalate_note=("Our billing desk has been notified. A revised "
                       "breakdown is on its way to your email.") if escalated_to_human else None,
        history=history,
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
