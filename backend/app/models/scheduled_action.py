import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ScheduledAction(Base):
    """Scheduled recovery action — stores delayed actions like reminders.

    Each action is scheduled for a future time and executed by the scheduler
    only after re-checking all stop conditions.
    """

    __tablename__ = "scheduled_actions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_cases.id"), index=True
    )
    action_type: Mapped[str] = mapped_column(
        String(100)
    )  # "initial_message", "reminder", "final_notice", "payment_check"
    attempt_number: Mapped[int] = mapped_column(Integer)  # which attempt in the sequence
    channel: Mapped[str] = mapped_column(String(50))  # "whatsapp", "email", "sms"
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # The wall-clock time at which the reminder was actually queued for sending
    # (distinct from scheduled_for which is the target delivery time).
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", index=True
    )  # "pending", "executed", "cancelled", "skipped"
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # relationships
    recovery_case = relationship("RecoveryCase", back_populates="scheduled_actions")
