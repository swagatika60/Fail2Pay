"""Deterministic Recovery Policy Engine.

Decides WHAT type of intervention is allowed based on structured inputs.
No AI or LLM is involved in any policy decision — pure rule-based logic.

AI may later help choose among bounded options, but it must never bypass
policy restrictions defined here.

Policy inputs:
- amount (paise)
- risk_level (HIGH/MEDIUM/LOW)
- attempt_count / max_attempts
- customer_preferences (opt-out channels)
- previous_response (paid/promised/no_response/failed)
- payment_status
- recovery_history (list of past actions)

Possible actions:
- SEND_WHATSAPP
- SEND_EMAIL
- SEND_PAYMENT_LINK
- SEND_INVOICE
- CREATE_PROMISE_TO_PAY
- PROPOSE_PAYMENT_PLAN
- SCHEDULE_REMINDER
- STOP_RECOVERY

Every policy decision is structured:
{
  "action": "SEND_WHATSAPP",
  "reason": "First recovery attempt",
  "allowed": true
}
"""

import logging

from app.schemas.policy import PolicyAction, PolicyDecision, PolicyInput

logger = logging.getLogger(__name__)


# --- Constants ---

ALLOWED_ACTIONS = [
    "SEND_WHATSAPP",
    "SEND_EMAIL",
    "SEND_PAYMENT_LINK",
    "SEND_INVOICE",
    "CREATE_PROMISE_TO_PAY",
    "PROPOSE_PAYMENT_PLAN",
    "SCHEDULE_REMINDER",
    "STOP_RECOVERY",
]

# Amount thresholds for escalation (in paise)
PAYMENT_PLAN_THRESHOLD = 10_000_000  # ₹10,000 — propose plan for large amounts
INVOICE_THRESHOLD = 5_000_000  # ₹5,000 — send invoice for larger amounts

# Terminal statuses where no recovery actions should be taken
TERMINAL_STATUSES = {"RECOVERED", "LOST", "STOPPED"}


def evaluate_policy(policy_input: PolicyInput) -> PolicyDecision:
    """Evaluate all possible actions against the policy rules.

    This is the main entry point. It checks every possible action and
    returns which are allowed, which are denied, and the recommended action.

    Args:
        policy_input: All inputs needed for policy evaluation

    Returns:
        PolicyDecision with allowed/denied actions and recommendation
    """
    allowed = []
    denied = []

    # Evaluate each possible action
    evaluators = [
        _eval_stop_recovery,
        _eval_send_whatsapp,
        _eval_send_email,
        _eval_send_payment_link,
        _eval_send_invoice,
        _eval_create_promise_to_pay,
        _eval_propose_payment_plan,
        _eval_schedule_reminder,
    ]

    for evaluator in evaluators:
        action = evaluator(policy_input)
        if action.allowed:
            allowed.append(action)
        else:
            denied.append(action)

    # Choose the recommended action from allowed ones
    recommended = _choose_recommended(allowed, policy_input)

    return PolicyDecision(
        allowed_actions=allowed,
        denied_actions=denied,
        recommended_action=recommended,
    )


# --- Individual action evaluators ---


def _eval_stop_recovery(pi: PolicyInput) -> PolicyAction:
    """STOP_RECOVERY — always allowed if case is terminal or stop conditions met."""
    # Terminal cases should always allow stop (cleanup)
    if pi.case_status in TERMINAL_STATUSES:
        return PolicyAction(
            action="STOP_RECOVERY",
            reason=f"Case is already {pi.case_status} — stop recovery",
            allowed=True,
            priority=100,
        )

    # Max attempts reached
    if pi.attempt_count >= pi.max_attempts:
        return PolicyAction(
            action="STOP_RECOVERY",
            reason=f"Maximum attempts reached ({pi.attempt_count}/{pi.max_attempts})",
            allowed=True,
            priority=90,
        )

    # Customer opted out (check customer_preferences)
    prefs = pi.customer_preferences or {}
    if prefs.get("opted_out", False):
        return PolicyAction(
            action="STOP_RECOVERY",
            reason="Customer has opted out of recovery",
            allowed=True,
            priority=100,
        )

    # Payment already succeeded
    if pi.payment_status == "captured":
        return PolicyAction(
            action="STOP_RECOVERY",
            reason="Payment has been captured — no recovery needed",
            allowed=True,
            priority=100,
        )

    return PolicyAction(
        action="STOP_RECOVERY",
        reason="Stop conditions not met — recovery should continue",
        allowed=False,
    )


