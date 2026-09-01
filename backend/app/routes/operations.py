"""Operations list endpoints for the frontend.

Lightweight read-only lists (conversations, payment plans, invoices) with
case + customer context, used by the Revenue Ops console pages.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["operations"])


def _case_customer_context(db: Session, case_id) -> dict:
    """Return minimal case + customer context for a recovery case."""
    from app.models.customer import Customer
    from app.models.recovery_case import RecoveryCase

    case = db.get(RecoveryCase, case_id)
    if not case:
        return {}
    customer = db.get(Customer, case.customer_id) if case.customer_id else None
    return {
        "case_id": str(case.id),
        "case_status": case.status.value if hasattr(case.status, "value") else case.status,
        "case_risk_level": case.risk_level,
        "customer_name": customer.name if customer else None,
        "customer_email": customer.email if customer else None,
        "customer_phone": customer.phone if customer else None,
    }


def _bulk_case_customer_context(db: Session, case_ids) -> dict:
    """Preload case + customer context for many case ids in a handful of queries.

    Avoids the N+1 pattern of _case_customer_context (one RecoveryCase + one
    Customer query per row) and returns a map keyed by case id.
    """
    from app.models.customer import Customer
    from app.models.recovery_case import RecoveryCase

    case_ids = list({cid for cid in case_ids if cid is not None})
    if not case_ids:
        return {}

    cases = list(
        db.execute(select(RecoveryCase).where(RecoveryCase.id.in_(case_ids))).scalars().all()
    )
    customer_ids = {c.customer_id for c in cases if c.customer_id}
    customers = (
        list(db.execute(select(Customer).where(Customer.id.in_(customer_ids))).scalars().all())
        if customer_ids
        else []
    )
    customer_map = {c.id: c for c in customers}

    context: dict = {}
    for case in cases:
        customer = customer_map.get(case.customer_id) if case.customer_id else None
        context[case.id] = {
            "case_id": str(case.id),
            "case_status": case.status.value if hasattr(case.status, "value") else case.status,
            "case_risk_level": case.risk_level,
            "customer_name": customer.name if customer else None,
            "customer_email": customer.email if customer else None,
            "customer_phone": customer.phone if customer else None,
        }
    return context


@router.get("/payment-plans")
def list_payment_plans(db: Session = Depends(get_db)):
    """List all payment plans with case + customer context."""
    from app.models.payment_plan import PaymentPlan

    plans = list(
        db.execute(
            select(PaymentPlan).order_by(PaymentPlan.created_at.desc())
        ).scalars().all()
    )

    context = _bulk_case_customer_context(
        db, [plan.recovery_case_id for plan in plans]
    )
    degradations = _bulk_degradation_summary(db, plans)

    result = []
    for plan in plans:
        total_installments = plan.installments_paid + plan.installments_failed
        remaining_installments = max(plan.number_of_installments - plan.installments_paid, 0)
        degradation = degradations.get(plan.id, {
            "degraded": False,
            "fail_threshold": 0,
            "failed_count": plan.installments_failed,
            "strategy": None,
            "strategy_label": None,
        })
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
            "customer_message": plan.customer_message,
            "agreed_at": plan.agreed_at.isoformat() if plan.agreed_at else None,
            "first_payment_date": plan.first_payment_date.isoformat() if plan.first_payment_date else None,
            "last_payment_date": plan.last_payment_date.isoformat() if plan.last_payment_date else None,
            "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "degradation": degradation,
            "progress": {
                "paid_installments": plan.installments_paid,
                "failed_installments": plan.installments_failed,
                "total_installments": plan.number_of_installments,
                "remaining_installments": remaining_installments,
                "paid_amount": plan.amount_paid,
                "remaining_amount": plan.total_amount - plan.amount_paid,
                "percent_paid": round(
                    (plan.amount_paid / plan.total_amount) * 100, 1
                ) if plan.total_amount > 0 else 0.0,
            },
            **{k: v for k, v in context.get(plan.recovery_case_id, {}).items()},
        })

    return result


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    """List all conversations with case + customer context and last message."""
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage

    conversations = list(
        db.execute(
            select(Conversation).order_by(Conversation.created_at.desc())
        ).scalars().all()
    )

    message_rows = list(
        db.execute(
            select(ConversationMessage).order_by(ConversationMessage.created_at)
        ).scalars().all()
    )
    messages_by_conv: dict = {}
    for msg in message_rows:
        messages_by_conv.setdefault(msg.conversation_id, []).append(msg)

    context = _bulk_case_customer_context(
        db, [conv.recovery_case_id for conv in conversations]
    )

    result = []
    for conv in conversations:
        messages = messages_by_conv.get(conv.id, [])
        last = messages[-1] if messages else None
        result.append({
            "id": str(conv.id),
            "channel": conv.channel,
            "status": conv.status.value if hasattr(conv.status, "value") else conv.status,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            "message_count": len(messages),
            "outbound_count": sum(1 for m in messages if m.direction == "outbound"),
            "inbound_count": sum(1 for m in messages if m.direction == "inbound"),
            "last_message": {
                "direction": last.direction,
                "content": last.content,
                "created_at": last.created_at.isoformat() if last.created_at else None,
            } if last else None,
            "messages": [
                {
                    "id": str(m.id),
                    "direction": m.direction,
                    "content": m.content,
                    "message_type": m.message_type,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages[-50:]
            ],
            **{k: v for k, v in context.get(conv.recovery_case_id, {}).items()},
        })

    return result


@router.get("/invoices")
def list_invoices(db: Session = Depends(get_db)):
    """List all invoices with case + customer context."""
    from app.models.invoice import Invoice

    invoices = list(
        db.execute(
            select(Invoice).order_by(Invoice.created_at.desc())
        ).scalars().all()
    )

    context = _bulk_case_customer_context(
        db, [invoice.recovery_case_id for invoice in invoices]
    )

    result = []
    for invoice in invoices:
        result.append({
            "id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "amount": invoice.amount,
            "currency": invoice.currency,
            "description": invoice.description,
            "status": invoice.status,
            "issued_at": invoice.issued_at.isoformat() if invoice.issued_at else None,
            "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
            "viewed_at": invoice.viewed_at.isoformat() if invoice.viewed_at else None,
            "token_expires_at": invoice.token_expires_at.isoformat() if invoice.token_expires_at else None,
            "access_count": invoice.access_count,
            "delivered_via": invoice.delivered_via,
            "delivered_at": invoice.delivered_at.isoformat() if invoice.delivered_at else None,
            "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
            "secure_token": invoice.secure_token,
            **{k: v for k, v in context.get(invoice.recovery_case_id, {}).items() if k != "case_id"},
        })

    return result


# ============================================================
# PAYMENT DEGRADATION / MANDATE RETRY SEQUENCER
# ============================================================


def _degradation_summary(db: Session, plan) -> dict:
    """Lightweight degradation flag + reason for the plan list card."""
    from app.services.retry_sequencer import DEGRADATION_FAIL_THRESHOLD

    degraded = plan.installments_failed >= DEGRADATION_FAIL_THRESHOLD
    strategy = None
    if degraded:
        from app.services.retry_sequencer import _collect_failures
        failures = _collect_failures(db, plan.id)
        if any(r in ("mandate_declined", "autopay_failed", "upi_mandate_failed") for r in failures):
            strategy = "SPLIT_PLAN"
        else:
            strategy = "ALTERNATE_GATEWAY"
    return {
        "degraded": degraded,
        "fail_threshold": DEGRADATION_FAIL_THRESHOLD,
        "failed_count": plan.installments_failed,
        "strategy": strategy,
        "strategy_label": (
            "Rewarded split plan: 50% upfront + 50% in 14 days"
            if strategy == "SPLIT_PLAN"
            else "Alternate-gateway payment link" if strategy else None
        ),
    }


def _bulk_degradation_summary(db: Session, plans) -> dict:
    """Degradation summaries for many plans in a single FAILED query.

    Collects failure reasons for every degraded plan at once, then computes
    each plan's strategy locally — avoiding one _collect_failures query per
    plan (the N+1 pattern in the old list endpoint).
    """
    from app.models.installment import Installment
    from app.services.retry_sequencer import DEGRADATION_FAIL_THRESHOLD

    degraded_ids = {
        plan.id
        for plan in plans
        if plan.installments_failed >= DEGRADATION_FAIL_THRESHOLD
    }
    if not degraded_ids:
        return {}

    failures_by_plan: dict = {pid: [] for pid in degraded_ids}
    if degraded_ids:
        rows = db.execute(
            select(Installment).where(
                Installment.payment_plan_id.in_(degraded_ids),
                Installment.status == "FAILED",
            )
        ).scalars().all()
        for row in rows:
            failures_by_plan.setdefault(row.payment_plan_id, []).append(
                row.failure_reason or "unknown"
            )

    result: dict = {}
    for plan in plans:
        if plan.id not in degraded_ids:
            continue
        failures = failures_by_plan.get(plan.id, [])
        if any(r in ("mandate_declined", "autopay_failed", "upi_mandate_failed") for r in failures):
            strategy = "SPLIT_PLAN"
        else:
            strategy = "ALTERNATE_GATEWAY"
        result[plan.id] = {
            "degraded": True,
            "fail_threshold": DEGRADATION_FAIL_THRESHOLD,
            "failed_count": plan.installments_failed,
            "strategy": strategy,
            "strategy_label": (
                "Rewarded split plan: 50% upfront + 50% in 14 days"
                if strategy == "SPLIT_PLAN"
                else "Alternate-gateway payment link"
            ),
        }
    return result



@router.get("/plans/{plan_id}/retry-sequencer")
def get_plan_retry_sequencer(plan_id, db: Session = Depends(get_db)):
    """Get the payment-degradation & mandate retry sequencer for a plan.

    Detects failed UPI/Autopay mandates and returns the recommended
    degradation strategy (split plan vs alternate gateway) plus a
    timestamped retry/outreach timeline showing exactly WHEN each step
    will execute.
    """
    import uuid
    from fastapi import HTTPException
    from app.services.retry_sequencer import generate_retry_sequencer

    try:
        pid = uuid.UUID(str(plan_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan id")

    result = generate_retry_sequencer(db, pid)
    return {
        "plan_id": result.plan_id,
        "case_id": result.case_id,
        "degraded": result.degraded,
        "trigger_reason": result.trigger_reason,
        "strategy": result.strategy,
        "strategy_label": result.strategy_label,
        "split": result.split,
        "timeline": result.timeline,
        "blocked": result.blocked,
        "block_reason": result.block_reason,
    }


# ============================================================
# AUTONOMOUS SCHEDULER OPS
# ============================================================


@router.post("/autonomous/scheduler/run")
def run_autonomous_scheduler(db: Session = Depends(get_db)):
    """Run one background scheduler pass over all due actions.

    Polls for scheduled actions whose ``scheduled_for`` has passed and processes
    them through the full guardrail pipeline (terminal states, opt-out, dispute,
    max attempts, recovered payment all cancel the action before outreach). This
    is the same routine the long-lived background loop runs on its interval, and
    is exposed as a manual ops trigger for on-demand reconciliation.
    """
    from app.services.scheduler import process_due_actions

    results = process_due_actions(db)
    return {
        "total_due": results["total_due"],
        "executed": results["executed"],
        "cancelled": results["cancelled"],
        "skipped": results["skipped"],
        "details": results["details"],
    }