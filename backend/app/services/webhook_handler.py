"""Razorpay webhook processing service.

Handles webhook signature verification and event processing for:
- payment.failed: Creates RevenueEvent + RecoveryCase with AT_RISK status
- payment.captured: Updates RevenueEvent + marks RecoveryCase RECOVERED if fully paid

All processing is idempotent - duplicate webhooks are detected and skipped.
"""

import hashlib
import hmac
import logging
import time

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.audit_event import create_audit_event
from app.crud.customer import create_customer, get_customer_by_external_id
from app.crud.recovery_case import (
    get_recovery_case,
    get_recovery_cases_by_status,
)
from app.crud.revenue_event import create_revenue_event, get_revenue_events_by_customer
from app.crud.webhook_event import get_webhook_event_by_event_id, store_webhook_event
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.schemas.audit_event import AuditEventCreate
from app.schemas.customer import CustomerCreate
from app.schemas.recovery_case import RecoveryCaseCreate
from app.schemas.revenue_event import RevenueEventCreate

logger = logging.getLogger(__name__)


def verify_webhook_signature(payload_body: bytes, signature: str) -> bool:
    """Verify Razorpay webhook signature using HMAC SHA256.

    Args:
        payload_body: The raw request body bytes
        signature: The X-Razorpay-Signature header value

    Returns:
        True if signature is valid, False otherwise
    """
    settings = get_settings()
    webhook_secret = settings.razorpay_webhook_secret

    if not webhook_secret:
        logger.warning("RAZORPAY_WEBHOOK_SECRET not configured, skipping verification")
        return True

    if not signature:
        return False

    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def is_duplicate_webhook(db: Session, event_id: str) -> bool:
    """Check if a webhook event has already been processed."""
    return get_webhook_event_by_event_id(db, event_id) is not None


def process_payment_failed(db: Session, payload: dict) -> dict:
    """Handle payment.failed webhook event.

    Steps:
    1. Check idempotency (skip if already processed)
    2. Store the revenue/payment event
    3. Find or create the customer
    4. Create a RecoveryCase with AT_RISK status
    5. Store amount and failure information
    6. Create an AuditEvent

    Returns:
        dict with status and case_id if a new case was created
    """
    _t0 = time.monotonic()
    event_id = payload.get("id", "")
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})

    payment_id = payment.get("id", "")
    order_id = payment.get("order_id", "")
    amount = payment.get("amount", 0)
    currency = payment.get("currency", "INR")
    status = payment.get("status", "failed")
    failure_reason = payment.get("failure_reason", "Unknown")
    failure_code = payment.get("failure_code", "")
    method = payment.get("method", "")

    # customer info from payment
    email = payment.get("email", "")
    phone = payment.get("contact", "")
    customer_external_id = payment.get("customer_id", "")

    # --- Step 1: Idempotency check ---
    if is_duplicate_webhook(db, event_id):
        logger.info("Duplicate webhook event %s, skipping", event_id)
        return {"status": "skipped", "reason": "duplicate_webhook"}

    # --- Step 1b: Installment correlation (recurring/EMI failure path) ---
    # A failed payment for an installment (matched by razorpay order/payment id)
    # is recorded against the installment plan — it does NOT spawn a new case.
    from app.services.installment_workflow import record_installment_failure

    installment = _find_installment_for_payment(db, payment_id, order_id)
    if installment:
        store_webhook_event(db, event_id, "payment.failed", payment_id)
        failure_result = record_installment_failure(
            db, installment.id, reason=failure_reason or "payment_failed"
        )
        logger.info(
            "Installment payment failed: installment=%s, case=%s",
            installment.id,
            installment.recovery_case_id,
        )
        return {
            "case_id": str(installment.recovery_case_id),
            "payment_id": payment_id,
            "installment_failure": True,
            **failure_result,
            "status": "processed",
        }

    # Check if revenue event already exists for this payment
    existing_events = get_revenue_events_by_customer(
        db,
        customer_id=_get_or_create_customer_id(
            db, customer_external_id, email, phone
        ),
    )
    for event in existing_events:
        if event.external_event_id == payment_id:
            logger.info("Revenue event for payment %s already exists, skipping", payment_id)
            store_webhook_event(db, event_id, "payment.failed", payment_id)
            return {"status": "skipped", "reason": "duplicate_revenue_event"}

    # --- Step 2: Store the revenue event ---
    customer_id = _get_or_create_customer_id(db, customer_external_id, email, phone)

    revenue_event = create_revenue_event(
        db,
        data=RevenueEventCreate(
            customer_id=customer_id,
            external_event_id=payment_id,
            event_type="payment_failed",
            amount=amount,
            currency=currency,
            status=status,
            source="razorpay",
            extra_data={
                "order_id": order_id,
                "method": method,
                "failure_reason": failure_reason,
                "failure_code": failure_code,
            },
        ),
    )

