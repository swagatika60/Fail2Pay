"""Recovery settings service: defaults, hard caps and safe persistence.

These settings only control operational knobs. Safety protections (hard-stop
rules, opt-out, minimum reminder spacing) are enforced elsewhere and can never
be disabled here — the service clamps every value back into the safe range
even if a caller bypasses HTTP validation.
"""

from sqlalchemy.orm import Session

from app.models import RecoverySetting
from app.schemas.settings import (
    MAX_INSTALLMENTS_CAP,
    MAX_RECOVERY_ATTEMPTS_CAP,
    RECOVERY_WINDOW_DAYS_CAP,
    REMINDER_SEQUENCE_MAX_LEN,
    DEFAULT_REMINDER_SEQUENCE,
)

DEFAULT_MERCHANT_ID = "default"

DEFAULT_SETTINGS = {
    "max_recovery_attempts": 5,
    "recovery_window_days": 14,
    "whatsapp_enabled": True,
    "email_enabled": True,
    "default_reminder_sequence": list(DEFAULT_REMINDER_SEQUENCE),
    "payment_plan_enabled": True,
    "max_installments": 4,
    "promise_to_pay_enabled": True,
}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _safe_sequence(seq: list[int]) -> list[int]:
    """Clamp out-of-range values and never allow a non-increasing sequence."""
    cleaned: list[int] = []
    for slot in seq:
        slot = _clamp(max(1, int(slot)), 1, RECOVERY_WINDOW_DAYS_CAP * 24)
        if not cleaned or slot > cleaned[-1]:
            cleaned.append(slot)
    return cleaned[:REMINDER_SEQUENCE_MAX_LEN] or list(DEFAULT_REMINDER_SEQUENCE)


def get_or_create(db: Session, merchant_id: str = DEFAULT_MERCHANT_ID) -> RecoverySetting:
    """Return the merchant's settings row, creating a default one if missing."""
    row = (
        db.query(RecoverySetting)
        .filter(RecoverySetting.merchant_id == merchant_id)
        .first()
    )
    if row is None:
        row = RecoverySetting(merchant_id=merchant_id, **DEFAULT_SETTINGS)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def to_response(row: RecoverySetting) -> dict:
    """Build the API response dict from a settings row (safety toggles fixed on)."""
    sequence = row.default_reminder_sequence or list(DEFAULT_REMINDER_SEQUENCE)
    return {
        "merchant_id": row.merchant_id,
        "max_recovery_attempts": row.max_recovery_attempts,
        "recovery_window_days": row.recovery_window_days,
        "whatsapp_enabled": row.whatsapp_enabled,
        "email_enabled": row.email_enabled,
        "default_reminder_sequence": sequence,
        "payment_plan_enabled": row.payment_plan_enabled,
        "max_installments": row.max_installments,
        "promise_to_pay_enabled": row.promise_to_pay_enabled,
        # Safety protections are enforced by hard_stop.py / validation and are
        # unconditionally enabled — never controlled by these settings.
        "hard_stop_enabled": True,
        "opt_out_enforced": True,
        "min_reminder_gap_hours": 2,
        "updated_at": row.updated_at,
    }


def save_settings(db: Session, payload: dict, merchant_id: str = DEFAULT_MERCHANT_ID) -> RecoverySetting:
    """Validate + safety-clamp and persist a settings update.

    ``payload`` is expected to come from a validated ``RecoverySettingsUpdate``;
    clamping here is a last-resort backstop so the DB can never hold values
    outside the safe range.
    """
    row = get_or_create(db, merchant_id)

    row.max_recovery_attempts = _clamp(
        int(payload["max_recovery_attempts"]), 1, MAX_RECOVERY_ATTEMPTS_CAP
    )
    row.recovery_window_days = _clamp(
        int(payload["recovery_window_days"]), 1, RECOVERY_WINDOW_DAYS_CAP
    )
    row.max_installments = _clamp(int(payload["max_installments"]), 2, MAX_INSTALLMENTS_CAP)

    whatsapp = bool(payload["whatsapp_enabled"])
    email = bool(payload["email_enabled"])
    # Safety: cannot disable every channel.
    if not whatsapp and not email:
        whatsapp = True
    row.whatsapp_enabled = whatsapp
    row.email_enabled = email

    row.default_reminder_sequence = _safe_sequence(payload["default_reminder_sequence"])
    row.payment_plan_enabled = bool(payload["payment_plan_enabled"])
    row.promise_to_pay_enabled = bool(payload["promise_to_pay_enabled"])

    db.commit()
    db.refresh(row)
    return row