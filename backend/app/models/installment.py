import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InstallmentStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Installment(Base):
    # one installment in a payment plan
    __tablename__ = "installments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_plans.id"), index=True)
    installment_number: Mapped[int] = mapped_column(Integer)  # 1st, 2nd, 3rd etc
    amount: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[InstallmentStatus] = mapped_column(Enum(InstallmentStatus), default=InstallmentStatus.SCHEDULED, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # relationships
    payment_plan = relationship("PaymentPlan", back_populates="installments")
