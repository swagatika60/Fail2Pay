"""Simulation API endpoints.

Run batch simulations and view results.
All data is clearly marked as DEMO_SIMULATION.
"""

import logging
import random
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


INDIAN_NAMES = [
    ("Rahul", "Sharma"), ("Priya", "Patel"), ("Amit", "Kumar"),
    ("Neha", "Gupta"), ("Rohan", "Singh"), ("Anjali", "Verma"),
    ("Vikram", "Reddy"), ("Pooja", "Nair"), ("Arjun", "Malhotra"),
    ("Kavita", "Joshi"),
]

FAILURE_REASONS = [
    "Insufficient funds",
    "Card expired",
    "Bank declined transaction",
    "Payment gateway timeout",
    "Authentication failed",
    "Daily limit exceeded",
]


@router.post("/run")
def run_simulation(db: Session = Depends(get_db)):
    """Run the batch simulation with 100 controlled test transactions.

    Creates demo data marked as DEMO_SIMULATION.
    Returns simulation results and analytics.
    """
    from app.services.simulation import run_simulation as _run_batch

    try:
        results = _run_batch(db)
        return results
    except Exception as e:
        logger.error("Simulation failed: %s", e, exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Simulation failed: {e}",
        ) from e


class SingleCaseRequest(BaseModel):
    amount: int = Field(0, description="Amount in paise (0 = random)")
    name: str | None = Field(None, description="Customer name (0 = random)")


