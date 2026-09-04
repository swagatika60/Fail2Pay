"""Recovery settings schemas for the merchant config page."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Hard safety caps (enforced at validation AND at the service layer so that
# merchant settings can never weaken recovery safety protections).
MAX_RECOVERY_ATTEMPTS_CAP = 8
RECOVERY_WINDOW_DAYS_CAP = 60
MAX_INSTALLMENTS_CAP = 12
REMINDER_SEQUENCE_MAX_LEN = 8
REMINDER_MIN_GAP_HOURS = 2
MIN_REMINDER_HOURS = 1

# Spec no-response cadence (hours after the initial message):
# T+2h → T+4h → T+8h → T+16h → T+24h → T+36h → T+48h → STOP
DEFAULT_REMINDER_SEQUENCE = [2, 4, 8, 16, 24, 36, 48]


class RecoverySettingsUpdate(BaseModel):
    """Body accepted by ``PUT /api/settings/recovery``."""

    max_recovery_attempts: int = Field(8, ge=1, le=MAX_RECOVERY_ATTEMPTS_CAP)
    recovery_window_days: int = Field(14, ge=1, le=RECOVERY_WINDOW_DAYS_CAP)
    whatsapp_enabled: bool = True
    email_enabled: bool = True
    default_reminder_sequence: list[int] = Field(default_factory=lambda: list(DEFAULT_REMINDER_SEQUENCE))
    payment_plan_enabled: bool = True
    max_installments: int = Field(4, ge=2, le=MAX_INSTALLMENTS_CAP)
    promise_to_pay_enabled: bool = True

    @field_validator("default_reminder_sequence")
    @classmethod
    def validate_reminder_sequence(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("reminder sequence must not be empty")
        if len(v) > REMINDER_SEQUENCE_MAX_LEN:
            raise ValueError(f"at most {REMINDER_SEQUENCE_MAX_LEN} reminders allowed")
        for slot in v:
            if slot < MIN_REMINDER_HOURS:
                raise ValueError(f"each reminder must be at least {MIN_REMINDER_HOURS}h after the previous")
        if any(v[i] >= v[i + 1] for i in range(len(v) - 1)):
            raise ValueError("reminder sequence must be strictly increasing")
        if any(v[i + 1] - v[i] < REMINDER_MIN_GAP_HOURS for i in range(len(v) - 1)):
            raise ValueError(f"reminders must be spaced at least {REMINDER_MIN_GAP_HOURS}h apart")
        return v

    @model_validator(mode="after")
    def check_recovery_rules(self) -> "RecoverySettingsUpdate":
        if not self.whatsapp_enabled and not self.email_enabled:
            raise ValueError("at least one recovery channel (WhatsApp or Email) must stay enabled")
        total_hours = sum(self.default_reminder_sequence)
        window_hours = self.recovery_window_days * 24
        if total_hours > window_hours:
            raise ValueError(
                f"reminder sequence totals {total_hours}h which exceeds the "
                f"recovery window of {window_hours}h ({self.recovery_window_days} days)"
            )
        return self


class RecoverySettingsResponse(BaseModel):
    """Returned by ``GET/PUT /api/settings/recovery``."""

    merchant_id: str
    max_recovery_attempts: int
    recovery_window_days: int
    whatsapp_enabled: bool
    email_enabled: bool
    default_reminder_sequence: list[int]
    payment_plan_enabled: bool
    max_installments: int
    promise_to_pay_enabled: bool
    # Safety protections — always on, never exposed as merchant toggles.
    hard_stop_enabled: Literal[True] = True
    opt_out_enforced: Literal[True] = True
    min_reminder_gap_hours: int = REMINDER_MIN_GAP_HOURS
    updated_at: datetime | None = None