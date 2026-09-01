"""List endpoints for Checkout Abandonments and Subscription Failures.

These endpoints provide the data for the frontend dashboard pages.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["checkout-subscription"])


@router.get("/checkout-abandonments")
def list_checkout_abandonments(db: Session = Depends(get_db)):
    """List all checkout abandonments with customer context."""
    from app.models.checkout import CheckoutAbandonment
    from app.models.customer import Customer

    rows = (
        db.execute(
            select(CheckoutAbandonment, Customer)
            .join(Customer, CheckoutAbandonment.customer_id == Customer.id, isouter=True)
            .order_by(CheckoutAbandonment.created_at.desc())
        )
        .all()
    )

    results = []
    for checkout, customer in rows:
        extra = checkout.extra_data or {}
        results.append({
            "id": str(checkout.id),
            "customer_id": str(checkout.customer_id),
            "customer_name": customer.name if customer else None,
            "customer_email": customer.email if customer else None,
            "customer_phone": customer.phone if customer else None,
            "cart_ref": checkout.cart_ref,
            "amount": checkout.amount,
            "currency": checkout.currency,
            "item_count": checkout.item_count,
            "source": checkout.source,
            "abandonment_reason": checkout.abandonment_reason,
            "cause": extra.get("cause", "unknown"),
            "status": checkout.status,
            "reengagement_count": checkout.reengagement_count,
            "reengagement_channel": checkout.reengagement_channel,
            "abandoned_at": checkout.abandoned_at.isoformat() if checkout.abandoned_at else None,
            "last_reengagement_at": checkout.last_reengagement_at.isoformat() if checkout.last_reengagement_at else None,
            "created_at": checkout.created_at.isoformat() if checkout.created_at else None,
            "recovery_case_id": str(checkout.recovery_case_id) if checkout.recovery_case_id else None,
        })

    return results


@router.get("/checkout-abandonments/summary")
def checkout_abandonments_summary(db: Session = Depends(get_db)):
    """Aggregate stats for checkout abandonments."""
    from app.models.checkout import CheckoutAbandonment

    total = db.execute(select(func.count(CheckoutAbandonment.id))).scalar() or 0
    total_amount = db.execute(select(func.coalesce(func.sum(CheckoutAbandonment.amount), 0))).scalar() or 0
    recovered = db.execute(
        select(func.count(CheckoutAbandonment.id)).where(CheckoutAbandonment.status == "recovered")
    ).scalar() or 0
    abandoned = db.execute(
        select(func.count(CheckoutAbandonment.id)).where(CheckoutAbandonment.status == "abandoned")
    ).scalar() or 0
    recovering = db.execute(
        select(func.count(CheckoutAbandonment.id)).where(CheckoutAbandonment.status == "recovering")
    ).scalar() or 0
    lost = db.execute(
        select(func.count(CheckoutAbandonment.id)).where(CheckoutAbandonment.status == "lost")
    ).scalar() or 0

    return {
        "total": total,
        "total_amount": total_amount,
        "recovered": recovered,
        "abandoned": abandoned,
        "recovering": recovering,
        "lost": lost,
        "recovery_rate": round(recovered / total * 100, 1) if total > 0 else 0,
    }


@router.get("/subscription-failures")
def list_subscription_failures(db: Session = Depends(get_db)):
    """List all subscription failures with customer context."""
    from app.models.subscription import SubscriptionFailure
    from app.models.customer import Customer

    rows = (
        db.execute(
            select(SubscriptionFailure, Customer)
            .join(Customer, SubscriptionFailure.customer_id == Customer.id, isouter=True)
            .order_by(SubscriptionFailure.created_at.desc())
        )
        .all()
    )

    results = []
    for sub, customer in rows:
        extra = sub.extra_data or {}
        results.append({
            "id": str(sub.id),
            "customer_id": str(sub.customer_id),
            "customer_name": customer.name if customer else None,
            "customer_email": customer.email if customer else None,
            "customer_phone": customer.phone if customer else None,
            "subscription_id": sub.subscription_id,
            "plan_id": sub.plan_id,
            "plan_name": sub.plan_name,
            "billing_cycle": sub.billing_cycle,
            "amount": sub.amount,
            "currency": sub.currency,
            "failure_code": sub.failure_code,
            "failure_reason": sub.failure_reason,
            "cause": extra.get("cause", "unknown"),
            "status": sub.status,
            "retry_count": sub.retry_count,
            "max_retries": sub.max_retries,
            "days_until_churn": sub.days_until_churn,
            "failed_at": sub.failed_at.isoformat() if sub.failed_at else None,
            "next_retry_at": sub.next_retry_at.isoformat() if sub.next_retry_at else None,
            "last_retry_at": sub.last_retry_at.isoformat() if sub.last_retry_at else None,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
            "recovery_case_id": str(sub.recovery_case_id) if sub.recovery_case_id else None,
        })

    return results


@router.get("/subscription-failures/summary")
def subscription_failures_summary(db: Session = Depends(get_db)):
    """Aggregate stats for subscription failures."""
    from app.models.subscription import SubscriptionFailure

    total = db.execute(select(func.count(SubscriptionFailure.id))).scalar() or 0
    total_amount = db.execute(select(func.coalesce(func.sum(SubscriptionFailure.amount), 0))).scalar() or 0
    failed = db.execute(
        select(func.count(SubscriptionFailure.id)).where(SubscriptionFailure.status == "failed")
    ).scalar() or 0
    retrying = db.execute(
        select(func.count(SubscriptionFailure.id)).where(SubscriptionFailure.status == "retrying")
    ).scalar() or 0
    recovered = db.execute(
        select(func.count(SubscriptionFailure.id)).where(SubscriptionFailure.status == "recovered")
    ).scalar() or 0
    churned = db.execute(
        select(func.count(SubscriptionFailure.id)).where(SubscriptionFailure.status == "churned")
    ).scalar() or 0

    return {
        "total": total,
        "total_amount": total_amount,
        "failed": failed,
        "retrying": retrying,
        "recovered": recovered,
        "churned": churned,
        "retention_rate": round(recovered / total * 100, 1) if total > 0 else 0,
    }