# --- Step 3: Assess risk via Revenue Risk Engine ---
    from app.crud.recovery_case import create_recovery_case
    from app.services import agent_steps
    from app.services.revenue_risk import assess_and_log_risk, assess_risk

    # --- Step 3a: Root-cause diagnosis (agent reasoning step) ---
    # Classify the failure into a canonical root cause so the negotiation
    # engine picks the bounded intervention. The diagnosis is streamed live
    # (and persisted) once the case exists (Step 3b).
    from app.services.root_cause import classify_root_cause

    diagnosis = classify_root_cause(
        failure_code=failure_code,
        failure_reason=failure_reason,
        event_type="payment_failed",
        extra={"method": method, "order_id": order_id},
    )

    assessment = assess_risk(
        db=db,
        customer_id=str(customer_id),
        revenue_event_id=str(revenue_event.id),
        event_type="payment_failed",
        amount=amount,
        extra_data={
            "order_id": order_id,
            "method": method,
            "failure_reason": failure_reason,
            "failure_code": failure_code,
        },
    )

    # --- Step 3b: Read merchant recovery policy ---
    from app.services.recovery_settings import get_or_create

    merchant_settings = get_or_create(db)
    max_attempts = merchant_settings.max_recovery_attempts

    # --- Step 4: Create RecoveryCase ---
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

    # --- Step 5: Set status to AT_RISK ---
    recovery_case.status = RecoveryStatus.AT_RISK
    db.commit()
    db.refresh(recovery_case)

    # --- Step 6: Store webhook event for idempotency ---
    store_webhook_event(db, event_id, "payment.failed", payment_id)

    # --- Step 7: Create AuditEvent ---
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
                "failure_reason": failure_reason,
            },
            extra_data={"webhook_event_id": event_id, "payment_id": payment_id},
        ),
    )

    # --- Step 7b: Log the risk decision to the audit trail ---
    assess_and_log_risk(
        db=db,
        recovery_case_id=str(recovery_case.id),
        customer_id=str(customer_id),
        revenue_event_id=str(revenue_event.id),
        event_type="payment_failed",
        amount=amount,
        extra_data={
            "order_id": order_id,
            "method": method,
            "failure_reason": failure_reason,
            "failure_code": failure_code,
        },
    )

    # --- Step 7c: Stream the reasoning chain (Agent Thought Stream) ---
    # [Trigger Received] -> [Root Cause: ...] -> [Policy Check] -> [Action]
    # Each step is persisted to the audit trail AND pushed live over WebSocket.
    agent_steps.emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=agent_steps.AgentStage.TRIGGER,
        label="Trigger Received",
        detail=f"payment.failed · {failure_code or failure_reason or 'no gateway code'}",
        confidence=1.0,
        latency_ms=int((time.monotonic() - _t0) * 1000),
        extra={"payment_id": payment_id, "amount": amount, "method": method},
    )
    agent_steps.emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=agent_steps.AgentStage.DIAGNOSIS,
        label=f"Root Cause: {diagnosis.label}",
        detail=diagnosis.explanation,
        confidence=diagnosis.confidence,
        extra=diagnosis.to_dict(),
    )
    agent_steps.emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=agent_steps.AgentStage.POLICY,
        label="Policy Check: Recoverable",
        detail=(
            f"risk={assessment.risk_level} · recoverable={assessment.is_recoverable} · "
            f"max_attempts={max_attempts} · intervention={diagnosis.recommended_intervention}"
        ),
        confidence=1.0,
        extra={
            "risk_level": assessment.risk_level,
            "is_recoverable": assessment.is_recoverable,
            "recommended_intervention": diagnosis.recommended_intervention,
        },
    )

    logger.info(
        "Created recovery case %s for failed payment %s (amount: %d)",
        recovery_case.id,
        payment_id,
        amount,
    )

    # --- Step 8: Initiate recovery workflow ---
    # Connect payment failure → recovery case → policy → WhatsApp → schedule
    from app.services.orchestrator import initiate_recovery

    recovery_result = initiate_recovery(db, recovery_case.id)
    logger.info(
        "Recovery initiation result for case %s: %s",
        recovery_case.id,
        recovery_result.get("status"),
    )

    action_t0 = time.monotonic()
    action_label = "Action Dispatched"
    if recovery_result.get("status") == "initiated":
        action_label = "Recovery Initiated: WhatsApp"
    elif recovery_result.get("status") == "skipped":
        action_label = "Policy Blocked: Skipped"
    agent_steps.emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=agent_steps.AgentStage.ACTION,
        label=action_label,
        detail=recovery_result.get("reason") or recovery_result.get("error")
        or f"case_status={recovery_result.get('status')}",
        confidence=0.98,
        latency_ms=int((time.monotonic() - action_t0) * 1000),
        extra={"recovery_result": recovery_result},
    )

    # --- Step 9: Auto-send the payment-failed notification email ---
    # The customer gets a transactional email as soon as the agent detects the
    # failure (the recovery case is created), carrying the retry payment link.
    _auto_send_failed_payment_email(db, recovery_case, amount)

    return {
        "status": "processed",
        "case_id": str(recovery_case.id),
        "payment_id": payment_id,
        "recovery_initiated": recovery_result.get("status") == "initiated",
        "recovery_result": recovery_result,
        "diagnosis": diagnosis.to_dict(),
    }


