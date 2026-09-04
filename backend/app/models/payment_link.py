import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def generate_payment_link_token() -> str:
    """Generate a cryptographically secure token for a payment link."""
    return secrets.token_urlsafe(32)


class PaymentLink(Base):
    """A secure, expiring payment link for a recovery case.

    Each link carries its own public ``payment_link_id`` (used in the
    clickable URL) plus a backend-only secure token. Links are issued when the
    agent sends a pay-now card/invoice, and expire after ``expires_at`` so a
    stale link can never be reused after the balance is settled.
    """

    __tablename__ = "payment_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_cases.id"), index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )

    # Public link identifier used in the URL (/pay/{payment_link_id}).
    payment_link_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, default=generate_payment_link_token
    )
    # Backend-only token that authorizes server-side redemption — never exposed
    # in URLs to the customer.
    secure_token: Mapped[str] = mapped_column(
        String(100), unique=True, default=generate_payment_link_token
    )

    amount: Mapped[int] = mapped_column(Integer)  # in paise
    currency: Mapped[str] = mapped_column(String(10), default="INR")

    # Status and lifecycle
    status: Mapped[str] = mapped_column(
        String(50), default="ACTIVE", index=True
    )  # ACTIVE, USED, EXPIRED, CANCELLED
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    recovery_case = relationship("RecoveryCase", back_populates="payment_links")

    @property
    def url(self) -> str:
        from app.services.agent_engine import get_pay_host

        return f"{get_pay_host()}/pay/{self.payment_link_id}"


def build_payment_link_expiry() -> datetime:
    """Default expiry for a freshly issued payment link (7 days)."""
    return datetime.now(timezone.utc) + timedelta(days=7)
