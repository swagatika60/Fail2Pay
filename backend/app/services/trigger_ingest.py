"""External revenue-trigger ingestion service.

Unifies the "value-creation" ingestion path for revenue-at-risk signals that
arrive outside the Razorpay payment webhooks:

    checkout_abandonment  — cart abandoned before payment completion
    aging_invoice         — invoice past its due date
    mandate_drop          — recurring mandate can no longer charge the customer

Every trigger follows the same deterministic pipeline so the ops console sees
one consistent view: revenue event → risk assessment → recovery case → streamed
agent-reasoning chain (Trigger Received → Root Cause → Policy Check → Action).
Money is never recorded here; only risk + recovery intent.
"""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crud.audit_event import create_audit_event
from app.crud.customer import create_customer, get_customer_by_external_id
from app.crud.recovery_case import create_recovery_case
from app.crud.revenue_event import create_revenue_event
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.revenue_event import RevenueEvent
from app.schemas.audit_event import AuditEventCreate
from app.schemas.customer import CustomerCreate
from app.schemas.recovery_case import RecoveryCaseCreate
from app.schemas.revenue_event import RevenueEventCreate

logger = logging.getLogger(__name__)


def _idempotent(db: Session, external_event_id: str) -> bool:
    if not external_event_id:
        return False
    existing = db.execute(
        select(RevenueEvent).where(RevenueEvent.external_event_id == external_event_id)
    ).scalar_one_or_none()
    return existing is not None


def _event_type_for(trigger_type: str) -> str:
    return {
        "checkout_abandonment": "checkout_abandonment",
        "aging_invoice": "overdue_invoice",
        "mandate_drop": "failed_subscription",
    }.get(trigger_type, trigger_type)