@router.post("/single")
def simulate_single_case(
    body: SingleCaseRequest | None = None,
    db: Session = Depends(get_db),
):
    """Create a single persisted simulation case in the database.

    Unlike the dashboard's client-side mock, this creates real DB rows
    (Customer → RevenueEvent → RecoveryCase → AuditEvent → AgentSteps)
    so the case survives page refreshes and can be navigated to from
    the cases list.

    Returns the case_id plus basic summary fields so the frontend can
    immediately link to /case/{case_id}.
    """
    from app.crud.customer import create_customer
    from app.crud.recovery_case import create_recovery_case
    from app.crud.revenue_event import create_revenue_event
    from app.models.recovery_case import RecoveryCase, RecoveryStatus
    from app.schemas.customer import CustomerCreate
    from app.schemas.recovery_case import RecoveryCaseCreate
    from app.schemas.revenue_event import RevenueEventCreate
    from app.services import agent_steps
    from app.services.recovery_settings import get_or_create
    from app.services.revenue_risk import assess_risk

    now = datetime.now(timezone.utc)

    # --- Determine customer info ---
    name_tuple = random.choice(INDIAN_NAMES)
    customer_name = body.name if body and body.name else f"{name_tuple[0]} {name_tuple[1]}"
    email = f"{name_tuple[0].lower()}.{name_tuple[1].lower()}_{uuid.uuid4().hex[:8]}@gmail.com"
    phone = f"+91{random.randint(7000000000, 9999999999)}"
    # ``body.amount`` is paise (see SingleCaseRequest docstring) — never scale
    # an explicit amount. Only the random fallback (rupees) is converted.
    if body and body.amount and body.amount > 0:
        amount = body.amount
    else:
        amount = random.choice([499, 999, 1999, 4999, 9999, 14999]) * 100

    # --- Create customer ---
    customer = create_customer(
        db,
        data=CustomerCreate(
            external_id=f"DEMO_SIMULATION_sim_{uuid.uuid4().hex[:12]}",
            email=email,
            phone=phone,
            name=customer_name,
        ),
    )

    # --- Create revenue event ---
    failure_reason = random.choice(FAILURE_REASONS)
    revenue_event = create_revenue_event(
        db,
        data=RevenueEventCreate(
            customer_id=customer.id,
            external_event_id=f"pay_DEMO_SINGLE_{uuid.uuid4().hex[:8]}",
            event_type="payment_failed",
            amount=amount,
            currency="INR",
            status="failed",
            source="razorpay",
            extra_data={
                "simulation": True,
                "scenario": "single_sim",
                "failure_reason": failure_reason,
                "method": random.choice(["card", "upi", "netbanking", "wallet"]),
            },
        ),
    )

    # --- Risk assessment ---
    assessment = assess_risk(
        db=db,
        customer_id=str(customer.id),
        revenue_event_id=str(revenue_event.id),
        event_type="payment_failed",
        amount=amount,
        extra_data={"failure_reason": failure_reason},
    )

    # --- Create recovery case ---
    merchant_settings = get_or_create(db)
    max_attempts = merchant_settings.max_recovery_attempts

    recovery_case = create_recovery_case(
        db,
        data=RecoveryCaseCreate(
            customer_id=customer.id,
            revenue_event_id=revenue_event.id,
            risk_level=assessment.risk_level,
            risk_reason=assessment.risk_reason,
            original_amount=amount,
            remaining_amount=amount,
            max_attempts=max_attempts,
        ),
    )
    recovery_case.status = RecoveryStatus.AT_RISK
    recovery_case.extra_data = {
        "simulation": True,
        "scenario": "single_sim",
        "root_cause": "PAYMENT_FAILURE",
    }
    db.commit()
    db.refresh(recovery_case)

    # --- Audit events ---
    # Domain events (same as the webhook path) so the policy trace carries the
    # trigger (REVENUE_DETECTED / RISK_DETECTED) layer, not just a generic
    # "created" row.
    from app.services.audit_logger import (
        log_revenue_detected,
        log_risk_detected,
    )

    log_revenue_detected(
        db,
        recovery_case.id,
        amount=amount,
        payment_id=revenue_event.external_event_id,
        failure_reason=failure_reason,
    )
    log_risk_detected(
        db,
        recovery_case.id,
        risk_level=assessment.risk_level,
        risk_reason=assessment.risk_reason,
        amount=amount,
    )

    # --- Agent reasoning steps ---
    agent_steps.emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=agent_steps.AgentStage.TRIGGER,
        label="Trigger Received",
        detail=f"payment.failed · {failure_reason}",
        confidence=1.0,
        extra={"amount": amount, "method": "simulated"},
    )
    agent_steps.emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=agent_steps.AgentStage.DIAGNOSIS,
        label="Root Cause: Payment Failure",
        detail=f"Simulated payment failure — {failure_reason}",
        confidence=0.92,
        extra={"failure_reason": failure_reason},
    )
    agent_steps.emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=agent_steps.AgentStage.POLICY,
        label="Policy Check: Recoverable",
        detail=f"risk={assessment.risk_level} · recoverable={assessment.is_recoverable}",
        confidence=1.0,
        extra={"risk_level": assessment.risk_level},
    )

    # --- Initiate recovery ---
    from app.services.orchestrator import initiate_recovery

    recovery_result = initiate_recovery(db, recovery_case.id)
    action_label = {
        "initiated": "Recovery Initiated: WhatsApp",
        "skipped": "Policy Blocked: Skipped",
    }.get(recovery_result.get("status"), "Action Dispatched")

    agent_steps.emit_case_step(
        db,
        case_id=str(recovery_case.id),
        stage=agent_steps.AgentStage.ACTION,
        label=action_label,
        detail=f"status={recovery_result.get('status')}",
        confidence=0.98,
        extra={"recovery_result": recovery_result},
    )

    logger.info(
        "Single simulation case created: case=%s amount=%d customer=%s",
        recovery_case.id, amount, customer_name,
    )

    return {
        "case_id": str(recovery_case.id),
        "customer_name": customer_name,
        "original_amount": amount,
        "risk_level": assessment.risk_level,
        "status": "AT_RISK",
    }


@router.get("/analytics")
def get_simulation_analytics(db: Session = Depends(get_db)):
    """Get analytics from the simulation data.

    Only counts DEMO_SIMULATION data.
    """
    from app.services.simulation import _compute_simulation_analytics

    analytics = _compute_simulation_analytics(db)
    return analytics


