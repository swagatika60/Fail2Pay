import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Payment(Base):
    """A verified captured payment against a recovery case.

    This is the ground truth for *actually recovered money*:
    - only payments with ``status == "captured"`` count as recovered revenue
    - a customer *message* ("I'll pay") is never recorded here — only money
      that has genuinely moved.

    Mirrors the Razorpay payment object: ``pay_<id>``, amount, method.
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_cases.id"), index=True
    )
    razorpay_payment_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Payment details
    amount: Mapped[int] = mapped_column(Integer)  # in paise
    currency: Mapped[str] = mapped_column(String(10), default="INR")

    # Verification — only "captured" counts as recovered money
    status: Mapped[str] = mapped_column(String(20), default="created", index=True)
    method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    recovery_case = relationship("RecoveryCase", back_populates="payments")