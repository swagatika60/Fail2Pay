import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PaymentPlanStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"  # Plan presented, waiting for customer agreement
    ACCEPTED = "ACCEPTED"  # Customer agreed, plan is active
    ACTIVE = "ACTIVE"  # Payments being collected
    COMPLETED = "COMPLETED"  # All installments paid
    CANCELLED = "CANCELLED"  # Plan cancelled by customer/merchant
    DEFAULTED = "DEFAULTED"  # Too many missed installments


class PaymentPlan(Base):
    """Payment plan — splits failed payment into installments.

    Flow:
    1. AI detects PAYMENT_PLAN_REQUEST
    2. Check merchant policy (allowed frequencies, min/max installments)
    3. Calculate permitted plans
    4. Present options to customer
    5. Customer agrees → ACCEPTED
    6. Create installment records
    7. Schedule installment reminders
    8. Track each installment
    9. All paid → COMPLETED → RecoveryCase = RECOVERED
    """

    __tablename__ = "payment_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_cases.id"), index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )

    # Plan details
    total_amount: Mapped[int] = mapped_column(Integer)  # in paise
    installment_amount: Mapped[int] = mapped_column(Integer)  # in paise
    number_of_installments: Mapped[int] = mapped_column(Integer)
    frequency: Mapped[str] = mapped_column(String(20))  # "weekly", "biweekly", "monthly"
    currency: Mapped[str] = mapped_column(String(10), default="INR")

    # Dates
    first_payment_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_payment_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        String(50), default=PaymentPlanStatus.PROPOSED.value, index=True
    )

    # Payment tracking
    amount_paid: Mapped[int] = mapped_column(Integer, default=0)
    installments_paid: Mapped[int] = mapped_column(Integer, default=0)
    installments_failed: Mapped[int] = mapped_column(Integer, default=0)

    # Customer agreement
    customer_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Razorpay integration
    razorpay_plan_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Metadata
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    recovery_case = relationship("RecoveryCase", back_populates="payment_plans")
    installments = relationship("Installment", back_populates="payment_plan", order_by="Installment.installment_number")
