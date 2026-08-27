import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# all possible states for a recovery case
class RecoveryStatus(str, enum.Enum):
    AT_RISK = "AT_RISK"
    RECOVERY_IN_PROGRESS = "RECOVERY_IN_PROGRESS"
    PROMISED = "PROMISED"
    SCHEDULED = "SCHEDULED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    RECOVERED = "RECOVERED"
    LOST = "LOST"
    STOPPED = "STOPPED"


class RecoveryCase(Base):
    # main recovery case - tracks the whole recovery process for a failed payment
    __tablename__ = "recovery_cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    revenue_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("revenue_events.id"), index=True)
    risk_level: Mapped[str] = mapped_column(String(20), index=True)  # "high", "medium", "low"
    risk_reason: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[RecoveryStatus] = mapped_column(Enum(RecoveryStatus), default=RecoveryStatus.AT_RISK, index=True)
    original_amount: Mapped[int] = mapped_column(Integer)  # how much failed
    recovered_amount: Mapped[int] = mapped_column(Integer, default=0)  # how much we got back
    remaining_amount: Mapped[int] = mapped_column(Integer)  # still need to recover
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)  # how many times we tried
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)  # stop after this many tries
    recovery_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # relationships
    customer = relationship("Customer", back_populates="recovery_cases")
    revenue_event = relationship("RevenueEvent", back_populates="recovery_cases")
    recovery_attempts = relationship("RecoveryAttempt", back_populates="recovery_case")
    conversations = relationship("Conversation", back_populates="recovery_case")
    payment_plans = relationship("PaymentPlan", back_populates="recovery_case")
    audit_events = relationship("AuditEvent", back_populates="recovery_case")
    scheduled_actions = relationship("ScheduledAction", back_populates="recovery_case")
    sent_emails = relationship("SentEmail", back_populates="recovery_case")
    invoices = relationship("Invoice", back_populates="recovery_case")
    promises = relationship("Promise", back_populates="recovery_case")