def process_payment_captured(db: Session, payload: dict) -> dict:
    """Handle payment.captured webhook event.

    Steps:
    1. Check idempotency (skip if already processed)
    2. Update payment/revenue event
    3. Find related recovery case
    4. Increase recovered_amount
    5. Mark recovery case RECOVERED if fully paid
    6. Stop any future recovery workflow
    7. Write an AuditEvent

    Returns:
        dict with status and case_id if a case was updated
    """
    event_id = payload.get("id", "")
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})

    payment_id = payment.get("id", "")
    order_id = payment.get("order_id", "")
    amount = payment.get("amount", 0)
    status = payment.get("status", "captured")
    method = payment.get("method", "")

    # --- Step 1: Idempotency check ---
    if is_duplicate_webhook(db, event_id):
        logger.info("Duplicate webhook event %s, skipping", event_id)
        return {"status": "skipped", "reason": "duplicate_webhook"}

    # --- Step 1b: Installment correlation (recurring/EMI captured path) ---
    # A captured payment for an installment is recorded against the payment
    # plan (marking the installment PAID and the plan one step closer to
    # COMPLETED) instead of inflating the original case's partial recovery.
    from app.services.installment_workflow import record_installment_payment

    installment = _find_installment_for_payment(db, payment_id, order_id)
    if installment:
        store_webhook_event(db, event_id, "payment.captured", payment_id)
        payment_result = record_installment_payment(
            db, installment.id, amount, razorpay_payment_id=payment_id
        )
        _record_verified_payment(
            db=db,
            recovery_case_id=installment.recovery_case_id,
            payment_id=payment_id,
            order_id=order_id,
            amount=amount,
            method=method,
            extra_data={"source": "razorpay_webhook", "channel": "payment_plan"},
        )
        plan_case = db.get(RecoveryCase, installment.recovery_case_id)
        _emit_ledger_capture_step(
            db,
            plan_case,
            payment_id=payment_id,
            amount=amount,
            method=method,
        )

        # Plan completion settles the case in full → run the deterministic
        # finalizer (fulfill promises, close the plan, cancel emails/links,
        # mark invoices paid) and send the loop-termination confirmation, then
        # stream the typed events the non-installment path already emits.
        if plan_case and plan_case.remaining_amount <= 0:
            from datetime import datetime, timezone

            from app.services.realtime import publish_case_event
            from app.services.workflow_engine import finalize_recovered_case

            finalize_recovered_case(db, plan_case, reason="installment_plan_completed")
            _send_settlement_confirmation(
                db, plan_case, amount_paise=plan_case.original_amount
            )
            occurred = datetime.now(timezone.utc).isoformat()
            publish_case_event(
                event_type="payment_captured",
                case_id=str(plan_case.id),
                data={
                    "payment_id": payment_id,
                    "amount": amount,
                    "remaining_amount": 0,
                    "recovered_amount": plan_case.recovered_amount,
                },
                occurred_at=occurred,
            )

        logger.info(
            "Installment payment captured: installment=%s, case=%s",
            installment.id,
            installment.recovery_case_id,
        )
        return {
            "case_id": str(installment.recovery_case_id),
            "payment_id": payment_id,
            "installment_payment": True,
            **payment_result,
            "status": "processed",
        }

    # Find the revenue event for this payment
    from sqlalchemy import select
    from app.models.revenue_event import RevenueEvent

    revenue_event = db.execute(
        select(RevenueEvent).where(RevenueEvent.external_event_id == payment_id)
    ).scalar_one_or_none()

    if not revenue_event:
        logger.warning("No revenue event found for payment %s", payment_id)
        store_webhook_event(db, event_id, "payment.captured", payment_id)
        return {"status": "skipped", "reason": "no_revenue_event"}

    # --- Step 2: Update revenue event status ---
    revenue_event.status = status
    db.commit()

    # --- Step 3: Find related recovery case ---
    # Search all non-terminal statuses (case may have moved from AT_RISK to RECOVERY_IN_PROGRESS)
    recovery_cases = (
        get_recovery_cases_by_status(db, RecoveryStatus.AT_RISK)
        + get_recovery_cases_by_status(db, RecoveryStatus.RECOVERY_IN_PROGRESS)
        + get_recovery_cases_by_status(db, RecoveryStatus.ENGAGED)
        + get_recovery_cases_by_status(db, RecoveryStatus.PAYMENT_PLAN)
        + get_recovery_cases_by_status(db, RecoveryStatus.PARTIALLY_RECOVERED)
        + get_recovery_cases_by_status(db, RecoveryStatus.PROMISED)
        + get_recovery_cases_by_status(db, RecoveryStatus.SCHEDULED)
    )

    target_case = None
    for case in recovery_cases:
        if case.revenue_event_id == revenue_event.id:
            target_case = case
            break

    if not target_case:
        logger.warning(
            "No recovery case found for revenue event %s", revenue_event.id
        )
        store_webhook_event(db, event_id, "payment.captured", payment_id)
        return {"status": "skipped", "reason": "no_recovery_case"}

    # --- Step 4: Increase recovered_amount ---
    old_recovered = target_case.recovered_amount
    target_case.recovered_amount += amount
    target_case.remaining_amount = max(
        0, target_case.original_amount - target_case.recovered_amount
    )

    # --- Step 4b: Record the VERIFIED payment ---
    # Only "captured" webhooks create Payment rows — the ground truth for the
    # Revenue Map. A customer message is never treated as money.
    _record_verified_payment(
        db=db,
        recovery_case_id=target_case.id,
        payment_id=payment_id,
        order_id=order_id,
        amount=amount,
        method=method,
        extra_data={"source": "razorpay_webhook"},
    )
    _emit_ledger_capture_step(
        db, target_case, payment_id=payment_id, amount=amount, method=method
    )

    # --- Step 5 & 6: Mark RECOVERED if fully paid ---
    old_status = target_case.status
    if target_case.remaining_amount <= 0:
        from datetime import datetime, timezone

        from app.services.realtime import publish_case_event
        from app.services.workflow_engine import finalize_recovered_case

        # Run the deterministic finalizer: settle amounts + RECOVERED, fulfil
        # any ACTIVE promise, close any open payment plan, cancel every pending
        # scheduled action + PENDING email, expire any stale payment link and
        # mark the case's invoices PAID (idempotent).
        finalize_recovered_case(db, target_case, reason="payment_captured")

        logger.info(
            "Recovery case %s fully recovered (amount: %d)",
            target_case.id,
            target_case.recovered_amount,
        )

        # Settlement confirmation: tell the customer the payment is reconciled
        # and push it to the live audit stream. This is the loop-termination
        # message for a fully settled case.
        _send_settlement_confirmation(
            db,
            target_case,
            amount_paise=target_case.original_amount,
        )

        # Typed payment event for the ops console. The finalizer emits the
        # richer recovery_completed / case_status_changed events.
        occurred = datetime.now(timezone.utc).isoformat()
        publish_case_event(
            event_type="payment_captured",
            case_id=str(target_case.id),
            data={
                "payment_id": payment_id,
                "amount": amount,
                "remaining_amount": 0,
                "recovered_amount": target_case.recovered_amount,
            },
            occurred_at=occurred,
        )
    else:
        target_case.status = RecoveryStatus.PARTIALLY_RECOVERED

        from datetime import datetime as _dt, timezone as _tz
        from app.services.realtime import publish_case_event

        publish_case_event(
            event_type="payment_captured",
            case_id=str(target_case.id),
            data={
                "payment_id": payment_id,
                "amount": amount,
                "remaining_amount": target_case.remaining_amount,
                "recovered_amount": target_case.recovered_amount,
            },
            occurred_at=_dt.now(_tz.utc).isoformat(),
        )

    db.commit()
    db.refresh(target_case)

    # --- Step 7: Store webhook event ---
    store_webhook_event(db, event_id, "payment.captured", payment_id)

    # --- Step 8: Create AuditEvent ---
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=target_case.id,
            entity_type="recovery_case",
            entity_id=target_case.id,
            action="updated",
            old_value={
                "status": str(old_status.value),
                "recovered_amount": old_recovered,
            },
            new_value={
                "status": str(target_case.status.value),
                "recovered_amount": target_case.recovered_amount,
                "remaining_amount": target_case.remaining_amount,
            },
            extra_data={"webhook_event_id": event_id, "payment_id": payment_id},
        ),
    )

    return {
        "status": "processed",
        "case_id": str(target_case.id),
        "payment_id": payment_id,
        "recovered_amount": target_case.recovered_amount,
        "remaining_amount": target_case.remaining_amount,
    }


