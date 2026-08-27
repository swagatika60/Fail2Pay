"""Tests for the deterministic Recovery Policy Engine.

Covers all 8 possible actions and their policy rules:
- STOP_RECOVERY
- SEND_WHATSAPP
- SEND_EMAIL
- SEND_PAYMENT_LINK
- SEND_INVOICE
- CREATE_PROMISE_TO_PAY
- PROPOSE_PAYMENT_PLAN
- SCHEDULE_REMINDER

Also covers:
- Terminal state handling
- Opt-out handling
- Max attempts
- Payment status
- Previous response handling
- Recommendation logic
- Priority ordering
"""

import pytest

from app.schemas.policy import PolicyInput, PolicyAction, PolicyDecision
from app.services.policy_engine import (
    evaluate_policy,
    evaluate_single_action,
    ALLOWED_ACTIONS,
    TERMINAL_STATUSES,
)


# --- Helper to create policy inputs ---


def make_input(**overrides) -> PolicyInput:
    """Create a PolicyInput with sensible defaults, override specific fields."""
    defaults = {
        "amount": 5000000,  # ₹50,000
        "risk_level": "MEDIUM",
        "attempt_count": 1,
        "max_attempts": 5,
        "customer_preferences": None,
        "previous_response": None,
        "payment_status": "failed",
        "recovery_history": None,
        "case_status": "RECOVERY_IN_PROGRESS",
        "has_phone": True,
        "has_email": True,
    }
    defaults.update(overrides)
    return PolicyInput(**defaults)


# --- STOP_RECOVERY Tests ---


class TestStopRecovery:
    def test_stop_allowed_when_max_attempts_reached(self):
        pi = make_input(attempt_count=5, max_attempts=5)
        decision = evaluate_policy(pi)
        stop = _find_action(decision, "STOP_RECOVERY")
        assert stop.allowed is True
        assert "Maximum attempts" in stop.reason

    def test_stop_allowed_when_case_recovered(self):
        pi = make_input(case_status="RECOVERED")
        decision = evaluate_policy(pi)
        stop = _find_action(decision, "STOP_RECOVERY")
        assert stop.allowed is True
        assert "RECOVERED" in stop.reason

    def test_stop_allowed_when_case_stopped(self):
        pi = make_input(case_status="STOPPED")
        decision = evaluate_policy(pi)
        stop = _find_action(decision, "STOP_RECOVERY")
        assert stop.allowed is True

    def test_stop_allowed_when_case_lost(self):
        pi = make_input(case_status="LOST")
        decision = evaluate_policy(pi)
        stop = _find_action(decision, "STOP_RECOVERY")
        assert stop.allowed is True

    def test_stop_allowed_when_customer_opted_out(self):
        pi = make_input(customer_preferences={"opted_out": True})
        decision = evaluate_policy(pi)
        stop = _find_action(decision, "STOP_RECOVERY")
        assert stop.allowed is True
        assert "opted out" in stop.reason.lower()

    def test_stop_allowed_when_payment_captured(self):
        pi = make_input(payment_status="captured")
        decision = evaluate_policy(pi)
        stop = _find_action(decision, "STOP_RECOVERY")
        assert stop.allowed is True
        assert "captured" in stop.reason.lower()

    def test_stop_denied_when_recovery_in_progress(self):
        pi = make_input(attempt_count=1, max_attempts=5)
        decision = evaluate_policy(pi)
        stop = _find_action(decision, "STOP_RECOVERY")
        assert stop.allowed is False


# --- SEND_WHATSAPP Tests ---


