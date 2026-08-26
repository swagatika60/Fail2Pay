import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InvoiceStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class Invoice(Base):
    # invoice for each installment or payment
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    payment_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_plans.id"), index=True)
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[InvoiceStatus] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.PENDING, index=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # relationships
    payment_plan = relationship("PaymentPlan", back_populates="invoices")