def _eval_send_whatsapp(pi: PolicyInput) -> PolicyAction:
    """SEND_WHATSAPP — preferred channel for first attempts."""
    # Must have phone number
    if not pi.has_phone:
        return PolicyAction(
            action="SEND_WHATSAPP",
            reason="Customer has no phone number on file",
            allowed=False,
        )

    # Customer opted out of WhatsApp
    prefs = pi.customer_preferences or {}
    opted_out_channels = prefs.get("opted_out_channels", [])
    if "whatsapp" in opted_out_channels:
        return PolicyAction(
            action="SEND_WHATSAPP",
            reason="Customer opted out of WhatsApp messages",
            allowed=False,
        )

    # Case is terminal — no messages
    if pi.case_status in TERMINAL_STATUSES:
        return PolicyAction(
            action="SEND_WHATSAPP",
            reason=f"Case is {pi.case_status} — no further messages",
            allowed=False,
        )

    # Max attempts reached
    if pi.attempt_count >= pi.max_attempts:
        return PolicyAction(
            action="SEND_WHATSAPP",
            reason="Maximum attempts reached — no more messages",
            allowed=False,
        )

    # WhatsApp is preferred for first 2 attempts
    if pi.attempt_count <= 2:
        return PolicyAction(
            action="SEND_WHATSAPP",
            reason=f"Attempt {pi.attempt_count} — WhatsApp is preferred for early outreach",
            allowed=True,
            priority=80,
        )

    # After attempt 2, WhatsApp is still allowed but lower priority
    return PolicyAction(
        action="SEND_WHATSAPP",
        reason=f"Attempt {pi.attempt_count} — WhatsApp still available as backup",
        allowed=True,
        priority=40,
    )


def _eval_send_email(pi: PolicyInput) -> PolicyAction:
    """SEND_EMAIL — used as fallback or after WhatsApp attempts."""
    # Must have email
    if not pi.has_email:
        return PolicyAction(
            action="SEND_EMAIL",
            reason="Customer has no email on file",
            allowed=False,
        )

    # Customer opted out of email
    prefs = pi.customer_preferences or {}
    opted_out_channels = prefs.get("opted_out_channels", [])
    if "email" in opted_out_channels:
        return PolicyAction(
            action="SEND_EMAIL",
            reason="Customer opted out of email messages",
            allowed=False,
        )

    # Case is terminal
    if pi.case_status in TERMINAL_STATUSES:
        return PolicyAction(
            action="SEND_EMAIL",
            reason=f"Case is {pi.case_status} — no further messages",
            allowed=False,
        )

    # Max attempts reached
    if pi.attempt_count >= pi.max_attempts:
        return PolicyAction(
            action="SEND_EMAIL",
            reason="Maximum attempts reached — no more messages",
            allowed=False,
        )

    # Email is useful from attempt 2 onward (after WhatsApp)
    if pi.attempt_count < 2:
        return PolicyAction(
            action="SEND_EMAIL",
            reason="Attempt 1 — prefer WhatsApp first, email as backup",
            allowed=True,
            priority=30,
        )

    # From attempt 2+, email is a good channel
    return PolicyAction(
        action="SEND_EMAIL",
        reason=f"Attempt {pi.attempt_count} — email as follow-up channel",
        allowed=True,
        priority=60,
    )


def _eval_send_payment_link(pi: PolicyInput) -> PolicyAction:
    """SEND_PAYMENT_LINK — provide a direct payment link."""
    # Case is terminal
    if pi.case_status in TERMINAL_STATUSES:
        return PolicyAction(
            action="SEND_PAYMENT_LINK",
            reason=f"Case is {pi.case_status} — no payment actions",
            allowed=False,
        )

    # Max attempts reached
    if pi.attempt_count >= pi.max_attempts:
        return PolicyAction(
            action="SEND_PAYMENT_LINK",
            reason="Maximum attempts reached — no more actions",
            allowed=False,
        )

    # Payment already captured
    if pi.payment_status == "captured":
        return PolicyAction(
            action="SEND_PAYMENT_LINK",
            reason="Payment already captured — no link needed",
            allowed=False,
        )

    # Not useful if customer already promised to pay (wait for them)
    if pi.previous_response == "promised":
        return PolicyAction(
            action="SEND_PAYMENT_LINK",
            reason="Customer promised to pay — wait for payment",
            allowed=False,
        )

    # Always useful for failed payments — include payment link in messages
    priority = 70 if pi.risk_level == "HIGH" else 50
    return PolicyAction(
        action="SEND_PAYMENT_LINK",
        reason="Include payment link for easy recovery",
        allowed=True,
        priority=priority,
    )