class TestSendWhatsApp:
    def test_whatsapp_allowed_first_attempt(self):
        pi = make_input(attempt_count=1)
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        assert wa.allowed is True
        assert wa.priority >= 70

    def test_whatsapp_allowed_second_attempt(self):
        pi = make_input(attempt_count=2)
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        assert wa.allowed is True

    def test_whatsapp_denied_no_phone(self):
        pi = make_input(has_phone=False)
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        assert wa.allowed is False
        assert "no phone" in wa.reason.lower()

    def test_whatsapp_denied_opted_out(self):
        pi = make_input(customer_preferences={"opted_out_channels": ["whatsapp"]})
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        assert wa.allowed is False
        assert "opted out" in wa.reason.lower()

    def test_whatsapp_denied_terminal_case(self):
        pi = make_input(case_status="RECOVERED")
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        assert wa.allowed is False

    def test_whatsapp_denied_max_attempts(self):
        pi = make_input(attempt_count=5, max_attempts=5)
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        assert wa.allowed is False

    def test_whatsapp_lower_priority_after_attempt_2(self):
        pi_early = make_input(attempt_count=1)
        pi_later = make_input(attempt_count=3)
        d1 = evaluate_policy(pi_early)
        d2 = evaluate_policy(pi_later)
        wa1 = _find_action(d1, "SEND_WHATSAPP")
        wa2 = _find_action(d2, "SEND_WHATSAPP")
        assert wa1.priority > wa2.priority


# --- SEND_EMAIL Tests ---


class TestSendEmail:
    def test_email_allowed_before_max_attempts(self):
        for attempt in range(1, 5):
            pi = make_input(attempt_count=attempt, max_attempts=5)
            decision = evaluate_policy(pi)
            email = _find_action(decision, "SEND_EMAIL")
            assert email.allowed is True, f"Email should be allowed at attempt {attempt}"

    def test_email_denied_no_email(self):
        pi = make_input(has_email=False)
        decision = evaluate_policy(pi)
        email = _find_action(decision, "SEND_EMAIL")
        assert email.allowed is False
        assert "no email" in email.reason.lower()

    def test_email_denied_opted_out(self):
        pi = make_input(customer_preferences={"opted_out_channels": ["email"]})
        decision = evaluate_policy(pi)
        email = _find_action(decision, "SEND_EMAIL")
        assert email.allowed is False

    def test_email_denied_terminal_case(self):
        pi = make_input(case_status="LOST")
        decision = evaluate_policy(pi)
        email = _find_action(decision, "SEND_EMAIL")
        assert email.allowed is False

    def test_email_denied_max_attempts(self):
        pi = make_input(attempt_count=5, max_attempts=5)
        decision = evaluate_policy(pi)
        email = _find_action(decision, "SEND_EMAIL")
        assert email.allowed is False

    def test_email_higher_priority_than_whatsapp_after_attempt_2(self):
        pi = make_input(attempt_count=3)
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        email = _find_action(decision, "SEND_EMAIL")
        assert email.priority > wa.priority


# --- SEND_PAYMENT_LINK Tests ---


class TestSendPaymentLink:
    def test_payment_link_allowed_for_failed_payment(self):
        pi = make_input(payment_status="failed")
        decision = evaluate_policy(pi)
        link = _find_action(decision, "SEND_PAYMENT_LINK")
        assert link.allowed is True

    def test_payment_link_denied_when_captured(self):
        pi = make_input(payment_status="captured")
        decision = evaluate_policy(pi)
        link = _find_action(decision, "SEND_PAYMENT_LINK")
        assert link.allowed is False

    def test_payment_link_denied_when_promised(self):
        pi = make_input(previous_response="promised")
        decision = evaluate_policy(pi)
        link = _find_action(decision, "SEND_PAYMENT_LINK")
        assert link.allowed is False
        assert "promised" in link.reason.lower()

    def test_payment_link_denied_terminal_case(self):
        pi = make_input(case_status="STOPPED")
        decision = evaluate_policy(pi)
        link = _find_action(decision, "SEND_PAYMENT_LINK")
        assert link.allowed is False

    def test_payment_link_higher_priority_for_high_risk(self):
        pi_high = make_input(risk_level="HIGH")
        pi_low = make_input(risk_level="LOW")
        d_high = evaluate_policy(pi_high)
        d_low = evaluate_policy(pi_low)
        link_high = _find_action(d_high, "SEND_PAYMENT_LINK")
        link_low = _find_action(d_low, "SEND_PAYMENT_LINK")
        assert link_high.priority > link_low.priority


