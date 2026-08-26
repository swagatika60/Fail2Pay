import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PaymentPlanStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DEFAULTED = "DEFAULTED"


class PaymentPlan(Base):
    # payment plan - split the failed payment into installments
    __tablename__ = "payment_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    total_amount: Mapped[int] = mapped_column(Integer)
    number_of_installments: Mapped[int] = mapped_column(Integer)
    frequency: Mapped[str] = mapped_column(String(20))  # "weekly", "monthly" etc
    status: Mapped[PaymentPlanStatus] = mapped_column(Enum(PaymentPlanStatus), default=PaymentPlanStatus.PROPOSED, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # relationships
    recovery_case = relationship("RecoveryCase", back_populates="payment_plans")
    installments = relationship("Installment", back_populates="payment_plan")
    invoices = relationship("Invoice", back_populates="payment_plan")