def _eval_send_invoice(pi: PolicyInput) -> PolicyAction:
    """SEND_INVOICE — formal invoice for larger amounts or overdue."""
    # Case is terminal
    if pi.case_status in TERMINAL_STATUSES:
        return PolicyAction(
            action="SEND_INVOICE",
            reason=f"Case is {pi.case_status} — no invoice actions",
            allowed=False,
        )

    # Max attempts reached
    if pi.attempt_count >= pi.max_attempts:
        return PolicyAction(
            action="SEND_INVOICE",
            reason="Maximum attempts reached — no more actions",
            allowed=False,
        )

    # Payment already captured
    if pi.payment_status == "captured":
        return PolicyAction(
            action="SEND_INVOICE",
            reason="Payment already captured — no invoice needed",
            allowed=False,
        )

    # Invoice is more appropriate for larger amounts
    if pi.amount >= INVOICE_THRESHOLD:
        return PolicyAction(
            action="SEND_INVOICE",
            reason=f"Amount ₹{pi.amount // 100} >= ₹{INVOICE_THRESHOLD // 100} — formal invoice appropriate",
            allowed=True,
            priority=55,
        )

    # For smaller amounts, invoice is less useful but still allowed
    return PolicyAction(
        action="SEND_INVOICE",
        reason="Invoice available but less critical for small amounts",
        allowed=True,
        priority=20,
    )


def _eval_create_promise_to_pay(pi: PolicyInput) -> PolicyAction:
    """CREATE_PROMISE_TO_PAY — formalize customer's promise."""
    # Case is terminal
    if pi.case_status in TERMINAL_STATUSES:
        return PolicyAction(
            action="CREATE_PROMISE_TO_PAY",
            reason=f"Case is {pi.case_status} — no promise actions",
            allowed=False,
        )

    # Only meaningful if customer has actually promised
    if pi.previous_response == "promised":
        return PolicyAction(
            action="CREATE_PROMISE_TO_PAY",
            reason="Customer promised to pay — create formal promise record",
            allowed=True,
            priority=75,
        )

    # If customer hasn't promised, can't create a promise
    return PolicyAction(
        action="CREATE_PROMISE_TO_PAY",
        reason="Customer has not promised to pay — cannot create promise",
        allowed=False,
    )


def _eval_propose_payment_plan(pi: PolicyInput) -> PolicyAction:
    """PROPOSE_PAYMENT_PLAN — offer installment plan for large amounts."""
    # Case is terminal
    if pi.case_status in TERMINAL_STATUSES:
        return PolicyAction(
            action="PROPOSE_PAYMENT_PLAN",
            reason=f"Case is {pi.case_status} — no payment plan actions",
            allowed=False,
        )

    # Max attempts reached
    if pi.attempt_count >= pi.max_attempts:
        return PolicyAction(
            action="PROPOSE_PAYMENT_PLAN",
            reason="Maximum attempts reached — no more actions",
            allowed=False,
        )

    # Payment already captured
    if pi.payment_status == "captured":
        return PolicyAction(
            action="PROPOSE_PAYMENT_PLAN",
            reason="Payment already captured — no plan needed",
            allowed=False,
        )

    # Not useful if customer already has a plan or promised
    if pi.previous_response in ("promised", "scheduled"):
        return PolicyAction(
            action="PROPOSE_PAYMENT_PLAN",
            reason="Customer already promised/scheduled — wait for payment",
            allowed=False,
        )

    # Only useful for larger amounts
    if pi.amount >= PAYMENT_PLAN_THRESHOLD:
        return PolicyAction(
            action="PROPOSE_PAYMENT_PLAN",
            reason=f"Amount ₹{pi.amount // 100} >= ₹{PAYMENT_PLAN_THRESHOLD // 100} — payment plan appropriate",
            allowed=True,
            priority=65,
        )

    return PolicyAction(
        action="PROPOSE_PAYMENT_PLAN",
        reason=f"Amount ₹{pi.amount // 100} < ₹{PAYMENT_PLAN_THRESHOLD // 100} — plan not needed",
        allowed=False,
    )


