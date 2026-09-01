"""Subscription Failure Model.

Tracks subscription payment failures with retry state and recovery
workflow. Distinct from mandate_drop — covers the full subscription
lifecycle: renewal failures, downgrade attempts, churn risk.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SubscriptionFailure(Base):
    """A subscription whose renewal payment failed.

    Captures the subscription context (plan, billing cycle, renewal date)
    so the recovery engine can offer the right intervention: retry, downgrade,
    or EMI split.
    """

    __tablename__ = "subscription_failures"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), index=True
    )
    recovery_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recovery_cases.id"), nullable=True, index=True
    )

    # Subscription details
    subscription_id: Mapped[str] = mapped_column(String(255), index=True)
    plan_id: Mapped[str | None] = mapped_column(String(255))
    plan_name: Mapped[str | None] = mapped_column(String(255))
    billing_cycle: Mapped[str | None] = mapped_column(String(50))  # monthly, yearly

    # Payment failure
    amount: Mapped[int] = mapped_column(Integer)  # renewal amount in paise
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Renewal context
    renewal_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_billing_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    days_until_churn: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    last_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(30), default="failed"
    )  # failed, retrying, recovered, churned, cancelled

    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    customer = relationship("Customer", back_populates="subscription_failures")
    recovery_case = relationship("RecoveryCase", back_populates="subscription_failure")