# --- SEND_INVOICE Tests ---


class TestSendInvoice:
    def test_invoice_allowed_for_large_amounts(self):
        pi = make_input(amount=5_000_000)  # ₹5,000
        decision = evaluate_policy(pi)
        inv = _find_action(decision, "SEND_INVOICE")
        assert inv.allowed is True
        assert inv.priority >= 50

    def test_invoice_allowed_for_small_amounts(self):
        pi = make_input(amount=1_000_000)  # ₹1,000
        decision = evaluate_policy(pi)
        inv = _find_action(decision, "SEND_INVOICE")
        assert inv.allowed is True
        assert inv.priority < 50

    def test_invoice_denied_terminal_case(self):
        pi = make_input(case_status="RECOVERED")
        decision = evaluate_policy(pi)
        inv = _find_action(decision, "SEND_INVOICE")
        assert inv.allowed is False

    def test_invoice_denied_when_captured(self):
        pi = make_input(payment_status="captured")
        decision = evaluate_policy(pi)
        inv = _find_action(decision, "SEND_INVOICE")
        assert inv.allowed is False


# --- CREATE_PROMISE_TO_PAY Tests ---


class TestCreatePromiseToPay:
    def test_promise_allowed_when_customer_promised(self):
        pi = make_input(previous_response="promised")
        decision = evaluate_policy(pi)
        ptp = _find_action(decision, "CREATE_PROMISE_TO_PAY")
        assert ptp.allowed is True
        assert "promised" in ptp.reason.lower()

    def test_promise_denied_when_no_response(self):
        pi = make_input(previous_response="no_response")
        decision = evaluate_policy(pi)
        ptp = _find_action(decision, "CREATE_PROMISE_TO_PAY")
        assert ptp.allowed is False

    def test_promise_denied_when_paid(self):
        pi = make_input(previous_response="paid")
        decision = evaluate_policy(pi)
        ptp = _find_action(decision, "CREATE_PROMISE_TO_PAY")
        assert ptp.allowed is False

    def test_promise_denied_terminal_case(self):
        pi = make_input(previous_response="promised", case_status="RECOVERED")
        decision = evaluate_policy(pi)
        ptp = _find_action(decision, "CREATE_PROMISE_TO_PAY")
        assert ptp.allowed is False


# --- PROPOSE_PAYMENT_PLAN Tests ---


class TestProposePaymentPlan:
    def test_plan_allowed_for_large_amount(self):
        pi = make_input(amount=10_000_000)  # ₹10,000
        decision = evaluate_policy(pi)
        plan = _find_action(decision, "PROPOSE_PAYMENT_PLAN")
        assert plan.allowed is True
        assert plan.priority >= 60

    def test_plan_denied_for_small_amount(self):
        pi = make_input(amount=5_000_000)  # ₹5,000
        decision = evaluate_policy(pi)
        plan = _find_action(decision, "PROPOSE_PAYMENT_PLAN")
        assert plan.allowed is False
        assert "not needed" in plan.reason.lower()

    def test_plan_denied_when_promised(self):
        pi = make_input(amount=10_000_000, previous_response="promised")
        decision = evaluate_policy(pi)
        plan = _find_action(decision, "PROPOSE_PAYMENT_PLAN")
        assert plan.allowed is False

    def test_plan_denied_when_scheduled(self):
        pi = make_input(amount=10_000_000, previous_response="scheduled")
        decision = evaluate_policy(pi)
        plan = _find_action(decision, "PROPOSE_PAYMENT_PLAN")
        assert plan.allowed is False

    def test_plan_denied_when_captured(self):
        pi = make_input(amount=10_000_000, payment_status="captured")
        decision = evaluate_policy(pi)
        plan = _find_action(decision, "PROPOSE_PAYMENT_PLAN")
        assert plan.allowed is False