def process_mandate_auth_failed(db: Session, payload: dict) -> dict:
    """Handle ``subscription.auth.failed`` — a recurring mandate drop.

    A failed authorization means the stored mandate can no longer charge the
    customer (declined / expired / instrument changed). This is a distinct
    revenue-at-risk trigger: the root cause is always a mandate lifecycle
    problem, and the intervention is a smart mandate re-setup (never blind
    re-charging of the same dead mandate).

    Reuses the same ingestion path as ``payment.failed`` (revenue event →
    risk → recovery case → streamed reasoning chain) so mandate drops surface
    in the exact same pipeline.
    """
    _t0 = time.monotonic()
    event_id = payload.get("id", "")
    auth = payload.get("payload", {}).get("authorization", {}).get("entity", {})
    failure = payload.get("payload", {}).get("failure", {}) or {}
    error = failure.get("entity", {}) if isinstance(failure, dict) else {}

    subscription_id = auth.get("subscription_id", "")
    mandate_id = auth.get("id", "") or error.get("id", "")
    amount = error.get("amount", 0) or auth.get("amount", 0) or 0
    failure_reason = error.get("failure_reason", "") or "mandate auth failed"
    failure_code = error.get("failure_code", "") or "mandate_declined"

    email = error.get("email", "") or auth.get("email", "")
    phone = error.get("contact", "") or auth.get("contact", "")
    customer_external_id = error.get("customer_id", "") or auth.get("customer_id", "")

    # --- Idempotency ---
    unique_id = error.get("razorpay_event_id") or event_id
    if is_duplicate_webhook(db, event_id):
        return {"status": "skipped", "reason": "duplicate_webhook"}

    # --- Root-cause diagnosis ---
    from app.services.agent_steps import AgentStage, emit_case_step
    from app.services.root_cause import classify_root_cause

    diagnosis = classify_root_cause(
        failure_code=failure_code,
        failure_reason=failure_reason,
        event_type="subscription.auth.failed",
        trigger_type="mandate_drop",
        extra={"mandate_id": mandate_id, "subscription_id": subscription_id},
    )

    # --- Create customer + revenue event + recovery case ---
    customer_id = _get_or_create_customer_id(db, customer_external_id, email, phone)
    revenue_event = create_revenue_event(
        db,
        data=RevenueEventCreate(
            customer_id=customer_id,
            external_event_id=unique_id or f"mandate_{mandate_id}",
            event_type="mandate_drop",
            amount=amount,
            currency="INR",
            status="failed",
            source="razorpay",
            extra_data={
                "mandate_id": mandate_id,
                "subscription_id": subscription_id,
                "failure_reason": failure_reason,
                "failure_code": failure_code,
                "trigger": "subscription.auth.failed",
            },
        ),
    )

    from app.crud.recovery_case import create_recovery_case
    from app.services.revenue_risk import assess_risk

    assessment = assess_risk(
        db=db,
        customer_id=str(customer_id),
        revenue_event_id=str(revenue_event.id),
        event_type="failed_subscription",
        amount=amount,
        extra_data={
            "subscription_status": "active",
            "failure_reason": failure_reason,
            "failure_code": failure_code,
        },
    )

    from app.services.recovery_settings import get_or_create

    merchant_settings = get_or_create(db)
    max_attempts = merchant_settings.max_recovery_attempts

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
    extra = dict(recovery_case.extra_data or {})
    extra["trigger"] = "mandate_drop"
    extra["root_cause"] = diagnosis.root_cause
    extra["mandate_id"] = mandate_id
    extra["subscription_id"] = subscription_id
    recovery_case.extra_data = extra
    db.commit()

    store_webhook_event(db, event_id, "subscription.auth.failed", mandate_id or event_id)

    # --- Audit + streamed reasoning chain ---
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
                "trigger": "mandate_drop",
                "failure_reason": failure_reason,
            },
            extra_data={"webhook_event_id": event_id, "mandate_id": mandate_id},
        ),
    )

    emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=AgentStage.TRIGGER,
        label="Trigger Received",
        detail=f"subscription.auth.failed · mandate {mandate_id or '—'} dropped",
        confidence=1.0,
        latency_ms=int((time.monotonic() - _t0) * 1000),
        extra={"mandate_id": mandate_id, "subscription_id": subscription_id},
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
        label="Policy Check: Mandate Re-setup",
        detail=(
            f"intervention={diagnosis.recommended_intervention} · "
            f"risk={assessment.risk_level} · max_attempts={max_attempts}"
        ),
        confidence=diagnosis.confidence,
        extra={"recommended_intervention": diagnosis.recommended_intervention},
    )

    from app.services.orchestrator import initiate_recovery

    recovery_result = initiate_recovery(db, recovery_case.id)

    emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=AgentStage.ACTION,
        label="Mandate Re-setup Flow Initiated",
        detail=f"intervention={diagnosis.recommended_intervention} · status={recovery_result.get('status')}",
        extra={"recovery_status": recovery_result.get("status")},
    )

    logger.info(
        "Mandate drop ingested: case=%s mandate=%s amount=%d",
        recovery_case.id,
        mandate_id,
        amount,
    )

    return {
        "status": "processed",
        "case_id": str(recovery_case.id),
        "mandate_id": mandate_id,
        "recovery_initiated": recovery_result.get("status") == "initiated",
        "diagnosis": diagnosis.to_dict(),
    }


