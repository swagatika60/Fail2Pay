import enum
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EmailDeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    FAILED = "failed"


class EmailType(str, enum.Enum):
    FAILED_PAYMENT = "failed_payment"
    PAYMENT_RETRY = "payment_retry"
    INVOICE = "invoice"
    PAYMENT_PLAN_CONFIRMATION = "payment_plan_confirmation"
    PROMISE_TO_PAY_REMINDER = "promise_to_pay_reminder"
    PAYMENT_SUCCESS = "payment_success"


class SentEmail(Base):
    """Tracks every email sent through the system.

    Every email is logged regardless of delivery outcome.
    """

    __tablename__ = "sent_emails"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recovery_cases.id"), nullable=True, index=True
    )
    recipient_email: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    email_type: Mapped[str] = mapped_column(String(100), index=True)
    delivery_status: Mapped[str] = mapped_column(
        String(50), default=EmailDeliveryStatus.PENDING.value, index=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_response: Mapped[dict | None] = mapped_column("provider_response", JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # relationships
    recovery_case = relationship("RecoveryCase", back_populates="sent_emails")
