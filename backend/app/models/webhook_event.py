import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebhookEvent(Base):
    """Tracks processed webhook event IDs for idempotency.

    Before processing any webhook, we check if the event ID already exists here.
    If it does, we skip processing to avoid duplicate side effects.
    """

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Razorpay's unique webhook event ID (e.g. "evt_abc123")
    event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # The event type (e.g. "payment.failed", "payment.captured")
    event_type: Mapped[str] = mapped_column(String(100))
    # Razorpay payment ID if available
    payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
