"""Tests for Subscription Failure Recovery Service."""

import pytest
from datetime import datetime, timedelta, timezone

from app.services.subscription_recovery import (
    classify_subscription_failure,
    calculate_next_retry,
    build_subscription_recovery_message,
    SUBSCRIPTION_FAILURE_CAUSES,
    RETRY_INTERVALS,
)


class TestSubscriptionFailureClassification:
    """Test subscription failure root cause detection."""

    def test_insufficient_funds_by_code(self):
        assert classify_subscription_failure(failure_code="insufficient_funds") == "insufficient_funds"

    def test_card_expired_by_code(self):
        assert classify_subscription_failure(failure_code="card_expired") == "card_expired"

    def test_mandate_issue_by_code(self):
        assert classify_subscription_failure(failure_code="mandate_declined") == "mandate_issue"

    def test_bank_declined_by_code(self):
        assert classify_subscription_failure(failure_code="declined") == "bank_declined"

    def test_gateway_timeout_by_code(self):
        assert classify_subscription_failure(failure_code="gateway_timeout") == "gateway_timeout"

    def test_insufficient_funds_by_reason(self):
        assert classify_subscription_failure(failure_reason="insufficient balance") == "insufficient_funds"

    def test_card_expired_by_reason(self):
        assert classify_subscription_failure(failure_reason="card has expired") == "card_expired"

    def test_unknown_fallback(self):
        assert classify_subscription_failure() == "unknown"

    def test_all_causes_have_retry_strategy(self):
        for cause_key, cause_info in SUBSCRIPTION_FAILURE_CAUSES.items():
            assert "retry_strategy" in cause_info
            assert "max_retries" in cause_info
            assert cause_info["retry_strategy"] in RETRY_INTERVALS or cause_info["max_retries"] == 0


class TestRetryCalculation:
    """Test retry scheduling logic."""

    def test_card_expired_no_retries(self):
        result = calculate_next_retry("card_expired", 0)
        assert result is None

    def test_immediate_retry_first_attempt(self):
        result = calculate_next_retry("gateway_timeout", 0)
        assert result is not None
        assert result > datetime.now(timezone.utc)

    def test_exponential_backoff_progression(self):
        r0 = calculate_next_retry("insufficient_funds", 0)
        r1 = calculate_next_retry("insufficient_funds", 1)
        r2 = calculate_next_retry("insufficient_funds", 2)
        r3 = calculate_next_retry("insufficient_funds", 3)

        assert r0 is not None
        assert r1 is not None
        assert r2 is not None
        assert r3 is None  # max_retries = 3

        # Each retry should be further out
        assert r1 > r0
        assert r2 > r1

    def test_max_retries_exhausted(self):
        for cause in SUBSCRIPTION_FAILURE_CAUSES:
            max_retries = SUBSCRIPTION_FAILURE_CAUSES[cause]["max_retries"]
            result = calculate_next_retry(cause, max_retries)
            assert result is None, f"{cause} should have no retry at max_retries"


class TestSubscriptionRecoveryMessages:
    """Test subscription recovery message generation."""

    def test_card_expired_english(self):
        msg = build_subscription_recovery_message(
            "Priya", 99900, "Premium Plan", "card_expired", 0, "en"
        )
        assert "Priya" in msg
        assert "₹999" in msg
        assert "expired" in msg.lower()

    def test_first_attempt_english(self):
        msg = build_subscription_recovery_message(
            "Priya", 99900, "Premium Plan", "insufficient_funds", 0, "en"
        )
        assert "Priya" in msg
        assert "₹999" in msg
        assert "Premium Plan" in msg

    def test_escalation_english(self):
        msg0 = build_subscription_recovery_message("Priya", 99900, "Plan", "insufficient_funds", 0, "en")
        msg1 = build_subscription_recovery_message("Priya", 99900, "Plan", "insufficient_funds", 1, "en")
        msg2 = build_subscription_recovery_message("Priya", 99900, "Plan", "insufficient_funds", 2, "en")
        assert "final" in msg2.lower()
        assert "risk" in msg1.lower() or "suspend" in msg1.lower()

    def test_hinglish_messages(self):
        msg = build_subscription_recovery_message(
            "Priya", 99900, "Premium Plan", "insufficient_funds", 0, "hi"
        )
        assert "Priya" in msg
        assert "₹999" in msg
        assert any(hi in msg for hi in ("Namaste", "hai", "karein", "ka"))

    def test_hinglish_card_expired(self):
        msg = build_subscription_recovery_message(
            "Priya", 99900, "Plan", "card_expired", 0, "hi-en"
        )
        assert "Priya" in msg
        assert "card" in msg.lower()

    def test_fallback_name(self):
        msg = build_subscription_recovery_message(None, 99900, "Plan", "unknown", 0, "en")
        assert "there" in msg
