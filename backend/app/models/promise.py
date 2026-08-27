import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PromiseStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"  # Promise is active, waiting for payment
    FULFILLED = "FULFILLED"  # Payment received within promised window
    MISSED = "MISSED"  # Payment not received by promised date
    BROKEN = "BROKEN"  # Promise broken — escalated to payment plan or reminder
    CANCELLED = "CANCELLED"  # Promise cancelled (customer stopped, etc.)
    EXPIRED = "EXPIRED"  # Promise window expired without payment


class Promise(Base):
    """Tracks customer payment promises.

    When a customer says "I'll pay tomorrow", a Promise is created.
    The system pauses generic reminders while the promise is active.
    If the promised payment doesn't occur, recovery resumes.
    """

    __tablename__ = "promises"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_cases.id"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), index=True
    )

    # Promise details
    amount_promised: Mapped[int] = mapped_column(Integer)  # amount in paise
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    promised_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    promise_window_hours: Mapped[int] = mapped_column(Integer, default=72)  # grace period
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Customer message (what they said)
    customer_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(50), default=PromiseStatus.ACTIVE.value, index=True
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_amount: Mapped[int] = mapped_column(Integer, default=0)
    missed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Metadata
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    recovery_case = relationship("RecoveryCase", back_populates="promises")
    customer = relationship("Customer", back_populates="promises")