def process_order_paid(db: Session, payload: dict) -> dict:
    """Correlate an order transition to the paid state (no money recorded).

    Razorpay fires ``order.paid`` when an order transitions to the paid state.
    Actual money is never recorded here — that is the exclusive job of the
    ``payment.captured`` webhook (which creates the verified Payment row). This
    handler only correlates the order to a payment plan installment and pushes a
    typed ``order_paid`` event so the ops console reflects the order lifecycle.

    Idempotent: duplicates are skipped via the stored webhook event id.
    """
    event_id = payload.get("id", "")
    order = payload.get("payload", {}).get("order", {}).get("entity", {})
    order_id = order.get("id", "")

    if is_duplicate_webhook(db, event_id):
        return {"status": "skipped", "reason": "duplicate_webhook"}

    store_webhook_event(db, event_id, "order.paid", order_id or event_id)

    if not order_id:
        return {"status": "processed", "case_id": None, "order_id": None}

    installment = _find_installment_for_payment(db, "", order_id)
    if not installment:
        return {"status": "processed", "case_id": None, "order_id": order_id}

    from app.services.realtime import publish_case_event

    publish_case_event(
        event_type="order_paid",
        case_id=str(installment.recovery_case_id) if installment.recovery_case_id else "",
        data={"order_id": order_id, "installment_id": str(installment.id)},
    )

    logger.info("order.paid correlated to installment %s", installment.id)
    return {
        "status": "processed",
        "case_id": str(installment.recovery_case_id) if installment.recovery_case_id else None,
        "order_id": order_id,
    }