def ingest_trigger(
    db: Session,
    *,
    trigger_type: str,
    external_event_id: str,
    amount: int,
    customer_external_id: str = "",
    email: str = "",
    phone: str = "",
    name: str | None = None,
    failure_code: str = "",
    failure_reason: str = "",
    description: str = "",
    metadata: dict | None = None,
) -> dict:
    """Ingest a revenue-at-risk trigger into the recovery pipeline.

    Returns the standard ingestion result (status, case_id, diagnosis, ...) so
    every route returns a consistent envelope.
    """
    _t0 = time.monotonic()
    metadata = metadata or {}

    if _idempotent(db, external_event_id):
        return {"status": "skipped", "reason": "duplicate_trigger"}

    import uuid as _uuid

    resolved_event_id = external_event_id or f"trigger_{trigger_type}_{_uuid.uuid4().hex[:12]}"

    from app.models.customer import Customer
    from uuid import UUID

    customer_id: UUID | None = None
    if customer_external_id:
        customer = get_customer_by_external_id(db, customer_external_id)
        if customer:
            customer_id = customer.id
    if customer_id is None:
        _existing = (
            db.execute(select(Customer).where(Customer.email == email))
            .scalars()
            .first()
            if email
            else None
        )
        customer_id = _existing.id if _existing else None
    if customer_id is None:
        customer = create_customer(
            db,
            data=CustomerCreate(
                external_id=customer_external_id or f"trigger_{_uuid.uuid4().hex[:12]}",
                email=email or None,
                phone=phone or None,
                name=name,
            ),
        )
        customer_id = customer.id

    # --- Root-cause diagnosis ---
    from app.services.agent_steps import AgentStage, emit_case_step
    from app.services.root_cause import classify_root_cause

    diagnosis = classify_root_cause(
        failure_code=failure_code,
        failure_reason=failure_reason or description,
        event_type=_event_type_for(trigger_type),
        trigger_type=trigger_type,
        extra=metadata,
    )

    # --- Revenue event (open/at-risk; NO money recorded) ---
    revenue_event = create_revenue_event(
        db,
        data=RevenueEventCreate(
            customer_id=customer_id,
            external_event_id=resolved_event_id,
            event_type=_event_type_for(trigger_type),
            amount=amount,
            currency=metadata.get("currency", "INR"),
            status="failed"
            if trigger_type == "mandate_drop"
            else "open",
            source=metadata.get("source", trigger_type),
            extra_data={
                "trigger": trigger_type,
                "failure_reason": failure_reason,
                "failure_code": failure_code,
                "description": description,
                **metadata,
            },
        ),
    )

    # --- Deterministic risk assessment ---
    from app.services.revenue_risk import assess_and_log_risk, assess_risk

    assessment = assess_risk(
        db=db,
        customer_id=str(customer_id),
        revenue_event_id=str(revenue_event.id),
        event_type=_event_type_for(trigger_type),
        amount=amount,
        extra_data=metadata,
    )

    # --- Recovery case + merchant policy ---
    from app.services.recovery_settings import get_or_create

    max_attempts = get_or_create(db).max_recovery_attempts

    recovery_case = create_recovery_case(
        db,
        data=RecoveryCaseCreate(
            customer_id=customer_id,
            revenue_event_id=revenue_event.id,
            risk_level=assessment.risk_level,
            risk_reason=assessment.risk_reason,
            original_amount=amount,
            remaining_amount=amount,
            max_attempts=max_attempts,
        ),
    )
    recovery_case.status = RecoveryStatus.AT_RISK
    _extra = dict(recovery_case.extra_data or {})
    _extra["trigger"] = trigger_type
    _extra["root_cause"] = diagnosis.root_cause
    recovery_case.extra_data = _extra
    db.commit()

    # --- Audit: the FIRST audit event must be the "created" lifecycle event ---
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=recovery_case.id,
            entity_type="recovery_case",
            entity_id=recovery_case.id,
            action="created",
            new_value={
                "status": "AT_RISK",
                "original_amount": amount,
                "trigger": trigger_type,
                "source": metadata.get("source", ""),
            },
            extra_data={"external_event_id": external_event_id},
        ),
    )

    # --- Streamed agent-reasoning chain ---
    emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=AgentStage.TRIGGER,
        label="Trigger Received",
        detail=f"{trigger_type} · {description or external_event_id or '—'}",
        confidence=1.0,
        latency_ms=int((time.monotonic() - _t0) * 1000),
        extra=metadata,
    )
    emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=AgentStage.DIAGNOSIS,
        label=f"Root Cause: {diagnosis.label}",
        detail=diagnosis.explanation,
        confidence=diagnosis.confidence,
        extra=diagnosis.to_dict(),
    )
    emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=AgentStage.POLICY,
        label=f"Policy Check: {assessment.risk_level} / Recoverable",
        detail=(
            f"risk={assessment.risk_level} · recoverable={assessment.is_recoverable} · "
            f"intervention={diagnosis.recommended_intervention}"
        ),
        confidence=diagnosis.confidence,
        extra={
            "risk_level": assessment.risk_level,
            "risk_category": assessment.risk_category,
            "is_recoverable": assessment.is_recoverable,
            "recommended_intervention": diagnosis.recommended_intervention,
        },
    )

    # --- Trigger the recovery workflow (bounded by policy+schedule) ---
    from app.services.orchestrator import initiate_recovery

    recovery_result = initiate_recovery(db, recovery_case.id)

    action_label = {
        "initiated": "Recovery Initiated: WhatsApp",
        "skipped": "Policy Blocked: Skipped",
    }.get(recovery_result.get("status"), "Action Dispatched")

    emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=AgentStage.ACTION,
        label=action_label,
        detail=(
            recovery_result.get("reason")
            or recovery_result.get("error")
            or f"status={recovery_result.get('status')}"
        ),
        confidence=0.98,
        extra={"recovery_result": recovery_result},
    )

    logger.info(
        "Trigger ingested: type=%s case=%s amount=%d risk=%s",
        trigger_type,
        recovery_case.id,
        amount,
        assessment.risk_level,
    )

    return {
        "status": "processed",
        "case_id": str(recovery_case.id),
        "revenue_event_id": str(revenue_event.id),
        "trigger_type": trigger_type,
        "amount": amount,
        "risk_level": assessment.risk_level,
        "is_recoverable": assessment.is_recoverable,
        "recovery_initiated": recovery_result.get("status") == "initiated",
        "diagnosis": diagnosis.to_dict(),
    }


