"""Schemas for the Recovery Policy Engine.

Defines the structured input/output for deterministic policy decisions.
No AI or LLM is involved in any policy decision.
"""

from pydantic import BaseModel


class PolicyInput(BaseModel):
    """All inputs the policy engine needs to make a decision."""

    amount: int  # amount in paise
    risk_level: str  # "HIGH", "MEDIUM", "LOW"
    attempt_count: int  # how many attempts have been made
    max_attempts: int = 5  # maximum allowed attempts
    customer_preferences: dict | None = None  # opt_out channels, communication prefs
    previous_response: str | None = None  # last customer response
    payment_status: str = "failed"  # current payment status
    recovery_history: list[dict] | None = None  # list of past actions taken
    case_status: str = "RECOVERY_IN_PROGRESS"  # current case status
    has_phone: bool = True  # whether customer has a phone number
    has_email: bool = True  # whether customer has an email


class PolicyAction(BaseModel):
    """A single policy decision output."""

    action: str  # one of the ALLOWED_ACTIONS
    reason: str  # why this action is allowed or denied
    allowed: bool  # whether the action is permitted
    priority: int = 0  # higher = more urgent (for ordering multiple allowed actions)


class PolicyDecision(BaseModel):
    """Complete policy decision with all evaluated actions."""

    allowed_actions: list[PolicyAction]
    denied_actions: list[PolicyAction]
    recommended_action: PolicyAction | None  # the single best action
