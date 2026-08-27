from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.webhook_event import WebhookEvent


def get_webhook_event_by_event_id(db: Session, event_id: str) -> WebhookEvent | None:
    """Check if a webhook event has already been processed."""
    return (
        db.execute(
            select(WebhookEvent).where(WebhookEvent.event_id == event_id)
        ).scalar_one_or_none()
    )


def store_webhook_event(
    db: Session, event_id: str, event_type: str, payment_id: str | None = None
) -> WebhookEvent:
    """Store a processed webhook event for idempotency tracking."""
    webhook_event = WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        payment_id=payment_id,
    )
    db.add(webhook_event)
    db.commit()
    db.refresh(webhook_event)
    return webhook_event
