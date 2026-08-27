"""Analytics API endpoints for the Revenue Map dashboard.

Provides revenue metrics, recovery case lists, and case details.
All data comes from the database — nothing is hardcoded.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.customer import Customer
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.revenue_event import RevenueEvent
from app.schemas.analytics import (
    RecoveryCaseDetail,
    RecoveryCaseSummary,
    RevenueSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary", response_model=RevenueSummary)
def get_revenue_summary(db: Session = Depends(get_db)):
    """Get all revenue metrics for the dashboard.

    Returns real data from the database with no hardcoding.
    """
    return _compute_summary(db)


@router.get("/recovery-cases", response_model=list[RecoveryCaseSummary])
def list_recovery_cases(db: Session = Depends(get_db)):
    """List all recovery cases for the dashboard table."""
    try:
        cases = (
            db.query(RecoveryCase)
            .order_by(RecoveryCase.created_at.desc())
            .all()
        )
        result = []
        for case in cases:
            customer = db.query(Customer).filter(Customer.id == case.customer_id).first()
            result.append(
                RecoveryCaseSummary(
                    id=case.id,
                    customer_name=customer.name if customer else None,
                    customer_email=customer.email if customer else None,
                    original_amount=case.original_amount,
                    risk_level=case.risk_level,
                    status=case.status.value if hasattr(case.status, "value") else case.status,
                    recovered_amount=case.recovered_amount,
                    remaining_amount=case.remaining_amount,
                    attempt_count=case.attempt_count,
                    created_at=case.created_at,
                    updated_at=case.updated_at,
                )
            )
        return result
    finally:
        pass


@router.get("/recovery-cases/{case_id}", response_model=RecoveryCaseDetail)
def get_recovery_case_detail(case_id: UUID, db: Session = Depends(get_db)):
    """Get full details of a specific recovery case."""
    try:
        case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
        if not case:
            raise HTTPException(status_code=404, detail="Recovery case not found")

        customer = db.query(Customer).filter(Customer.id == case.customer_id).first()
        revenue_event = (
            db.query(RevenueEvent)
            .filter(RevenueEvent.id == case.revenue_event_id)
            .first()
        )

        # Get audit events for this case
        audit_events_raw = (
            db.query(AuditEvent)
            .filter(AuditEvent.recovery_case_id == case.id)
            .order_by(AuditEvent.created_at.desc())
            .all()
        )
        audit_events = [
            {
                "id": str(ae.id),
                "action": ae.action,
                "entity_type": ae.entity_type,
                "old_value": ae.old_value,
                "new_value": ae.new_value,
                "created_at": ae.created_at.isoformat() if ae.created_at else None,
            }
            for ae in audit_events_raw
        ]

        # Extract failure reason from revenue event metadata
        failure_reason = None
        if revenue_event and revenue_event.extra_data:
            failure_reason = revenue_event.extra_data.get("failure_reason")

        return RecoveryCaseDetail(
            id=case.id,
            customer_id=case.customer_id,
            customer_name=customer.name if customer else None,
            customer_email=customer.email if customer else None,
            customer_phone=customer.phone if customer else None,
            revenue_event_id=case.revenue_event_id,
            risk_level=case.risk_level,
            risk_reason=case.risk_reason,
            status=case.status.value if hasattr(case.status, "value") else case.status,
            original_amount=case.original_amount,
            recovered_amount=case.recovered_amount,
            remaining_amount=case.remaining_amount,
            attempt_count=case.attempt_count,
            max_attempts=case.max_attempts,
            recovery_started_at=case.recovery_started_at,
            recovery_deadline=case.recovery_deadline,
            closed_at=case.closed_at,
            created_at=case.created_at,
            updated_at=case.updated_at,
            event_type=revenue_event.event_type if revenue_event else None,
            source=revenue_event.source if revenue_event else None,
            currency=revenue_event.currency if revenue_event else "INR",
            failure_reason=failure_reason,
            audit_events=audit_events,
        )
    finally:
        pass


def _compute_summary(db: Session) -> RevenueSummary:
    """Compute revenue summary from database."""
    # Get all recovery cases grouped by status
    status_amounts: dict[str, int] = {}
    total_original = 0
    total_recovered = 0

    all_cases = db.query(RecoveryCase).all()
    for case in all_cases:
        status = case.status.value if hasattr(case.status, "value") else case.status
        total_original += case.original_amount
        total_recovered += case.recovered_amount
        status_amounts[status] = status_amounts.get(status, 0) + case.original_amount

    at_risk = status_amounts.get("AT_RISK", 0)
    recovery_in_progress = status_amounts.get("RECOVERY_IN_PROGRESS", 0)
    promised = status_amounts.get("PROMISED", 0)
    scheduled = status_amounts.get("SCHEDULED", 0)
    partially_recovered = status_amounts.get("PARTIALLY_RECOVERED", 0)
    recovered = status_amounts.get("RECOVERED", 0)
    lost = status_amounts.get("LOST", 0)

    # Expected = everything (all cases represent expected revenue)
    expected_revenue = total_original

    # Collected = what's actually recovered
    collected_revenue = total_recovered

    # Revenue remaining
    revenue_remaining = max(0, total_original - total_recovered)

    # Recovery rate: recovered / at_risk (handle division by zero)
    at_risk_total = at_risk + partially_recovered  # at risk includes partially recovered
    recovery_rate = (total_recovered / at_risk_total) if at_risk_total > 0 else 0.0

    return RevenueSummary(
        expected_revenue=expected_revenue,
        collected_revenue=collected_revenue,
        revenue_at_risk=at_risk,
        recovery_in_progress=recovery_in_progress,
        promised_revenue=promised,
        scheduled_revenue=scheduled,
        partially_recovered=partially_recovered,
        recovered_revenue=recovered,
        lost_revenue=lost,
        total_revenue=total_original,
        revenue_recovered=total_recovered,
        revenue_remaining=revenue_remaining,
        recovery_rate=round(recovery_rate, 4),
    )