@router.get("/impact-ledger")
def get_verified_impact_ledger(db: Session = Depends(get_db)):
    """Get the Verified Impact Ledger for the demo simulation.

    Shows the recovery pipeline funnel (At Risk -> Intervention Dispatched
    -> Promise Captured -> Verified Recovered) plus a per-case ledger.

    Only DEMO_SIMULATION data is considered, and only verified captured
    payments count as recovered revenue.
    """
    from app.services.simulation import compute_verified_impact_ledger

    return compute_verified_impact_ledger(db)


@router.delete("/reset")
def reset_simulation_data(db: Session = Depends(get_db)):
    """Remove all DEMO_SIMULATION data from the database.

    Only deletes data where extra_data->simulation = True.
    """
    from app.models.recovery_case import RecoveryCase
    from app.models.revenue_event import RevenueEvent
    from app.models.customer import Customer
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage
    from app.models.audit_event import AuditEvent
    from app.models.email import SentEmail
    from app.models.invoice import Invoice
    from app.models.payment import Payment
    from app.models.payment_plan import PaymentPlan
    from app.models.promise import Promise
    from app.models.installment import Installment
    from app.models.recovery_attempt import RecoveryAttempt
    from app.models.scheduled_action import ScheduledAction
    from sqlalchemy import delete, select

    # Find demo customers
    demo_customers = list(
        db.execute(
            select(Customer).where(
                Customer.external_id.like("%DEMO_SIMULATION%")
            )
        ).scalars().all()
    )

    demo_customer_ids = [c.id for c in demo_customers]
    demo_case_ids = select(RecoveryCase.id).where(
        RecoveryCase.customer_id.in_(demo_customer_ids)
    ) if demo_customer_ids else select(RecoveryCase.id).where(False)

    def count(*statements) -> int:
        total = 0
        for statement in statements:
            result = db.execute(statement)
            total += result.rowcount or 0
        return total

    statements = [
        delete(AuditEvent).where(AuditEvent.recovery_case_id.in_(demo_case_ids)),
        delete(ConversationMessage).where(
            ConversationMessage.conversation_id.in_(
                select(Conversation.id).where(
                    Conversation.recovery_case_id.in_(demo_case_ids)
                )
            )
        ),
        delete(Conversation).where(Conversation.recovery_case_id.in_(demo_case_ids)),
        delete(RecoveryAttempt).where(RecoveryAttempt.recovery_case_id.in_(demo_case_ids)),
        delete(SentEmail).where(SentEmail.recovery_case_id.in_(demo_case_ids)),
        delete(Invoice).where(Invoice.recovery_case_id.in_(demo_case_ids)),
        delete(Promise).where(Promise.recovery_case_id.in_(demo_case_ids)),
        delete(ScheduledAction).where(ScheduledAction.recovery_case_id.in_(demo_case_ids)),
        delete(Installment).where(Installment.recovery_case_id.in_(demo_case_ids)),
        delete(Payment).where(Payment.recovery_case_id.in_(demo_case_ids)),
        delete(PaymentPlan).where(PaymentPlan.recovery_case_id.in_(demo_case_ids)),
        delete(RecoveryCase).where(RecoveryCase.customer_id.in_(demo_customer_ids)),
        delete(RevenueEvent).where(RevenueEvent.customer_id.in_(demo_customer_ids)),
        delete(Customer).where(Customer.id.in_(demo_customer_ids)),
    ]

    audit_events, messages, convs, attempts, emails, invoices, promises, actions = (
        count(statements[0]),
        count(statements[1]),
        count(statements[2]),
        count(statements[3]),
        count(statements[4]),
        count(statements[5]),
        count(statements[6]),
        count(statements[7]),
    )
    installments, payments, plans, cases, events = (
        count(statements[8]),
        count(statements[9]),
        count(statements[10]),
        count(statements[11]),
        count(statements[12]),
    )

    db.commit()

    return {
        "status": "reset",
        "deleted": {
            "customers": len(demo_customers),
            "cases": cases,
            "events": events,
            "conversations": convs,
            "messages": messages,
            "audit_events": audit_events,
            "payments": payments,
            "plans": plans,
            "installments": installments,
            "recovery_attempts": attempts,
            "emails": emails,
            "invoices": invoices,
            "promises": promises,
            "scheduled_actions": actions,
        },
    }
