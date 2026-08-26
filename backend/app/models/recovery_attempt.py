import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RecoveryAttempt(Base):
    # each time we try to recover money - this is one attempt
    __tablename__ = "recovery_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)  # 1st attempt, 2nd attempt etc
    channel: Mapped[str] = mapped_column(String(50))  # "whatsapp", "email", "sms"
    status: Mapped[str] = mapped_column(String(50), index=True)  # "sent", "delivered", "failed"
    result: Mapped[str | None] = mapped_column(String(50), nullable=True)  # "paid", "promised", "no_response"
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # relationships
    recovery_case = relationship("RecoveryCase", back_populates="recovery_attempts")