def _get_or_create_customer_id(
    db: Session, external_id: str, email: str, phone: str
) -> "uuid.UUID":
    """Find existing customer or create a new one."""
    import uuid

    if external_id:
        customer = get_customer_by_external_id(db, external_id)
        if customer:
            return customer.id

    # Create customer with available info
    customer = create_customer(
        db,
        data=CustomerCreate(
            external_id=external_id or f"unknown_{uuid.uuid4().hex[:12]}",
            email=email or None,
            phone=phone or None,
            name=None,
        ),
    )
    return customer.id


def _find_installment_for_payment(
    db: Session, payment_id: str, order_id: str = ""
):
    """Correlate a webhook payment to an installment (EMI/recurring path).

    Matches on the installment's stored Razorpay payment id first (available
    on capture), falling back to the Razorpay order id (available on failure).

    Returns:
        Installment row if matched, else None
    """
    from sqlalchemy import select

    from app.models.installment import Installment

    if payment_id:
        installment = db.execute(
            select(Installment).where(Installment.razorpay_payment_id == payment_id)
        ).scalar_one_or_none()
        if installment:
            return installment

    if order_id:
        installment = db.execute(
            select(Installment).where(Installment.razorpay_order_id == order_id)
        ).scalar_one_or_none()
        if installment:
            return installment

    return None


