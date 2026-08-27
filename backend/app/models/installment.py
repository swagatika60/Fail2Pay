import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InstallmentStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"  # Not yet due
    DUE = "DUE"  # Payment due now
    PAID = "PAID"  # Payment received
    FAILED = "FAILED"  # Payment failed
    CANCELLED = "CANCELLED"  # Installment cancelled
    OVERDUE = "OVERDUE"  # Payment missed deadline


class Installment(Base):
    """One installment in a payment plan.

    Tracks individual payment status and Razorpay transaction.
    """

    __tablename__ = "installments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_plans.id"), index=True
    )
    recovery_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recovery_cases.id"), nullable=True, index=True
    )

    # Installment details
    installment_number: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)  # in paise
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(10), default="INR")

    # Status
    status: Mapped[str] = mapped_column(
        String(50), default=InstallmentStatus.SCHEDULED.value, index=True
    )

    # Payment tracking
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_amount: Mapped[int] = mapped_column(Integer, default=0)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Razorpay integration
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Metadata
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    payment_plan = relationship("PaymentPlan", back_populates="installments")
