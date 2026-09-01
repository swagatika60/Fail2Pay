"""B2B Receivable Invoice model.

Tracks outstanding B2B invoices with due dates, overdue detection,
and escalation tier management. Unlike the existing Invoice model
(which tracks per-recovery-case invoices), this model represents
the merchant's accounts receivable ledger — invoices issued to
their business customers that may go overdue.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReceivableStatus(str, enum.Enum):
    """Lifecycle states for a B2B receivable invoice."""

    PENDING = "PENDING"  # Not yet due
    DUE = "DUE"  # Due date arrived, not yet overdue
    OVERDUE = "OVERDUE"  # Past due date
    IN_ESCALATION = "IN_ESCALATION"  # Actively being chased
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"  # Fully paid
    PARTIALLY_PAID = "PARTIALLY_PAID"  # Partial payment received
    WRITTEN_OFF = "WRITTEN_OFF"  # Deemed uncollectible
    DISPUTED = "DISPUTED"  # Customer disputes the invoice


class EscalationTier(str, enum.Enum):
    """Escalation tiers for overdue receivables.

    Tiers progress automatically as the invoice ages past its due date.
    Each tier uses progressively firmer language and higher-stakes actions.
    """

    NONE = "NONE"  # Not yet overdue or just became overdue
    FRIENDLY_REMINDER = "FRIENDLY_REMINDER"  # 1-7 days overdue
    FORMAL_NOTICE = "FORMAL_NOTICE"  # 8-30 days overdue
    MANAGEMENT_ESCALATION = "MANAGEMENT_ESCALATION"  # 31-60 days overdue
    FINAL_DEMAND = "FINAL_DEMAND"  # 61-90 days overdue
    LEGAL_COLLECTION = "LEGAL_COLLECTION"  # 90+ days overdue


# Escalation tier thresholds (days overdue)
ESCALATION_THRESHOLDS = {
    EscalationTier.FRIENDLY_REMINDER: 1,
    EscalationTier.FORMAL_NOTICE: 8,
    EscalationTier.MANAGEMENT_ESCALATION: 31,
    EscalationTier.FINAL_DEMAND: 61,
    EscalationTier.LEGAL_COLLECTION: 91,
}


class ReceivableInvoice(Base):
    """A B2B receivable invoice tracked for overdue detection and escalation.

    Each invoice represents money owed to the merchant by a business customer.
    The chaser service monitors these invoices and automatically:
    - Detects when they become overdue
    - Progresses escalation tiers based on age
    - Sends emails at each tier with appropriate tone
    - Stops escalating once payment is received or the invoice is written off
    """

    __tablename__ = "receivable_invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Customer / debtor info (snapshot at creation)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(255))
    customer_email: Mapped[str] = mapped_column(String(255))
    customer_company: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Invoice details
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[int] = mapped_column(Integer)  # total in paise
    amount_paid: Mapped[int] = mapped_column(Integer, default=0)  # received in paise
    currency: Mapped[str] = mapped_column(String(10), default="INR")

    # Dates
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Escalation state
    status: Mapped[str] = mapped_column(
        String(50), default=ReceivableStatus.PENDING.value, index=True
    )
    escalation_tier: Mapped[str] = mapped_column(
        String(50), default=EscalationTier.NONE.value, index=True
    )
    last_escalation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_escalation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    escalation_count: Mapped[int] = mapped_column(Integer, default=0)
    max_escalations: Mapped[int] = mapped_column(Integer, default=10)

    # Metadata
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    customer = relationship("Customer", back_populates="receivable_invoices")
    escalation_events = relationship(
        "ReceivableEscalationEvent",
        back_populates="receivable_invoice",
        order_by="ReceivableEscalationEvent.created_at",
    )

    @property
    def remaining_amount(self) -> int:
        """Amount still outstanding (paise)."""
        return max(0, self.amount - self.amount_paid)

    @property
    def is_fully_paid(self) -> bool:
        return self.amount_paid >= self.amount

    def overdue_days(self, now: datetime | None = None) -> int:
        """Number of days past the due date (0 if not overdue)."""
        from datetime import timezone as _tz

        if now is None:
            now = datetime.now(_tz.utc)
        if self.due_date.tzinfo is None:
            due = self.due_date.replace(tzinfo=_tz.utc)
        else:
            due = self.due_date
        delta = now - due
        return max(0, delta.days)

    def compute_escalation_tier(self) -> EscalationTier:
        """Determine the appropriate escalation tier based on overdue days."""
        days = self.overdue_days()
        if days <= 0:
            return EscalationTier.NONE
        if days < 8:
            return EscalationTier.FRIENDLY_REMINDER
        if days < 31:
            return EscalationTier.FORMAL_NOTICE
        if days < 61:
            return EscalationTier.MANAGEMENT_ESCALATION
        if days < 91:
            return EscalationTier.FINAL_DEMAND
        return EscalationTier.LEGAL_COLLECTION


class ReceivableEscalationEvent(Base):
    """Audit trail for escalation actions taken on a receivable invoice.

    Every email sent, tier change, payment received, or manual action
    is recorded here for the compliance audit trail.
    """

    __tablename__ = "receivable_escalation_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    receivable_invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receivable_invoices.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    # e.g. "escalation_tier_changed", "email_sent", "payment_received",
    # "manual_action", "dispute_opened", "written_off"
    old_tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    new_tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    receivable_invoice = relationship(
        "ReceivableInvoice", back_populates="escalation_events"
    )