def _record_verified_payment(
    db: Session,
    recovery_case_id,
    payment_id: str,
    order_id: str,
    amount: int,
    method: str,
    extra_data: dict | None = None,
):
    """Create a ``Payment`` row for a verified captured webhook payment.

    This is the only place real money is recorded into the Revenue Map.
    The ``razorpay_payment_id`` is unique — duplicates are skipped silently.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.payment import Payment

    existing = db.execute(
        select(Payment).where(Payment.razorpay_payment_id == payment_id)
    ).scalar_one_or_none()
    if existing:
        return existing

    payment = Payment(
        recovery_case_id=recovery_case_id,
        razorpay_payment_id=payment_id,
        razorpay_order_id=order_id or None,
        amount=amount,
        currency="INR",
        status="captured",
        method=method or None,
        paid_at=datetime.now(timezone.utc),
        extra_data=extra_data or {"source": "razorpay_webhook"},
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    logger.info(
        "Verified payment recorded: payment=%s, case=%s, amount=%d",
        payment_id,
        recovery_case_id,
        amount,
    )
    return payment


def _fulfill_active_promises(db: Session, recovery_case_id) -> list[str]:
    """Mark any ACTIVE promise for a case as FULFILLED.

    Called when a verified capture settles the case — the customer's promise
    ("I'll pay by X") is now redeemed, so the promise moves to FULFILLED instead
    of being allowed to expire/miss.

    Returns:
        List of promise ids that were fulfilled.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.promise import Promise, PromiseStatus

    promises = list(
        db.execute(
            select(Promise).where(
                Promise.recovery_case_id == recovery_case_id,
                Promise.status == PromiseStatus.ACTIVE.value,
            )
        ).scalars().all()
    )
    now = datetime.now(timezone.utc)
    for promise in promises:
        promise.status = PromiseStatus.FULFILLED.value
        promise.fulfilled_at = now
        promise.fulfilled_amount = promise.amount_promised
    if promises:
        db.commit()
    return [str(p.id) for p in promises]


