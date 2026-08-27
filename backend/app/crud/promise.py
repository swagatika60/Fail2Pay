import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.promise import Promise, PromiseStatus
from app.schemas.promise import PromiseCreate


def create_promise(db: Session, data: PromiseCreate) -> Promise:
    """Create a new promise."""
    promise = Promise(**data.model_dump())
    db.add(promise)
    db.commit()
    db.refresh(promise)
    return promise


def get_promise(db: Session, promise_id: uuid.UUID) -> Promise | None:
    """Get a single promise by ID."""
    return db.execute(
        select(Promise).where(Promise.id == promise_id)
    ).scalar_one_or_none()


def get_active_promise_for_case(db: Session, case_id: uuid.UUID) -> Promise | None:
    """Get the active promise for a recovery case."""
    return db.execute(
        select(Promise).where(
            Promise.recovery_case_id == case_id,
            Promise.status == PromiseStatus.ACTIVE.value,
        )
    ).scalar_one_or_none()


def get_active_promise_for_customer(db: Session, customer_id: uuid.UUID) -> Promise | None:
    """Get the active promise for a customer."""
    return db.execute(
        select(Promise).where(
            Promise.customer_id == customer_id,
            Promise.status == PromiseStatus.ACTIVE.value,
        )
    ).scalar_one_or_none()


def get_promises_by_case(db: Session, case_id: uuid.UUID) -> list[Promise]:
    """Get all promises for a recovery case."""
    return list(
        db.execute(
            select(Promise)
            .where(Promise.recovery_case_id == case_id)
            .order_by(Promise.created_at.desc())
        ).scalars().all()
    )


def get_promises_by_customer(db: Session, customer_id: uuid.UUID) -> list[Promise]:
    """Get all promises for a customer."""
    return list(
        db.execute(
            select(Promise)
            .where(Promise.customer_id == customer_id)
            .order_by(Promise.created_at.desc())
        ).scalars().all()
    )


def mark_promise_fulfilled(
    db: Session,
    promise_id: uuid.UUID,
    amount: int,
) -> Promise | None:
    """Mark a promise as fulfilled."""
    promise = get_promise(db, promise_id)
    if promise:
        promise.status = PromiseStatus.FULFILLED.value
        promise.fulfilled_at = datetime.now(timezone.utc)
        promise.fulfilled_amount = amount
        db.commit()
        db.refresh(promise)
    return promise


def mark_promise_missed(db: Session, promise_id: uuid.UUID) -> Promise | None:
    """Mark a promise as missed."""
    promise = get_promise(db, promise_id)
    if promise:
        promise.status = PromiseStatus.MISSED.value
        promise.missed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(promise)
    return promise


def cancel_promise(
    db: Session,
    promise_id: uuid.UUID,
    reason: str = "customer_cancelled",
) -> Promise | None:
    """Cancel a promise."""
    promise = get_promise(db, promise_id)
    if promise:
        promise.status = PromiseStatus.CANCELLED.value
        promise.cancelled_at = datetime.now(timezone.utc)
        promise.cancellation_reason = reason
        db.commit()
        db.refresh(promise)
    return promise


def expire_promise(db: Session, promise_id: uuid.UUID) -> Promise | None:
    """Expire a promise."""
    promise = get_promise(db, promise_id)
    if promise:
        promise.status = PromiseStatus.EXPIRED.value
        db.commit()
        db.refresh(promise)
    return promise


def get_expired_promises(db: Session) -> list[Promise]:
    """Get all active promises that have expired."""
    now = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(Promise).where(
                Promise.status == PromiseStatus.ACTIVE.value,
                Promise.expires_at <= now,
            )
        ).scalars().all()
    )


def count_promises_by_status(
    db: Session, case_id: uuid.UUID, status: str
) -> int:
    """Count promises by status for a case."""
    result = db.execute(
        select(func.count(Promise.id)).where(
            Promise.recovery_case_id == case_id,
            Promise.status == status,
        )
    )
    return result.scalar() or 0


def get_dashboard_promises(
    db: Session,
    limit: int = 50,
) -> list[dict]:
    """Get promise data formatted for dashboard display."""
    promises = list(
        db.execute(
            select(Promise)
            .order_by(Promise.created_at.desc())
            .limit(limit)
        ).scalars().all()
    )

    return [
        {
            "id": str(p.id),
            "recovery_case_id": str(p.recovery_case_id),
            "customer_id": str(p.customer_id),
            "amount_promised": p.amount_promised,
            "currency": p.currency,
            "promised_date": p.promised_date.isoformat(),
            "expires_at": p.expires_at.isoformat(),
            "status": p.status,
            "fulfilled_at": p.fulfilled_at.isoformat() if p.fulfilled_at else None,
            "fulfilled_amount": p.fulfilled_amount,
            "missed_at": p.missed_at.isoformat() if p.missed_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in promises
    ]
