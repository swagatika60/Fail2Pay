"""Tests for merchant recovery settings (persistence, validation, safety)."""

import pytest
from pydantic import ValidationError

from app.routes.settings import get_recovery_settings, update_recovery_settings
from app.schemas.settings import (
    MAX_INSTALLMENTS_CAP,
    MAX_RECOVERY_ATTEMPTS_CAP,
    RECOVERY_WINDOW_DAYS_CAP,
    RecoverySettingsResponse,
    RecoverySettingsUpdate,
)
from app.services import recovery_settings as settings_service


def test_defaults_returned_with_safety_on(db_session):
    """GET with no row returns defaults and hard-stop always enabled."""
    response = get_recovery_settings(db_session)

    assert response["max_recovery_attempts"] == 5
    assert response["recovery_window_days"] == 14
    assert response["default_reminder_sequence"] == [4, 8, 16, 32]
    assert response["max_installments"] == 4
    assert response["whatsapp_enabled"] is True
    assert response["email_enabled"] is True
    assert response["payment_plan_enabled"] is True
    assert response["promise_to_pay_enabled"] is True
    assert response["hard_stop_enabled"] is True
    assert response["opt_out_enforced"] is True


def test_update_persists_and_get_reflects(db_session):
    """PUT values persist and are returned by subsequent GET."""
    payload = RecoverySettingsUpdate(
        max_recovery_attempts=6,
        recovery_window_days=21,
        default_reminder_sequence=[2, 6, 18, 48],
        max_installments=6,
    )
    update_recovery_settings(payload, db_session)

    response = get_recovery_settings(db_session)
    assert response["max_recovery_attempts"] == 6
    assert response["recovery_window_days"] == 21
    assert response["default_reminder_sequence"] == [2, 6, 18, 48]
    assert response["max_installments"] == 6


def _valid_payload(**overrides) -> dict:
    base = {
        "max_recovery_attempts": 5,
        "recovery_window_days": 14,
        "whatsapp_enabled": True,
        "email_enabled": True,
        "default_reminder_sequence": [4, 8, 16, 32],
        "payment_plan_enabled": True,
        "max_installments": 4,
        "promise_to_pay_enabled": True,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "bad",
    [
        _valid_payload(max_recovery_attempts=MAX_RECOVERY_ATTEMPTS_CAP + 1),
        _valid_payload(recovery_window_days=RECOVERY_WINDOW_DAYS_CAP + 1),
        _valid_payload(max_recovery_attempts=0),
        _valid_payload(recovery_window_days=0),
        _valid_payload(max_installments=1),
        _valid_payload(max_installments=MAX_INSTALLMENTS_CAP + 1),
    ],
)
def test_out_of_range_values_rejected(bad):
    with pytest.raises(ValidationError):
        RecoverySettingsUpdate(**bad)


@pytest.mark.parametrize(
    "bad_seq",
    [
        [4, 4],
        [8, 4],
        [4, 5],
        [4, 8, 16, 0],
        [4, 8, 16, 32, 64, 128, 256, 512, 1024],
    ],
)
def test_bad_reminder_sequences_rejected(bad_seq):
    with pytest.raises(ValidationError):
        RecoverySettingsUpdate(**_valid_payload(default_reminder_sequence=bad_seq))


def test_both_channels_disabled_rejected():
    with pytest.raises(ValidationError):
        RecoverySettingsUpdate(
            **_valid_payload(whatsapp_enabled=False, email_enabled=False)
        )


def test_sequence_exceeding_window_rejected():
    """Reminder totals must fit inside the recovery window."""
    with pytest.raises(ValidationError):
        RecoverySettingsUpdate(
            **{
                **_valid_payload(),
                "recovery_window_days": 1,
                "default_reminder_sequence": [4, 8, 16, 32],  # 60h > 24h
            }
        )


def test_service_clamps_runaway_values(db_session):
    """Service-layer backstop never stores out-of-range values, even if a
    caller bypasses HTTP/pydantic validation."""
    settings_service.save_settings(
        db_session,
        {
            **_valid_payload(),
            "max_recovery_attempts": 999,
            "recovery_window_days": 500,
            "max_installments": 99,
            "whatsapp_enabled": False,
            "email_enabled": False,
            "default_reminder_sequence": [10, 9, 2000],
        },
    )

    response = get_recovery_settings(db_session)
    assert response["max_recovery_attempts"] <= MAX_RECOVERY_ATTEMPTS_CAP
    assert response["recovery_window_days"] <= RECOVERY_WINDOW_DAYS_CAP
    assert response["max_installments"] <= MAX_INSTALLMENTS_CAP
    assert response["whatsapp_enabled"] is True or response["email_enabled"] is True
    # Non-increasing entries are dropped, values clamped to window ceiling.
    assert response["default_reminder_sequence"] == [10, 1440]


def test_response_schema_roundtrip(db_session):
    update_recovery_settings(
        RecoverySettingsUpdate(**_valid_payload(max_recovery_attempts=7)), db_session
    )
    response = get_recovery_settings(db_session)
    parsed = RecoverySettingsResponse(**response)
    assert parsed.hard_stop_enabled is True
    assert parsed.max_recovery_attempts == 7