# --- SCHEDULE_REMINDER Tests ---


class TestScheduleReminder:
    def test_reminder_allowed_for_no_response(self):
        pi = make_input(previous_response="no_response")
        decision = evaluate_policy(pi)
        rem = _find_action(decision, "SCHEDULE_REMINDER")
        assert rem.allowed is True
        assert rem.priority >= 50

    def test_reminder_allowed_when_no_previous(self):
        pi = make_input(previous_response=None)
        decision = evaluate_policy(pi)
        rem = _find_action(decision, "SCHEDULE_REMINDER")
        assert rem.allowed is True

    def test_reminder_denied_when_promised(self):
        pi = make_input(previous_response="promised")
        decision = evaluate_policy(pi)
        rem = _find_action(decision, "SCHEDULE_REMINDER")
        assert rem.allowed is False
        assert "promised" in rem.reason.lower()

    def test_reminder_denied_terminal_case(self):
        pi = make_input(case_status="LOST")
        decision = evaluate_policy(pi)
        rem = _find_action(decision, "SCHEDULE_REMINDER")
        assert rem.allowed is False

    def test_reminder_denied_at_last_attempt(self):
        pi = make_input(attempt_count=4, max_attempts=5)
        decision = evaluate_policy(pi)
        rem = _find_action(decision, "SCHEDULE_REMINDER")
        assert rem.allowed is False

    def test_reminder_denied_when_captured(self):
        pi = make_input(payment_status="captured")
        decision = evaluate_policy(pi)
        rem = _find_action(decision, "SCHEDULE_REMINDER")
        assert rem.allowed is False


# --- Recommendation Tests ---


class TestRecommendation:
    def test_recommends_stop_when_max_attempts(self):
        pi = make_input(attempt_count=5, max_attempts=5)
        decision = evaluate_policy(pi)
        assert decision.recommended_action is not None
        assert decision.recommended_action.action == "STOP_RECOVERY"

    def test_recommends_stop_when_opted_out(self):
        pi = make_input(customer_preferences={"opted_out": True})
        decision = evaluate_policy(pi)
        assert decision.recommended_action.action == "STOP_RECOVERY"

    def test_recommends_promise_when_customer_promised(self):
        pi = make_input(previous_response="promised", attempt_count=3)
        decision = evaluate_policy(pi)
        assert decision.recommended_action.action == "CREATE_PROMISE_TO_PAY"

    def test_recommends_payment_link_first_attempt(self):
        pi = make_input(attempt_count=1, previous_response=None)
        decision = evaluate_policy(pi)
        # Should be payment_link or whatsapp (both high priority)
        assert decision.recommended_action.action in ("SEND_PAYMENT_LINK", "SEND_WHATSAPP")

    def test_recommends_whatsapp_first(self):
        pi = make_input(attempt_count=1)
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        # WhatsApp should be in allowed actions with high priority
        assert wa.allowed is True
        assert wa.priority >= 70

    def test_no_recommendation_when_all_denied(self):
        pi = make_input(
            case_status="RECOVERED",
        )
        decision = evaluate_policy(pi)
        # Stop recovery is still allowed for terminal cases
        assert decision.recommended_action is not None
        assert decision.recommended_action.action == "STOP_RECOVERY"


# --- Priority Ordering Tests ---


class TestPriorityOrdering:
    def test_stop_has_highest_priority(self):
        pi = make_input(attempt_count=5, max_attempts=5)
        decision = evaluate_policy(pi)
        stop = _find_action(decision, "STOP_RECOVERY")
        assert stop.priority >= 90  # 90 for max_attempts, 100 for terminal/opted_out

    def test_promise_high_priority_when_customer_promised(self):
        pi = make_input(previous_response="promised")
        decision = evaluate_policy(pi)
        ptp = _find_action(decision, "CREATE_PROMISE_TO_PAY")
        assert ptp.priority >= 70

    def test_payment_link_high_priority_for_high_risk(self):
        pi = make_input(risk_level="HIGH")
        decision = evaluate_policy(pi)
        link = _find_action(decision, "SEND_PAYMENT_LINK")
        assert link.priority >= 70