def _eval_schedule_reminder(pi: PolicyInput) -> PolicyAction:
    """SCHEDULE_REMINDER — schedule a follow-up reminder."""
    # Case is terminal
    if pi.case_status in TERMINAL_STATUSES:
        return PolicyAction(
            action="SCHEDULE_REMINDER",
            reason=f"Case is {pi.case_status} — no reminders",
            allowed=False,
        )

    # Max attempts reached
    if pi.attempt_count >= pi.max_attempts:
        return PolicyAction(
            action="SCHEDULE_REMINDER",
            reason="Maximum attempts reached — no more reminders",
            allowed=False,
        )

    # Payment already captured
    if pi.payment_status == "captured":
        return PolicyAction(
            action="SCHEDULE_REMINDER",
            reason="Payment already captured — no reminders needed",
            allowed=False,
        )

    # Already promised — wait, don't spam
    if pi.previous_response == "promised":
        return PolicyAction(
            action="SCHEDULE_REMINDER",
            reason="Customer promised to pay — wait for scheduled payment",
            allowed=False,
        )

    # Can't schedule if already at max
    if pi.attempt_count >= pi.max_attempts - 1:
        return PolicyAction(
            action="SCHEDULE_REMINDER",
            reason="Last attempt — don't schedule further reminders",
            allowed=False,
        )

    # Reminders are useful for no_response cases
    if pi.previous_response == "no_response" or pi.previous_response is None:
        return PolicyAction(
            action="SCHEDULE_REMINDER",
            reason="No response received — schedule follow-up reminder",
            allowed=True,
            priority=55,
        )

    # After any other response, reminder is less urgent
    return PolicyAction(
        action="SCHEDULE_REMINDER",
        reason="Follow-up reminder after customer interaction",
        allowed=True,
        priority=35,
    )


# --- Recommendation logic ---


def _choose_recommended(allowed: list[PolicyAction], pi: PolicyInput) -> PolicyAction | None:
    """Choose the single best action from allowed actions.

    Priority ordering:
    1. STOP_RECOVERY (if conditions met — highest priority)
    2. CREATE_PROMISE_TO_PAY (if customer promised — lock it in)
    3. SEND_PAYMENT_LINK (always useful for recovery)
    4. PROPOSE_PAYMENT_PLAN (for large amounts)
    5. SEND_WHATSAPP / SEND_EMAIL (channel preference)
    6. SEND_INVOICE (formal but slower)
    7. SCHEDULE_REMINDER (passive, least urgent)
    """
    if not allowed:
        return None

    # Sort by priority (highest first), then by predefined order
    action_priority_order = {
        "STOP_RECOVERY": 0,
        "CREATE_PROMISE_TO_PAY": 1,
        "SEND_PAYMENT_LINK": 2,
        "PROPOSE_PAYMENT_PLAN": 3,
        "SEND_WHATSAPP": 4,
        "SEND_EMAIL": 5,
        "SEND_INVOICE": 6,
        "SCHEDULE_REMINDER": 7,
    }

    def sort_key(a: PolicyAction) -> tuple:
        return (-a.priority, action_priority_order.get(a.action, 99))

    sorted_actions = sorted(allowed, key=sort_key)
    return sorted_actions[0]


def evaluate_single_action(pi: PolicyInput, action: str) -> PolicyAction:
    """Evaluate a single action against the policy rules.

    Useful when you want to check if a specific action is allowed
    without evaluating all actions.

    Args:
        pi: Policy input
        action: The action to evaluate (must be in ALLOWED_ACTIONS)

    Returns:
        PolicyAction with allowed/denied and reason
    """
    evaluators = {
        "STOP_RECOVERY": _eval_stop_recovery,
        "SEND_WHATSAPP": _eval_send_whatsapp,
        "SEND_EMAIL": _eval_send_email,
        "SEND_PAYMENT_LINK": _eval_send_payment_link,
        "SEND_INVOICE": _eval_send_invoice,
        "CREATE_PROMISE_TO_PAY": _eval_create_promise_to_pay,
        "PROPOSE_PAYMENT_PLAN": _eval_propose_payment_plan,
        "SCHEDULE_REMINDER": _eval_schedule_reminder,
    }

    evaluator = evaluators.get(action)
    if not evaluator:
        return PolicyAction(
            action=action,
            reason=f"Unknown action: {action}",
            allowed=False,
        )

    return evaluator(pi)
