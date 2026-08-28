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
    trigger: str  # one of: promise, stop, wrong_bill
    message: str | None = None  # optional override text


# mirror of the hard stop condition label we surface to judges
STOP_GUARDRAIL = (
    "Policy Guardrail: Opt-out detected. "
    "All automated outreach and retries halted immediately."
)


@router.post("/{case_id}/simulate-message")
def simulate_customer_message(
    case_id: UUID,
    body: SimulateMessageRequest,
    db: Session = Depends(get_db),
):
    """Inject a synthetic customer message for demo/testing.

    Reuses the REAL intent pipeline (detect_intent -> bounded handling) so
    the demo reflects production behavior, including hard-stop enforcement:

      - "promise"    -> PROMISE_TO_PAY  -> creates a real Promise, case -> PROMISED
      - "stop"       -> STOP_REQUEST    -> hard stop #2: case -> STOPPED, cancels
                                           all scheduled actions + active promise
      - "wrong_bill" -> QUESTION        -> records reply + audit; NO hard stop

    Returns the resulting case status, detected intent, and a policy-guardrail
    note when the customer opted out.
    """
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage
    from app.models.customer import Customer
    from app.models.recovery_case import RecoveryCase
    from app.schemas.intent import IntentDetectionRequest
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

    # --- Choose the synthetic inbound message text + expected intent ---
    trigger = body.trigger or "promise"
    TRIGGER_TEXT = {
        "promise": "Kal pakka karunga",
        "stop": "Stop messaging me",
        "wrong_bill": "Wrong bill amount, please check",
    }
    message_text = body.message or TRIGGER_TEXT.get(trigger, TRIGGER_TEXT["promise"])

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
    if detected_intent == "STOP_REQUEST":
        from app.services.hard_stop import handle_stop_intent
        hs = handle_stop_intent(
            db,
            case.id,
            intent="STOP_REQUEST",
            customer_message=message_text,
        )
        guardrail_note = STOP_GUARDRAIL
        db.refresh(case)
    elif detected_intent == "PROMISE_TO_PAY":
        from app.services.promise import create_promise_for_case
        promise_result = create_promise_for_case(
            db,
            case.id,
            customer_message=message_text,
        )
        db.refresh(case)
    else:
        # QUESTION / other: record an audit note, keep recovery running
        db.commit()
        db.refresh(case)

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
        "opt_out_triggered": detected_intent in ("STOP_REQUEST", "NEGATIVE"),
    }