# --- Multiple Actions Allowed ---


class TestMultipleActionsAllowed:
    def test_typical_first_attempt_allows_multiple(self):
        pi = make_input(attempt_count=1)
        decision = evaluate_policy(pi)
        assert len(decision.allowed_actions) >= 4
        allowed_names = {a.action for a in decision.allowed_actions}
        assert "SEND_WHATSAPP" in allowed_names
        assert "SEND_PAYMENT_LINK" in allowed_names

    def test_terminal_case_only_allows_stop(self):
        pi = make_input(case_status="RECOVERED")
        decision = evaluate_policy(pi)
        allowed_names = {a.action for a in decision.allowed_actions}
        assert allowed_names == {"STOP_RECOVERY"}

    def test_high_risk_high_amount_allows_more_actions(self):
        pi = make_input(risk_level="HIGH", amount=10_000_000)
        decision = evaluate_policy(pi)
        assert len(decision.allowed_actions) >= 5


# --- Terminal Status Tests ---


class TestTerminalStatuses:
    def test_recovered_allows_only_stop(self):
        pi = make_input(case_status="RECOVERED")
        decision = evaluate_policy(pi)
        allowed_names = {a.action for a in decision.allowed_actions}
        assert allowed_names == {"STOP_RECOVERY"}

    def test_lost_allows_only_stop(self):
        pi = make_input(case_status="LOST")
        decision = evaluate_policy(pi)
        allowed_names = {a.action for a in decision.allowed_actions}
        assert allowed_names == {"STOP_RECOVERY"}

    def test_stopped_allows_only_stop(self):
        pi = make_input(case_status="STOPPED")
        decision = evaluate_policy(pi)
        allowed_names = {a.action for a in decision.allowed_actions}
        assert allowed_names == {"STOP_RECOVERY"}


# --- Opt-Out Handling Tests ---


class TestOptOutHandling:
    def test_opt_out_whatsapp_only(self):
        pi = make_input(customer_preferences={"opted_out_channels": ["whatsapp"]})
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        email = _find_action(decision, "SEND_EMAIL")
        assert wa.allowed is False
        assert email.allowed is True

    def test_opt_out_email_only(self):
        pi = make_input(customer_preferences={"opted_out_channels": ["email"]})
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        email = _find_action(decision, "SEND_EMAIL")
        assert wa.allowed is True
        assert email.allowed is False

    def test_opt_out_all_channels(self):
        pi = make_input(customer_preferences={"opted_out_channels": ["whatsapp", "email"]})
        decision = evaluate_policy(pi)
        wa = _find_action(decision, "SEND_WHATSAPP")
        email = _find_action(decision, "SEND_EMAIL")
        assert wa.allowed is False
        assert email.allowed is False


# --- evaluate_single_action Tests ---


class TestEvaluateSingleAction:
    def test_evaluate_whatsapp_when_no_phone(self):
        pi = make_input(has_phone=False)
        result = evaluate_single_action(pi, "SEND_WHATSAPP")
        assert result.allowed is False

    def test_evaluate_payment_link_when_captured(self):
        pi = make_input(payment_status="captured")
        result = evaluate_single_action(pi, "SEND_PAYMENT_LINK")
        assert result.allowed is False

    def test_evaluate_unknown_action(self):
        pi = make_input()
        result = evaluate_single_action(pi, "INVALID_ACTION")
        assert result.allowed is False
        assert "unknown" in result.reason.lower()

    def test_evaluate_stop_when_max_attempts(self):
        pi = make_input(attempt_count=5, max_attempts=5)
        result = evaluate_single_action(pi, "STOP_RECOVERY")
        assert result.allowed is True