def _emit_ledger_capture_step(
    db: Session,
    case,
    payment_id: str,
    amount: int,
    method: str,
) -> None:
    """Stream the ledger-verification reasoning step for a verified capture.

    A captured webhook is the ground-truth money event; this step documents in
    the Agent Thought Stream that the recovered amount was *reconciled* (not
    merely promised) and, when the case closes, that recovery completed.
    """
    from datetime import datetime, timezone

    from app.services import agent_steps

    fully = case.remaining_amount <= 0
    agent_steps.emit_case_step(
        db,
        case_id=str(case.id),
        stage=agent_steps.AgentStage.LEDGER,
        label="Ledger Verified: Capture Reconciled",
        detail=(
            f"payment {payment_id} ({method or 'unknown'}) → ₹{(amount // 100)} "
            f"credited · remaining ₹{(max(case.remaining_amount, 0) // 100)}"
            + (" · case CLOSED" if fully else " · partial recovery")
        ),
        confidence=1.0,
        extra={
            "payment_id": payment_id,
            "amount": amount,
            "method": method,
            "recovered_amount": case.recovered_amount,
            "remaining_amount": case.remaining_amount,
            "settled": fully,
        },
    )
    if fully:
        agent_steps.emit_case_step(
            db,
            case_id=str(case.id),
            stage=agent_steps.AgentStage.LEDGER,
            label="Recovery Completed",
            detail=f"{case.original_amount // 100} INR captured — case closed",
            confidence=1.0,
            extra={"closed_at": datetime.now(timezone.utc).isoformat()},
        )


def _send_settlement_confirmation(
    db: Session,
    case,
    amount_paise: int,
) -> None:
    """Persist + broadcast the loop-termination reconciliation message.

    Emitted once a verified Razorpay capture settles a recovery case in full.
    The message is rendered from the agent engine's ``recovered`` template
    ("Thank you! Your payment of ₹X has been successfully reconciled."), written
    to the case's WhatsApp thread (so it survives a reload) and pushed over the
    case WebSocket so the ops console shows it live without a refresh.

    Idempotent in practice: the payment.captured webhook is de-duplicated
    upstream, so this runs exactly once per settlement.
    """
    from app.services import agent_engine, agent_flow

    customer = None
    if case.customer_id:
        from app.models.customer import Customer

        customer = db.get(Customer, case.customer_id)

    customer_name = customer.name if customer else None
    payload = agent_engine.build_reply(
        case_id=str(case.id),
        customer_name=customer_name,
        amount_paise=amount_paise,
        intent="ALREADY_PAID",
        invoice_id=agent_engine.invoice_id_for_case(str(case.id)),
        recovered=True,
    )
    agent_flow.persist_agent_reply(db, case, payload["text"], payload)
    logger.info(
        "Settlement confirmation sent for recovered case %s (amount=%d)",
        case.id,
        amount_paise,
    )


def _auto_send_failed_payment_email(db: Session, case, amount_paise: int) -> None:
    """Send the automatic payment-failed notification email for a case.

    Runs once when a failed payment creates a recovery case. Uses the
    transactional email service (opt-out / duplicate / hard-stop compliant)
    and is a no-op when the customer has no email address or the send is
    blocked (already sent, opted out, etc.).
    """
    from app.services.email import EmailType, send_recovery_email
    from app.services.agent_engine import payment_url_for_case

    try:
        send_recovery_email(
            db=db,
            case_id=case.id,
            email_type=EmailType.FAILED_PAYMENT.value,
            payment_link=payment_url_for_case(str(case.id)),
        )
    except Exception:
        logger.exception("Failed to auto-send payment-failed email for case %s", case.id)
