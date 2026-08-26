import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RevenueEvent(Base):
    # tracks failed payments and revenue events from razorpay
    __tablename__ = "revenue_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    # external_event_id is the razorpay payment/order id
    external_event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)  # like "payment_failed", "subscription_cancelled"
    amount: Mapped[int] = mapped_column(Integer)  # amount in paise
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(50), index=True)
    source: Mapped[str] = mapped_column(String(50))  # "razorpay" etc
    # using extra_data for metadata since "metadata" is reserved by sqlalchemy
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # relationships
    customer = relationship("Customer", back_populates="revenue_events")
    recovery_cases = relationship("RecoveryCase", back_populates="revenue_event")
