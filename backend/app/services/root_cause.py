"""Root Cause Diagnosis Agent.

Classifies *why* a revenue event is at risk so the recovery engine can pick the
bounded intervention that actually fits the failure:

- **TECHNICAL_RETRY**      → transient gateway/network blips best served by an
                            automated retry or a fresh mandate attempt.
- **LIQUIDITY_CONSTRAINT** → "insufficient_funds" / overdrawn limits — the
                            customer wants to pay but can't today; best served
                            by a split/EMI plan or a later-dated retry.
- **USER_HESITATION**      → checkout abandonment or a declined-decline loop;
                            best served by a gentle Hinglish nudge / discount or
                            a lower-friction payment link.
- **MANDATE_EXPIRY**       → recurring mandate declined/expired; best served by
                            a smart mandate re-setup flow with an updated
                            payment method.
- **ACCOUNT_ISSUE**        → frozen/blocked/closed accounts (not recoverable).
- **FRAUD_RISK**           → fraud-flagged transactions (hard stop, never chase).

Every classification is deterministic (no LLM in the decision), carries a
confidence + human-readable explanation, and maps onto the configured
intervention strategies so downstream policy evaluation stays bounded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class RootCause:
    """Canonical failure root-cause categories."""

    TECHNICAL_RETRY = "TECHNICAL_RETRY"
    LIQUIDITY_CONSTRAINT = "LIQUIDITY_CONSTRAINT"
    USER_HESITATION = "USER_HESITATION"
    MANDATE_EXPIRY = "MANDATE_EXPIRY"
    ACCOUNT_ISSUE = "ACCOUNT_ISSUE"
    FRAUD_RISK = "FRAUD_RISK"
    UNKNOWN = "UNKNOWN"


class Intervention:
    """Bounded intervention strategies the negotiation engine may deploy."""

    SMART_MANDATE_RETRY = "SMART_MANDATE_RETRY"
    HINGLISH_NEGOTIATION = "HINGLISH_NEGOTIATION"
    SPLIT_EMI_PLAN = "SPLIT_EMI_PLAN"
    INSTANT_PAYMENT_LINK = "INSTANT_PAYMENT_LINK"
    DEFERRED_RETRY = "DEFERRED_RETRY"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
    HARD_STOP = "HARD_STOP"


@dataclass
class RootCauseDiagnosis:
    """Result of classifying a revenue at-risk event."""

    root_cause: str = RootCause.UNKNOWN
    label: str = "Unknown cause"
    confidence: float = 0.5
    explanation: str = ""
    recommended_intervention: str = Intervention.INSTANT_PAYMENT_LINK
    factors: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "root_cause": self.root_cause,
            "label": self.label,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "recommended_intervention": self.recommended_intervention,
            "factors": self.factors,
        }


# --- Gateway failure code → root cause (deterministic lookup) ---

# Error codes that mean the customer's payment instrument or bank cannot cover
# the charge right now (funds / limit pressure), not a technical glitch.
LIQUIDITY_CODES = {
    "insufficient_funds",
    "insufficient balance",
    "insufficient_balance",
    "bank_nsdc",
    "day_bank_decline",
    "daily_limit_exceeded",
    "limit_exceeded",
    "insufficient_limit",
    "no_funds",
    "account_overdrawn",
}

# Transient technical / gateway/network hiccups where a retry succeeds.
TECHNICAL_CODES = {
    "bank_timeout",
    "payment_gateway_timeout",
    "gateway_timeout",
    "timeout",
    "network_error",
    "network_timeout",
    "service_unavailable",
    "internal_server_error",
    "processing_error",
    "request_timed_out",
    "unknown_error",
    "technical_error",
    "temporary_issue",
    "gateway_unreachable",
    "connection_error",
}

# Recurring / autopay instrument failures — the stored mandate can no longer
# charge (declined, expired, revoked) or was never authorised.
MANDATE_CODES = {
    "mandate_declined",
    "mandate_expired",
    "mandate_cancelled",
    "mandate_revoked",
    "autopay_failed",
    "upi_mandate_failed",
    "recurring_payment_failed",
    "authorization_failed",
    "auth_failed",
    "submerchant_validation_failed",
    "registration_failed",
    "mandate_not_authorized",
    "subscription_failed",
    "upi_authorization_failed",
    "instrument_expired",
}

# Card/bank declining the customer's attempt — mixed signal, frequently a
# combination of hesitation and instrument issues; treated as user-side friction.
HESITATION_CODES = {
    "transaction_declined",
    "card_declined",
    "declined",
    "card_expired",
    "authentication_failed",
    "3ds_failed",
    "otp_incorrect",
    "otp_expired",
    "user_cancelled",
    "user_abandoned",
    "checkout_abandoned",
    "cancelled_by_user",
    "payment_cancelled",
}

# Account-level problems — the customer's ability to pay may be blocked.
ACCOUNT_ISSUE_CODES = {
    "frozen",
    "blocked",
    "account_closed",
    "account_frozen",
    "card_frozen",
    "blocked_by_bank",
    "account_suspended",
}

# Fraud-flagged events — never chased.
FRAUD_CODES = {
    "fraud_detected",
    "suspicious_activity",
    "fraud",
    "possible_fraud",
    "risky_card",
    "failed_kyc",
    "embargoed_account",
}

LABELS = {
    RootCause.TECHNICAL_RETRY: "Technical Glitch",
    RootCause.LIQUIDITY_CONSTRAINT: "Liquidity Constraint",
    RootCause.USER_HESITATION: "User Hesitation",
    RootCause.MANDATE_EXPIRY: "Mandate Expiry",
    RootCause.ACCOUNT_ISSUE: "Account Issue",
    RootCause.FRAUD_RISK: "Fraud Risk",
    RootCause.UNKNOWN: "Unknown",
}

# root cause → the intervention the negotiation engine should try first.
DEFAULT_INTERVENTION = {
    RootCause.TECHNICAL_RETRY: Intervention.SMART_MANDATE_RETRY,
    RootCause.LIQUIDITY_CONSTRAINT: Intervention.SPLIT_EMI_PLAN,
    RootCause.USER_HESITATION: Intervention.HINGLISH_NEGOTIATION,
    RootCause.MANDATE_EXPIRY: Intervention.SMART_MANDATE_RETRY,
    RootCause.ACCOUNT_ISSUE: Intervention.HUMAN_ESCALATION,
    RootCause.FRAUD_RISK: Intervention.HARD_STOP,
    RootCause.UNKNOWN: Intervention.INSTANT_PAYMENT_LINK,
}

EXPLANATIONS = {
    RootCause.TECHNICAL_RETRY: (
        "Gateway refused or timed out — transient. A bounded automated retry is "
        "the lowest-friction next step."
    ),
    RootCause.LIQUIDITY_CONSTRAINT: (
        "The payment instrument cannot currently cover the charge. A split plan "
        "or a later-dated retry respects the constraint without losing the case."
    ),
    RootCause.USER_HESITATION: (
        "The customer started (or restarted) the payment but did not complete it. "
        "A gentle personalized nudge with a low-friction link converts best."
    ),
    RootCause.MANDATE_EXPIRY: (
        "The recurring mandate can no longer be charged. Re-set up a fresh "
        "mandate with an explicit opt-in instead of re-using the dead one."
    ),
    RootCause.ACCOUNT_ISSUE: (
        "The account/instrument is frozen or blocked — not recoverable through "
        "automated channels. Escalate for human or legal handling."
    ),
    RootCause.FRAUD_RISK: (
        "Transaction flagged as fraud — automated recovery must never run here. "
        "Hard stop and refer to the risk team."
    ),
    RootCause.UNKNOWN: "No reliable failure signal — default to a secure payment link.",
}


def normalize_code(value: str | None) -> str:
    """Lower-case and de-duplicate a gateway code for lookups."""
    if not value:
        return ""
    return str(value).strip().lower()


def classify_root_cause(
    *,
    failure_code: str | None = None,
    failure_reason: str | None = None,
    event_type: str | None = None,
    trigger_type: str | None = None,
    extra: dict | None = None,
) -> RootCauseDiagnosis:
    """Classify a revenue event's failure into a canonical root cause.

    Precedence (highest first): fraud > account issue > mandate > liquidity >
    technical > hesitation > unknown. ``trigger_type`` overrides signal the
    ingestion layer when there was no gateway error at all (checkout
    abandonment, mandate drop, aging invoice).
    """
    extra = extra or {}
    code = normalize_code(failure_code)
    reason = normalize_code(failure_reason)
    event = (event_type or "").lower()
    trigger = (trigger_type or "").lower()

    signals = [code, reason, trigger, event, normalize_code(extra.get("failure_code")), normalize_code(extra.get("failure_reason"))]
    haystack = [s for s in signals if s]

    factors = {
        "failure_code": failure_code,
        "failure_reason": failure_reason,
        "event_type": event_type,
        "trigger_type": trigger_type,
    }

    def _in(codes: set[str]) -> bool:
        return any(any(c in s for c in codes) for s in haystack)

    # 1. Fraud — absolute hard stop, regardless of anything else.
    if _in(FRAUD_CODES):
        return _build(
            RootCause.FRAUD_RISK,
            confidence=0.98,
            explanation=EXPLANATIONS[RootCause.FRAUD_RISK],
            factors=factors,
        )

    # 2. Account-level blocks.
    if _in(ACCOUNT_ISSUE_CODES):
        return _build(
            RootCause.ACCOUNT_ISSUE,
            confidence=0.96,
            explanation=EXPLANATIONS[RootCause.ACCOUNT_ISSUE],
            factors=factors,
        )

    # 3. Recurring mandate lifecycle failures.
    if _in(MANDATE_CODES):
        return _build(
            RootCause.MANDATE_EXPIRY,
            confidence=0.94,
            explanation=EXPLANATIONS[RootCause.MANDATE_EXPIRY],
            factors=factors,
        )

    # 4. Funds / limit pressure.
    if _in(LIQUIDITY_CODES):
        return _build(
            RootCause.LIQUIDITY_CONSTRAINT,
            confidence=0.9,
            explanation=EXPLANATIONS[RootCause.LIQUIDITY_CONSTRAINT],
            factors=factors,
        )

    # 5. Transient technical failures.
    if _in(TECHNICAL_CODES):
        return _build(
            RootCause.TECHNICAL_RETRY,
            confidence=0.88,
            explanation=EXPLANATIONS[RootCause.TECHNICAL_RETRY],
            factors=factors,
        )

    # 6. User-side friction / hesitancy.
    if _in(HESITATION_CODES):
        return _build(
            RootCause.USER_HESITATION,
            confidence=0.82,
            explanation=EXPLANATIONS[RootCause.USER_HESITATION],
            factors=factors,
        )

    # 7. Structural triggers with no gateway error.
    if trigger == "checkout_abandoned":
        return _build(
            RootCause.USER_HESITATION,
            confidence=0.8,
            explanation=EXPLANATIONS[RootCause.USER_HESITATION],
            factors=factors,
        )
    if trigger == "aging_invoice":
        return _build(
            RootCause.USER_HESITATION,
            confidence=0.6,
            explanation="Invoice past its due date — typical of B2B remittance "
            "drag. A follow-up with the invoice copy wins most cases.",
            factors=factors,
        )
    if trigger == "mandate_drop":
        return _build(
            RootCause.MANDATE_EXPIRY,
            confidence=0.9,
            explanation=EXPLANATIONS[RootCause.MANDATE_EXPIRY],
            factors=factors,
        )

    # 8. Unknown.
    return _build(
        RootCause.UNKNOWN,
        confidence=0.4,
        explanation=EXPLANATIONS[RootCause.UNKNOWN],
        factors=factors,
    )


def _build(root_cause: str, *, confidence: float, explanation: str, factors: dict) -> RootCauseDiagnosis:
    return RootCauseDiagnosis(
        root_cause=root_cause,
        label=LABELS[root_cause],
        confidence=confidence,
        explanation=explanation,
        recommended_intervention=DEFAULT_INTERVENTION[root_cause],
        factors=factors,
    )


def intervention_for(root_cause: str) -> str:
    """Return the bounded intervention mapped to a root cause."""
    return DEFAULT_INTERVENTION.get(root_cause, Intervention.INSTANT_PAYMENT_LINK)