import uuid

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.email import SentEmail, EmailDeliveryStatus
from app.schemas.email import SentEmailCreate


def create_sent_email(db: Session, data: SentEmailCreate) -> SentEmail:
    """Create a new sent email record."""
    email = SentEmail(**data.model_dump())
    db.add(email)
    db.commit()
    db.refresh(email)
    return email


def get_sent_email(db: Session, email_id: uuid.UUID) -> SentEmail | None:
    """Get a single sent email by ID."""
    return db.execute(
        select(SentEmail).where(SentEmail.id == email_id)
    ).scalar_one_or_none()


def get_emails_by_case(db: Session, case_id: uuid.UUID) -> list[SentEmail]:
    """Get all sent emails for a recovery case."""
    return list(
        db.execute(
            select(SentEmail)
            .where(SentEmail.recovery_case_id == case_id)
            .order_by(SentEmail.created_at.desc())
        ).scalars().all()
    )


def get_emails_by_recipient(db: Session, email: str) -> list[SentEmail]:
    """Get all sent emails to a recipient."""
    return list(
        db.execute(
            select(SentEmail)
            .where(SentEmail.recipient_email == email)
            .order_by(SentEmail.created_at.desc())
        ).scalars().all()
    )


def update_delivery_status(
    db: Session,
    email_id: uuid.UUID,
    status: str,
    provider_message_id: str | None = None,
    provider_response: dict | None = None,
    error_message: str | None = None,
) -> SentEmail | None:
    """Update the delivery status of a sent email."""
    from datetime import datetime, timezone

    email = get_sent_email(db, email_id)
    if email:
        email.delivery_status = status
        if provider_message_id:
            email.provider_message_id = provider_message_id
        if provider_response:
            email.provider_response = provider_response
        if error_message:
            email.error_message = error_message
        if status == "sent":
            email.sent_at = datetime.now(timezone.utc)
        elif status == "delivered":
            email.delivered_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(email)
    return email


def count_emails_by_case_and_type(
    db: Session, case_id: uuid.UUID, email_type: str
) -> int:
    """Count how many emails of a type have been sent for a case."""
    result = db.execute(
        select(func.count(SentEmail.id)).where(
            SentEmail.recovery_case_id == case_id,
            SentEmail.email_type == email_type,
            SentEmail.delivery_status.in_(["sent", "delivered"]),
        )
    )
    return result.scalar() or 0


def cancel_pending_emails_for_case(db: Session, case_id: uuid.UUID) -> int:
    """Cancel all queued (PENDING) emails for a recovery case.

    Called when a recovery case settles or is stopped so no stale reminder /
    retry email is dispatched after the outcome is already known. Returns the
    number of emails that were cancelled.
    """
    from datetime import datetime, timezone

    result = db.execute(
        select(SentEmail.id).where(
            SentEmail.recovery_case_id == case_id,
            SentEmail.delivery_status == EmailDeliveryStatus.PENDING.value,
        )
    )
    ids = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    for email_id in ids:
        email = db.get(SentEmail, email_id)
        if email:
            email.delivery_status = EmailDeliveryStatus.CANCELLED.value
            email.updated_at = now
    db.commit()
    return len(ids)
