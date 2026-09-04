from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.recovery_case import RecoveryCase
from app.models.payment_link import PaymentLink, build_payment_link_expiry


def create_payment_link(
    db: Session,
    recovery_case_id,
    amount: int,
    currency: str = "INR",
    expires_at: datetime | None = None,
) -> PaymentLink:
    """Issue a new secure payment link for a recovery case."""
    case = db.get(RecoveryCase, recovery_case_id)
    link = PaymentLink(
        recovery_case_id=recovery_case_id,
        customer_id=case.customer_id if case else None,
        amount=amount,
        currency=currency,
        expires_at=expires_at or build_payment_link_expiry(),
        status="ACTIVE",
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def get_payment_link_by_id(db: Session, payment_link_id: str) -> PaymentLink | None:
    """Fetch a payment link by its public payment_link_id."""
    return db.execute(
        select(PaymentLink).where(PaymentLink.payment_link_id == payment_link_id)
    ).scalar_one_or_none()


def get_active_links_for_case(db: Session, recovery_case_id) -> list[PaymentLink]:
    """Return all ACTIVE, non-expired links for a recovery case."""
    now = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(PaymentLink).where(
                PaymentLink.recovery_case_id == recovery_case_id,
                PaymentLink.status == "ACTIVE",
                PaymentLink.expires_at >= now,
            )
        ).scalars().all()
    )


def mark_link_used(db: Session, payment_link_id: str) -> PaymentLink | None:
    """Mark an ACTIVE link as USED once its payment is captured."""
    link = get_payment_link_by_id(db, payment_link_id)
    if not link:
        return None
    link.status = "USED"
    link.used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(link)
    return link


def expire_stale_links_for_case(db: Session, recovery_case_id) -> int:
    """Expire all ACTIVE links for a case (e.g. when the case settles/stopped).

    Returns the number of links expired so no stale payment link can be reused
    after the outcome is known.
    """
    links = get_active_links_for_case(db, recovery_case_id)
    if not links:
        return 0
    now = datetime.now(timezone.utc)
    for link in links:
        link.status = "EXPIRED"
        link.updated_at = now
    db.commit()
    return len(links)