def ingest_checkout_abandonment(db: Session, payload: dict) -> dict:
    """POST /api/triggers/checkout-abandoned payload → recovery case + CheckoutAbandonment record."""
    result = ingest_trigger(
        db,
        trigger_type="checkout_abandonment",
        external_event_id=payload.get("external_event_id", "")
        or payload.get("event_id", ""),
        amount=payload.get("amount", 0),
        customer_external_id=payload.get("customer_id", ""),
        email=payload.get("email", ""),
        phone=payload.get("phone", ""),
        name=payload.get("name"),
        failure_reason=payload.get("failure_reason", "cart abandoned at checkout"),
        description=payload.get("description", "Cart abandoned during checkout"),
        metadata={
            "cart_ref": payload.get("cart_ref", ""),
            "currency": payload.get("currency", "INR"),
            "abandonment_count": payload.get("abandonment_count", 1),
            "source": payload.get("source", "checkout"),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Create the CheckoutAbandonment record so the list page has data to show.
    if result.get("status") == "processed" and result.get("case_id"):
        from uuid import UUID
        from app.models.recovery_case import RecoveryCase
        from app.services.checkout_recovery import track_checkout_abandonment

        case = db.get(RecoveryCase, UUID(result["case_id"]))
        if case:
            checkout_result = track_checkout_abandonment(
                db,
                customer_id=case.customer_id,
                cart_ref=payload.get("cart_ref", f"CART-{str(case.id)[:8]}"),
                amount=payload.get("amount", 0),
                currency=payload.get("currency", "INR"),
                abandonment_reason=payload.get("failure_reason", "cart abandoned at checkout"),
                source=payload.get("source", "checkout"),
            )
            result["checkout_abandonment"] = checkout_result

    return result


def ingest_aging_invoice(db: Session, payload: dict) -> dict:
    """POST /api/triggers/aging-invoice payload → recovery case."""
    due_date = payload.get("due_date")
    overdue_days = payload.get("overdue_days")
    if overdue_days is None and due_date:
        try:
            due = (
                datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                if isinstance(due_date, str)
                else due_date
            )
            overdue_days = max(0, (datetime.now(timezone.utc) - due).days)
        except (TypeError, ValueError):
            overdue_days = 0
    if overdue_days is None:
        overdue_days = 0

    return ingest_trigger(
        db,
        trigger_type="aging_invoice",
        external_event_id=payload.get("external_event_id", "")
        or payload.get("invoice_id", ""),
        amount=payload.get("amount", 0),
        customer_external_id=payload.get("customer_id", ""),
        email=payload.get("email", ""),
        phone=payload.get("phone", ""),
        name=payload.get("name"),
        failure_reason=payload.get("failure_reason", f"invoice overdue by {overdue_days} days"),
        description=payload.get("description", "Invoice past its due date"),
        metadata={
            "invoice_id": payload.get("invoice_id", ""),
            "currency": payload.get("currency", "INR"),
            "due_date": payload.get("due_date", ""),
            "overdue_days": overdue_days,
            "source": payload.get("source", "billing"),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def ingest_mandate_drop(db: Session, payload: dict) -> dict:
    """POST /api/triggers/mandate-drop payload → recovery case."""
    return ingest_trigger(
        db,
        trigger_type="mandate_drop",
        external_event_id=payload.get("external_event_id", "")
        or payload.get("mandate_id", ""),
        amount=payload.get("amount", 0),
        customer_external_id=payload.get("customer_id", ""),
        email=payload.get("email", ""),
        phone=payload.get("phone", ""),
        name=payload.get("name"),
        failure_code=payload.get("failure_code", "mandate_declined"),
        failure_reason=payload.get(
            "failure_reason", "recurring mandate failed to charge the customer"
        ),
        description=payload.get("description", "Recurring mandate dropped"),
        metadata={
            "mandate_id": payload.get("mandate_id", ""),
            "subscription_id": payload.get("subscription_id", ""),
            "currency": payload.get("currency", "INR"),
            "source": payload.get("source", "razorpay_subscriptions"),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
    )