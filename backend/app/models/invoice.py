import enum
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InvoiceStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    VIEWED = "VIEWED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


def generate_secure_token() -> str:
    """Generate a cryptographically secure token for invoice access."""
    return secrets.token_urlsafe(32)


class Invoice(Base):
    """Secure invoice for recovery cases.

    Each invoice has:
    - A unique invoice number (human-readable)
    - A secure token for expiring access URLs
    - Customer and payment details
    - Delivery tracking
    """

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recovery_cases.id"), nullable=True, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )

    # Invoice details
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    amount: Mapped[int] = mapped_column(Integer)  # in paise
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Customer info (snapshot at invoice creation time)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Status and dates
    status: Mapped[str] = mapped_column(
        String(50), default=InvoiceStatus.PENDING.value, index=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Secure access
    secure_token: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, default=generate_secure_token
    )
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    # Delivery tracking
    delivered_via: Mapped[str | None] = mapped_column(String(50), nullable=True)  # "whatsapp", "email"
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    recovery_case = relationship("RecoveryCase", back_populates="invoices")
    customer = relationship("Customer", back_populates="invoices")