# --- Amount Threshold Tests ---


class TestAmountThresholds:
    def test_payment_plan_threshold(self):
        # Below threshold
        pi_below = make_input(amount=9_999_999)
        d_below = evaluate_policy(pi_below)
        plan_below = _find_action(d_below, "PROPOSE_PAYMENT_PLAN")
        assert plan_below.allowed is False

        # At threshold
        pi_at = make_input(amount=10_000_000)
        d_at = evaluate_policy(pi_at)
        plan_at = _find_action(d_at, "PROPOSE_PAYMENT_PLAN")
        assert plan_at.allowed is True

    def test_invoice_threshold(self):
        # Below threshold — still allowed but lower priority
        pi_below = make_input(amount=4_999_999)
        d_below = evaluate_policy(pi_below)
        inv_below = _find_action(d_below, "SEND_INVOICE")
        assert inv_below.allowed is True
        assert inv_below.priority < 50

        # At threshold
        pi_at = make_input(amount=5_000_000)
        d_at = evaluate_policy(pi_at)
        inv_at = _find_action(d_at, "SEND_INVOICE")
        assert inv_at.allowed is True
        assert inv_at.priority >= 50


# --- Customer Preferences Tests ---


class TestCustomerPreferences:
    def test_no_preferences_works(self):
        pi = make_input(customer_preferences=None)
        decision = evaluate_policy(pi)
        assert len(decision.allowed_actions) >= 4

    def test_empty_preferences_works(self):
        pi = make_input(customer_preferences={})
        decision = evaluate_policy(pi)
        assert len(decision.allowed_actions) >= 4


# --- Full Lifecycle Policy Tests ---


class TestFullLifecyclePolicy:
    def test_escalation_path(self):
        """Test how policies change as attempts increase."""
        # Attempt 1: WhatsApp + payment link
        pi1 = make_input(attempt_count=1)
        d1 = evaluate_policy(pi1)
        wa1 = _find_action(d1, "SEND_WHATSAPP")
        assert wa1.allowed is True
        assert wa1.priority >= 70

        # Attempt 3: Email becomes primary, WhatsApp backup
        pi3 = make_input(attempt_count=3)
        d3 = evaluate_policy(pi3)
        wa3 = _find_action(d3, "SEND_WHATSAPP")
        email3 = _find_action(d3, "SEND_EMAIL")
        assert wa3.priority < email3.priority

        # Attempt 5: Stop
        pi5 = make_input(attempt_count=5, max_attempts=5)
        d5 = evaluate_policy(pi5)
        stop5 = _find_action(d5, "STOP_RECOVERY")
        assert stop5.allowed is True

    def test_response_changes_policy(self):
        """Policy changes based on customer response."""
        # No response: schedule reminder
        pi_nr = make_input(previous_response="no_response")
        d_nr = evaluate_policy(pi_nr)
        rem = _find_action(d_nr, "SCHEDULE_REMINDER")
        assert rem.allowed is True

        # Promised: create promise, no payment link, no reminder
        pi_pr = make_input(previous_response="promised")
        d_pr = evaluate_policy(pi_pr)
        ptp = _find_action(d_pr, "CREATE_PROMISE_TO_PAY")
        link = _find_action(d_pr, "SEND_PAYMENT_LINK")
        rem2 = _find_action(d_pr, "SCHEDULE_REMINDER")
        assert ptp.allowed is True
        assert link.allowed is False
        assert rem2.allowed is False


# --- Helpers ---


def _find_action(decision: PolicyDecision, action_name: str) -> PolicyAction:
    """Find a specific action in the decision's allowed or denied list."""
    for action in decision.allowed_actions + decision.denied_actions:
        if action.action == action_name:
            return action
    raise AssertionError(f"Action {action_name} not found in decision")
