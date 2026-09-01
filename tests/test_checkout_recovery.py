"""Tests for Checkout Abandonment Recovery Service."""

import pytest
from app.services.checkout_recovery import (
    classify_abandonment_cause,
    get_reengagement_window,
    should_reengage,
    build_checkout_recovery_message,
    ABANDONMENT_CAUSES,
    MAXREENGAGEMENT_ATTEMPTS,
)


class TestAbandonmentCauseClassification:
    """Test checkout abandonment root cause detection."""

    def test_payment_failure_detected(self):
        assert classify_abandonment_cause(1000, "payment failed") == "payment_failure"

    def test_price_hesitation_detected(self):
        assert classify_abandonment_cause(1000, "too expensive") == "price_hesitation"

    def test_distraction_detected(self):
        assert classify_abandonment_cause(1000, "session timeout") == "distraction"

    def test_cart_page_source(self):
        assert classify_abandonment_cause(1000, source="cart_page") == "comparison_shopping"

    def test_payment_page_source(self):
        assert classify_abandonment_cause(1000, source="payment_page") == "payment_failure"

    def test_unknown_fallback(self):
        assert classify_abandonment_cause(1000, "") == "unknown"

    def test_all_causes_have_required_fields(self):
        for cause_key, cause_info in ABANDONMENT_CAUSES.items():
            assert "label" in cause_info
            assert "intervention" in cause_info
            assert "description" in cause_info


class TestReengagementWindow:
    """Test re-engagement timing logic."""

    def test_first_attempt_is_immediate(self):
        assert get_reengagement_window(0) == "immediate"

    def test_second_attempt_is_same_day(self):
        assert get_reengagement_window(1) == "same_day"

    def test_third_attempt_is_next_day(self):
        assert get_reengagement_window(2) == "next_day"

    def test_fourth_attempt_is_final_nudge(self):
        assert get_reengagement_window(3) == "final_nudge"


class TestReengageDecision:
    """Test re-engagement eligibility logic."""

    def test_can_reengage_when_abandoned(self):
        assert should_reengage(0, "abandoned") is True

    def test_can_reengage_when_recovering(self):
        assert should_reengage(1, "recovering") is True

    def test_cannot_reengage_when_recovered(self):
        assert should_reengage(0, "recovered") is False

    def test_cannot_reengage_when_lost(self):
        assert should_reengage(0, "lost") is False

    def test_cannot_reengage_when_max_attempts(self):
        assert should_reengage(MAXREENGAGEMENT_ATTEMPTS, "abandoned") is False


class TestRecoveryMessages:
    """Test deterministic recovery message generation."""

    def test_english_payment_failure_message(self):
        msg = build_checkout_recovery_message("Rahul", 500000, "payment_failure", 0, "en")
        assert "Rahul" in msg
        assert "₹5,000" in msg
        assert "payment" in msg.lower()

    def test_english_distraction_message(self):
        msg = build_checkout_recovery_message("Rahul", 500000, "distraction", 0, "en")
        assert "Rahul" in msg
        assert "₹5,000" in msg

    def test_english_escalation_messages(self):
        msg0 = build_checkout_recovery_message("Rahul", 500000, "unknown", 0, "en")
        msg1 = build_checkout_recovery_message("Rahul", 500000, "unknown", 1, "en")
        msg2 = build_checkout_recovery_message("Rahul", 500000, "unknown", 2, "en")
        # Messages should escalate in urgency
        assert "last chance" in msg2.lower()
        assert "reminder" in msg1.lower()

    def test_hinglish_messages(self):
        msg = build_checkout_recovery_message("Rahul", 500000, "unknown", 0, "hi")
        assert "Rahul" in msg
        assert "₹5,000" in msg
        # Should contain Hindi words
        assert any(hi in msg for hi in ("Namaste", "hai", "karein", "ka"))

    def test_hinglish_payment_failure(self):
        msg = build_checkout_recovery_message("Rahul", 500000, "payment_failure", 0, "hi-en")
        assert "Rahul" in msg
        assert "payment" in msg.lower()

    def test_fallback_name_when_none(self):
        msg = build_checkout_recovery_message(None, 500000, "unknown", 0, "en")
        assert "there" in msg
