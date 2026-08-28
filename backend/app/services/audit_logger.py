"""Centralized Audit Logging Service.

Every recovery event is logged. A judge should be able to open one case
and understand exactly:
- What happened
- When it happened
- Why it happened
- What the system did
- How much money was recovered

23 Event Types:
REVENUE_DETECTED, RISK_DETECTED, RECOVERY_STARTED, STRATEGY_SELECTED,
ACTION_SCHEDULED, ACTION_CANCELLED, MESSAGE_SENT, MESSAGE_FAILED,
CUSTOMER_REPLIED, INTENT_DETECTED, PROMISE_CREATED, PAYMENT_PLAN_PROPOSED,
PAYMENT_PLAN_ACCEPTED, INSTALLMENT_CREATED, INSTALLMENT_PAID,
INVOICE_REQUESTED, INVOICE_SENT, PAYMENT_RETRIED, PAYMENT_RECOVERED,
RECOVERY_STOPPED, RECOVERY_EXPIRED, AI_ERROR, EXTERNAL_API_ERROR
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ============================================================
# EVENT TYPE CONSTANTS
# ============================================================


class AuditEventType:
    REVENUE_DETECTED = "REVENUE_DETECTED"
    RISK_DETECTED = "RISK_DETECTED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    STRATEGY_SELECTED = "STRATEGY_SELECTED"
    ACTION_SCHEDULED = "ACTION_SCHEDULED"
    ACTION_CANCELLED = "ACTION_CANCELLED"
    MESSAGE_SENT = "MESSAGE_SENT"
    MESSAGE_FAILED = "MESSAGE_FAILED"
    CUSTOMER_REPLIED = "CUSTOMER_REPLIED"
    INTENT_DETECTED = "INTENT_DETECTED"
    PROMISE_CREATED = "PROMISE_CREATED"
    PAYMENT_PLAN_PROPOSED = "PAYMENT_PLAN_PROPOSED"
    PAYMENT_PLAN_ACCEPTED = "PAYMENT_PLAN_ACCEPTED"
    INSTALLMENT_CREATED = "INSTALLMENT_CREATED"
    INSTALLMENT_PAID = "INSTALLMENT_PAID"
    INVOICE_REQUESTED = "INVOICE_REQUESTED"
    INVOICE_SENT = "INVOICE_SENT"
    PAYMENT_RETRIED = "PAYMENT_RETRIED"
    PAYMENT_RECOVERED = "PAYMENT_RECOVERED"
    RECOVERY_STOPPED = "RECOVERY_STOPPED"
    RECOVERY_EXPIRED = "RECOVERY_EXPIRED"
    AI_ERROR = "AI_ERROR"
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"


# Event type → human-readable description
EVENT_DESCRIPTIONS = {
    AuditEventType.REVENUE_DETECTED: "Failed payment detected",
    AuditEventType.RISK_DETECTED: "Revenue risk assessed",
    AuditEventType.RECOVERY_STARTED: "Recovery workflow initiated",
    AuditEventType.STRATEGY_SELECTED: "Recovery strategy selected",
    AuditEventType.ACTION_SCHEDULED: "Recovery action scheduled",
    AuditEventType.ACTION_CANCELLED: "Scheduled action cancelled",
    AuditEventType.MESSAGE_SENT: "Message sent to customer",
    AuditEventType.MESSAGE_FAILED: "Message delivery failed",
    AuditEventType.CUSTOMER_REPLIED: "Customer responded",
    AuditEventType.INTENT_DETECTED: "Customer intent classified",
    AuditEventType.PROMISE_CREATED: "Customer made a promise to pay",
    AuditEventType.PAYMENT_PLAN_PROPOSED: "Payment plan proposed",
    AuditEventType.PAYMENT_PLAN_ACCEPTED: "Payment plan accepted by customer",
    AuditEventType.INSTALLMENT_CREATED: "Installment record created",
    AuditEventType.INSTALLMENT_PAID: "Installment payment received",
    AuditEventType.INVOICE_REQUESTED: "Customer requested invoice",
    AuditEventType.INVOICE_SENT: "Invoice delivered to customer",
    AuditEventType.PAYMENT_RETRIED: "Payment retry initiated",
    AuditEventType.PAYMENT_RECOVERED: "Payment successfully recovered",
    AuditEventType.RECOVERY_STOPPED: "Recovery workflow stopped",
    AuditEventType.RECOVERY_EXPIRED: "Recovery deadline expired",
    AuditEventType.AI_ERROR: "AI service error",
    AuditEventType.EXTERNAL_API_ERROR: "External API error",
}


# Event type → icon for timeline UI
EVENT_ICONS = {
    AuditEventType.REVENUE_DETECTED: "💰",
    AuditEventType.RISK_DETECTED: "⚠️",
    AuditEventType.RECOVERY_STARTED: "🔄",
    AuditEventType.STRATEGY_SELECTED: "🎯",
    AuditEventType.ACTION_SCHEDULED: "📅",
    AuditEventType.ACTION_CANCELLED: "❌",
    AuditEventType.MESSAGE_SENT: "📤",
    AuditEventType.MESSAGE_FAILED: "⚠️",
    AuditEventType.CUSTOMER_REPLIED: "📥",
    AuditEventType.INTENT_DETECTED: "🧠",
    AuditEventType.PROMISE_CREATED: "🤝",
    AuditEventType.PAYMENT_PLAN_PROPOSED: "📋",
    AuditEventType.PAYMENT_PLAN_ACCEPTED: "✅",
    AuditEventType.INSTALLMENT_CREATED: "📝",
    AuditEventType.INSTALLMENT_PAID: "💵",
    AuditEventType.INVOICE_REQUESTED: "📄",
    AuditEventType.INVOICE_SENT: "📨",
    AuditEventType.PAYMENT_RETRIED: "🔄",
    AuditEventType.PAYMENT_RECOVERED: "🎉",
    AuditEventType.RECOVERY_STOPPED: "🛑",
    AuditEventType.RECOVERY_EXPIRED: "⏰",
    AuditEventType.AI_ERROR: "🤖",
    AuditEventType.EXTERNAL_API_ERROR: "🔌",
}


# Event type → color for timeline UI
EVENT_COLORS = {
    AuditEventType.REVENUE_DETECTED: "red",
    AuditEventType.RISK_DETECTED: "amber",
    AuditEventType.RECOVERY_STARTED: "blue",
    AuditEventType.STRATEGY_SELECTED: "indigo",
    AuditEventType.ACTION_SCHEDULED: "slate",
    AuditEventType.ACTION_CANCELLED: "gray",
    AuditEventType.MESSAGE_SENT: "green",
    AuditEventType.MESSAGE_FAILED: "red",
    AuditEventType.CUSTOMER_REPLIED: "cyan",
    AuditEventType.INTENT_DETECTED: "purple",
    AuditEventType.PROMISE_CREATED: "blue",
    AuditEventType.PAYMENT_PLAN_PROPOSED: "indigo",
    AuditEventType.PAYMENT_PLAN_ACCEPTED: "green",
    AuditEventType.INSTALLMENT_CREATED: "slate",
    AuditEventType.INSTALLMENT_PAID: "green",
    AuditEventType.INVOICE_REQUESTED: "slate",
    AuditEventType.INVOICE_SENT: "blue",
    AuditEventType.PAYMENT_RETRIED: "amber",
    AuditEventType.PAYMENT_RECOVERED: "green",
    AuditEventType.RECOVERY_STOPPED: "red",
    AuditEventType.RECOVERY_EXPIRED: "gray",
    AuditEventType.AI_ERROR: "red",
    AuditEventType.EXTERNAL_API_ERROR: "red",
}


# ============================================================
# CORE LOGGING FUNCTION
# ============================================================


def log_audit_event(
    db: Session,
    event_type: str,
    recovery_case_id: uuid.UUID | str,
    entity_type: str = "recovery_case",
    entity_id: uuid.UUID | str | None = None,
    result: str = "success",
    reason: str = "",
    metadata: dict | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    customer_id: uuid.UUID | str | None = None,
    amount: int | None = None,
) -> dict:
    """Log a centralized audit event.

    This is the SINGLE entry point for all audit logging.
    Every event contains: timestamp, entity, recovery case,
    customer, event type, result, reason, metadata.

    Args:
        db: Database session
        event_type: One of AuditEventType constants
        recovery_case_id: UUID of the recovery case
        entity_type: Type of entity (recovery_case, payment_plan, etc.)
        entity_id: UUID of the specific entity
        result: "success", "failure", "skipped", "blocked"
        reason: Human-readable reason
        metadata: Additional context
        old_value: Previous state (for state changes)
        new_value: New state (for state changes)
        customer_id: UUID of the customer
        amount: Amount in paise (for financial events)

    Returns:
        dict with the logged event details
    """
    if entity_id is None:
        entity_id = recovery_case_id

    # Build comprehensive metadata
    full_metadata = {
        "event_type": event_type,
        "description": EVENT_DESCRIPTIONS.get(event_type, event_type),
        "result": result,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if customer_id:
        full_metadata["customer_id"] = str(customer_id)
    if amount is not None:
        full_metadata["amount"] = amount
        full_metadata["amount_formatted"] = _format_amount(amount)
    if metadata:
        full_metadata.update(metadata)

    # Create the audit event
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate

    try:
        case_uuid = uuid.UUID(str(recovery_case_id)) if not isinstance(recovery_case_id, uuid.UUID) else recovery_case_id
        entity_uuid = uuid.UUID(str(entity_id)) if not isinstance(entity_id, uuid.UUID) else entity_id

        audit = create_audit_event(
            db,
            data=AuditEventCreate(
                recovery_case_id=case_uuid,
                entity_type=entity_type,
                entity_id=entity_uuid,
                action=event_type,
                old_value=old_value,
                new_value=new_value,
                extra_data=full_metadata,
            ),
        )

        logger.info(
            "Audit: %s | case=%s | result=%s | %s",
            event_type, str(recovery_case_id)[:8], result, reason,
        )

        return {
            "id": str(audit.id),
            "event_type": event_type,
            "timestamp": full_metadata["timestamp"],
            "result": result,
        }

    except Exception as e:
        logger.error("Failed to create audit event: %s", str(e))
        return {"error": str(e)}


# ============================================================
# CONVENIENCE FUNCTIONS (one per event type)
# ============================================================


def log_revenue_detected(db, case_id, amount, payment_id, failure_reason):
    return log_audit_event(
        db, AuditEventType.REVENUE_DETECTED, case_id,
        result="detected",
        reason=f"Payment {payment_id} failed: {failure_reason}",
        amount=amount,
        metadata={"payment_id": payment_id, "failure_reason": failure_reason},
    )


def log_risk_detected(db, case_id, risk_level, risk_reason, amount):
    return log_audit_event(
        db, AuditEventType.RISK_DETECTED, case_id,
        result=risk_level.lower(),
        reason=risk_reason,
        amount=amount,
        metadata={"risk_level": risk_level},
    )


def log_recovery_started(db, case_id, strategy="default"):
    return log_audit_event(
        db, AuditEventType.RECOVERY_STARTED, case_id,
        result="started",
        reason=f"Recovery workflow initiated with strategy: {strategy}",
        metadata={"strategy": strategy},
    )


def log_strategy_selected(db, case_id, strategy, reason=""):
    return log_audit_event(
        db, AuditEventType.STRATEGY_SELECTED, case_id,
        result="selected",
        reason=reason or f"Strategy: {strategy}",
        metadata={"strategy": strategy},
    )


def log_action_scheduled(db, case_id, action_type, channel, scheduled_for):
    return log_audit_event(
        db, AuditEventType.ACTION_SCHEDULED, case_id,
        result="scheduled",
        reason=f"Scheduled {action_type} via {channel}",
        metadata={
            "action_type": action_type,
            "channel": channel,
            "scheduled_for": scheduled_for,
        },
    )


def log_action_cancelled(db, case_id, action_type, reason="cancelled"):
    return log_audit_event(
        db, AuditEventType.ACTION_CANCELLED, case_id,
        result="cancelled",
        reason=reason,
        metadata={"action_type": action_type},
    )


def log_message_sent(db, case_id, channel, message_type="text", language="en"):
    return log_audit_event(
        db, AuditEventType.MESSAGE_SENT, case_id,
        result="sent",
        reason=f"Message sent via {channel}",
        metadata={
            "channel": channel,
            "message_type": message_type,
            "language": language,
        },
    )


def log_message_failed(db, case_id, channel, error, is_transient=True):
    return log_audit_event(
        db, AuditEventType.MESSAGE_FAILED, case_id,
        result="failed",
        reason=f"Message delivery failed: {error}",
        metadata={
            "channel": channel,
            "error": str(error)[:500],
            "is_transient": is_transient,
        },
    )


def log_customer_replied(db, case_id, customer_id, message, language="en"):
    return log_audit_event(
        db, AuditEventType.CUSTOMER_REPLIED, case_id,
        result="received",
        reason="Customer sent a message",
        customer_id=customer_id,
        metadata={
            "message": message[:500],
            "language": language,
        },
    )


def log_intent_detected(db, case_id, intent, confidence, source, message=""):
    return log_audit_event(
        db, AuditEventType.INTENT_DETECTED, case_id,
        result=intent,
        reason=f"Intent: {intent} (confidence: {confidence:.2f}, source: {source})",
        metadata={
            "intent": intent,
            "confidence": confidence,
            "source": source,
            "message": message[:500],
        },
    )


def log_promise_created(db, case_id, customer_id, amount, promised_date):
    return log_audit_event(
        db, AuditEventType.PROMISE_CREATED, case_id,
        result="created",
        reason=f"Customer promised to pay {_format_amount(amount)} by {promised_date}",
        customer_id=customer_id,
        amount=amount,
        metadata={"promised_date": str(promised_date)},
    )


def log_payment_plan_proposed(db, case_id, plan_id, total, installments, frequency):
    return log_audit_event(
        db, AuditEventType.PAYMENT_PLAN_PROPOSED, case_id,
        entity_type="payment_plan",
        entity_id=plan_id,
        result="proposed",
        reason=f"Payment plan: {installments}× {_format_amount(total // installments)} {frequency}",
        amount=total,
        metadata={
            "plan_id": str(plan_id),
            "installments": installments,
            "frequency": frequency,
        },
    )


def log_payment_plan_accepted(db, case_id, plan_id, total):
    return log_audit_event(
        db, AuditEventType.PAYMENT_PLAN_ACCEPTED, case_id,
        entity_type="payment_plan",
        entity_id=plan_id,
        result="accepted",
        reason=f"Payment plan accepted for {_format_amount(total)}",
        amount=total,
        metadata={"plan_id": str(plan_id)},
    )


def log_installment_created(db, case_id, plan_id, installment_number, amount, due_date):
    return log_audit_event(
        db, AuditEventType.INSTALLMENT_CREATED, case_id,
        entity_type="installment",
        entity_id=plan_id,
        result="created",
        reason=f"Installment #{installment_number}: {_format_amount(amount)} due {due_date}",
        amount=amount,
        metadata={
            "plan_id": str(plan_id),
            "installment_number": installment_number,
            "due_date": str(due_date),
        },
    )


def log_installment_paid(db, case_id, installment_id, amount, installment_number):
    return log_audit_event(
        db, AuditEventType.INSTALLMENT_PAID, case_id,
        entity_type="installment",
        entity_id=installment_id,
        result="paid",
        reason=f"Installment #{installment_number} paid: {_format_amount(amount)}",
        amount=amount,
        metadata={
            "installment_id": str(installment_id),
            "installment_number": installment_number,
        },
    )


def log_invoice_requested(db, case_id, customer_id):
    return log_audit_event(
        db, AuditEventType.INVOICE_REQUESTED, case_id,
        result="requested",
        reason="Customer requested invoice",
        customer_id=customer_id,
    )


def log_invoice_sent(db, case_id, invoice_id, channel):
    return log_audit_event(
        db, AuditEventType.INVOICE_SENT, case_id,
        entity_type="invoice",
        entity_id=invoice_id,
        result="sent",
        reason=f"Invoice sent via {channel}",
        metadata={"channel": channel},
    )


def log_payment_retried(db, case_id, amount, payment_link):
    return log_audit_event(
        db, AuditEventType.PAYMENT_RETRIED, case_id,
        result="initiated",
        reason=f"Payment retry initiated for {_format_amount(amount)}",
        amount=amount,
        metadata={"payment_link": payment_link},
    )


def log_payment_recovered(db, case_id, amount, payment_id=""):
    return log_audit_event(
        db, AuditEventType.PAYMENT_RECOVERED, case_id,
        result="recovered",
        reason=f"Payment of {_format_amount(amount)} successfully recovered",
        amount=amount,
        metadata={"payment_id": payment_id},
    )


def log_recovery_stopped(db, case_id, reason="customer_requested"):
    return log_audit_event(
        db, AuditEventType.RECOVERY_STOPPED, case_id,
        result="stopped",
        reason=f"Recovery stopped: {reason}",
        metadata={"stop_reason": reason},
    )


def log_recovery_expired(db, case_id, deadline):
    return log_audit_event(
        db, AuditEventType.RECOVERY_EXPIRED, case_id,
        result="expired",
        reason=f"Recovery deadline {deadline} has passed",
        metadata={"deadline": str(deadline)},
    )


def log_ai_error(db, case_id, error, operation="intent_detection"):
    return log_audit_event(
        db, AuditEventType.AI_ERROR, case_id,
        result="error",
        reason=f"AI error during {operation}: {str(error)[:200]}",
        metadata={
            "operation": operation,
            "error": str(error)[:500],
        },
    )


def log_external_api_error(db, case_id, api_name, error, operation=""):
    return log_audit_event(
        db, AuditEventType.EXTERNAL_API_ERROR, case_id,
        result="error",
        reason=f"{api_name} API error: {str(error)[:200]}",
        metadata={
            "api_name": api_name,
            "operation": operation,
            "error": str(error)[:500],
        },
    )


# ============================================================
# TIMELINE QUERY
# ============================================================


def get_recovery_timeline(db, case_id) -> list[dict]:
    """Get the full recovery timeline for a case.

    Returns all audit events sorted chronologically, with
    human-readable descriptions and metadata.
    """
    from app.models.audit_event import AuditEvent
    from app.models.customer import Customer
    from app.models.recovery_case import RecoveryCase
    from sqlalchemy import select

    # Get case info
    case = db.execute(
        select(RecoveryCase).where(RecoveryCase.id == case_id)
    ).scalar_one_or_none()

    case_info = {}
    if case:
        customer = db.execute(
            select(Customer).where(Customer.id == case.customer_id)
        ).scalar_one_or_none()
        case_info = {
            "case_id": str(case.id),
            "customer_name": customer.name if customer else "Unknown",
            "customer_email": customer.email if customer else None,
            "customer_phone": customer.phone if customer else None,
            "original_amount": case.original_amount,
            "recovered_amount": case.recovered_amount,
            "remaining_amount": case.remaining_amount,
            "status": case.status.value if hasattr(case.status, "value") else case.status,
            "risk_level": case.risk_level,
            "attempt_count": case.attempt_count,
            "max_attempts": case.max_attempts,
        }

    # Get all audit events
    events = list(
        db.execute(
            select(AuditEvent)
            .where(AuditEvent.recovery_case_id == case_id)
            .order_by(AuditEvent.created_at.asc())
        ).scalars().all()
    )

    timeline = []
    for event in events:
        meta = event.extra_data or {}
        event_type = event.action

        timeline.append({
            "id": str(event.id),
            "event_type": event_type,
            "timestamp": event.created_at.isoformat() if event.created_at else None,
            "description": EVENT_DESCRIPTIONS.get(event_type, event.action),
            "icon": EVENT_ICONS.get(event_type, "📝"),
            "color": EVENT_COLORS.get(event_type, "slate"),
            "entity_type": event.entity_type,
            "old_value": event.old_value,
            "new_value": event.new_value,
            "result": meta.get("result", ""),
            "reason": meta.get("reason", ""),
            "amount": meta.get("amount"),
            "amount_formatted": meta.get("amount_formatted"),
            "metadata": meta,
        })

    return {
        "case": case_info,
        "timeline": timeline,
        "total_events": len(timeline),
        "summary": _build_timeline_summary(timeline, case_info),
    }


def _build_timeline_summary(timeline: list[dict], case_info: dict) -> dict:
    """Build a human-readable summary of the timeline."""
    event_counts = {}
    for event in timeline:
        et = event["event_type"]
        event_counts[et] = event_counts.get(et, 0) + 1

    first_event = timeline[0] if timeline else None
    last_event = timeline[-1] if timeline else None

    messages_sent = event_counts.get(AuditEventType.MESSAGE_SENT, 0)
    messages_failed = event_counts.get(AuditEventType.MESSAGE_FAILED, 0)
    customer_replies = event_counts.get(AuditEventType.CUSTOMER_REPLIED, 0)
    payments_recovered = event_counts.get(AuditEventType.PAYMENT_RECOVERED, 0)

    return {
        "total_events": len(timeline),
        "event_counts": event_counts,
        "first_event_at": first_event["timestamp"] if first_event else None,
        "last_event_at": last_event["timestamp"] if last_event else None,
        "messages_sent": messages_sent,
        "messages_failed": messages_failed,
        "customer_replies": customer_replies,
        "payments_recovered": payments_recovered,
        "original_amount": case_info.get("original_amount", 0),
        "recovered_amount": case_info.get("recovered_amount", 0),
        "recovery_rate": (
            case_info["recovered_amount"] / case_info["original_amount"]
            if case_info.get("original_amount", 0) > 0 else 0
        ),
    }


def _format_amount(amount_paise: int) -> str:
    """Format amount in paise to Indian Rupee format."""
    rupees = amount_paise // 100
    s = str(rupees)
    if len(s) <= 3:
        return f"₹{s}"
    last_three = s[-3:]
    remaining = s[:-3]
    formatted = ""
    while len(remaining) > 2:
        formatted = "," + remaining[-2:] + formatted
        remaining = remaining[:-2]
    formatted = remaining + formatted + "," + last_three
    return f"₹{formatted}"
