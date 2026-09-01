"""Checkout Abandonment Model.

Tracks cart abandonment events with re-engagement state.
Links to a RecoveryCase for the full recovery workflow.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CheckoutAbandonment(Base):
    """A cart abandoned during checkout, before payment was attempted.

    Records the cart value, abandonment context, and tracks re-engagement
    attempts through the recovery pipeline.
    """

    __tablename__ = "checkout_abandonments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), index=True
    )
    recovery_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recovery_cases.id"), nullable=True, index=True
    )

    # Cart details
    cart_ref: Mapped[str] = mapped_column(String(255), index=True)
    amount: Mapped[int] = mapped_column(Integer)  # cart total in paise
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    item_count: Mapped[int] = mapped_column(Integer, default=1)

    # Abandonment context
    abandoned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    abandonment_reason: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(
        String(50), default="checkout"
    )  # checkout, cart_page, payment_page

    # Re-engagement tracking
    reengagement_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reengagement_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reengagement_channel: Mapped[str | None] = mapped_column(
        String(50)
    )  # whatsapp, email, sms

    # Status
    status: Mapped[str] = mapped_column(
        String(30), default="abandoned"
    )  # abandoned, recovering, recovered, lost

    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    customer = relationship("Customer", back_populates="checkout_abandonments")
    recovery_case = relationship("RecoveryCase", back_populates="checkout_abandonment")
