"""Simulation API endpoints.

Run batch simulations and view results.
All data is clearly marked as DEMO_SIMULATION.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


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
