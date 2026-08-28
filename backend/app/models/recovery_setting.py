import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Boolean, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RecoverySetting(Base):
    """Merchant-configurable recovery settings (single row per merchant).

    Stores operational knobs only. Fundamental safety protections are NOT
    stored here — hard-stop rules, customer opt-out and minimum reminder
    spacing are enforced by ``services/hard_stop.py`` and validation, and
    can never be disabled through these settings.
    """

    __tablename__ = "recovery_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, default="default")

    # Operational knobs
    max_recovery_attempts: Mapped[int] = mapped_column(Integer, default=5)
    recovery_window_days: Mapped[int] = mapped_column(Integer, default=14)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Default reminder/snooze cadence in hours, must be strictly increasing
    default_reminder_sequence: Mapped[list | None] = mapped_column(JSON, nullable=True)

    payment_plan_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_installments: Mapped[int] = mapped_column(Integer, default=4)
    promise_to_pay_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )