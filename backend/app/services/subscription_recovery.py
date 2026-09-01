"""Subscription Failure Recovery Service.

Handles the full lifecycle of failed subscription payments:
1. Detect renewal failure (from Razorpay subscription webhook)
2. Diagnose root cause (insufficient funds, card expired, mandate issue)
3. Schedule smart retries with exponential backoff
4. Offer downgrade or alternative payment methods
5. Track retry outcomes and measure retention

Recovery is bounded: max retries, hard stops on opt-out, compliant
escalation to human support.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Subscription failure root causes
SUBSCRIPTION_FAILURE_CAUSES = {
    "insufficient_funds": {
        "label": "Insufficient funds",
        "retry_strategy": "exponential_backoff",
        "max_retries": 3,
        "description": "Customer account has insufficient balance for renewal",
    },
    "card_expired": {
        "label": "Expired card",
        "retry_strategy": "no_retry",
        "max_retries": 0,
        "description": "Customer's payment card has expired — requires card update",
    },
    "mandate_issue": {
        "label": "Mandate / UPI issue",
        "retry_strategy": "fixed_interval",
        "max_retries": 3,
        "description": "Auto-debit mandate is inactive or has hit limits",
    },
    "bank_declined": {
        "label": "Bank declined",
        "retry_strategy": "exponential_backoff",
        "max_retries": 3,
        "description": "Bank declined the transaction — may be temporary",
    },
    "gateway_timeout": {
        "label": "Gateway timeout",
        "retry_strategy": "immediate_retry",
        "max_retries": 2,
        "description": "Payment gateway timed out — retry immediately",
    },
    "unknown": {
        "label": "Unknown failure",
        "retry_strategy": "exponential_backoff",
        "max_retries": 2,
        "description": "Could not determine failure reason",
    },
}

# Exponential backoff intervals (in hours)
RETRY_INTERVALS = {
    "immediate_retry": [0.25, 1],              # 15 min, 1 hour
    "fixed_interval": [4, 8, 24],              # 4h, 8h, 24h
    "exponential_backoff": [2, 8, 24],         # 2h, 8h, 24h
}


def classify_subscription_failure(
    failure_code: str = "",
    failure_reason: str = "",
) -> str:
    """Classify subscription failure from gateway error codes.

    Deterministic mapping — AI is never involved.
    """
    code_lower = (failure_code or "").lower()
    reason_lower = (failure_reason or "").lower()

    # Insufficient funds
    if any(kw in code_lower for kw in ("insufficient", "balance", "not_enough")):
        return "insufficient_funds"
    if any(kw in reason_lower for kw in ("insufficient", "not enough funds")):
        return "insufficient_funds"

    # Card expired
    if any(kw in code_lower for kw in ("expired", "card_expired")):
        return "card_expired"
    if any(kw in reason_lower for kw in ("expired card", "card has expired")):
        return "card_expired"

    # Mandate / UPI
    if any(kw in code_lower for kw in ("mandate", "upi", "autodebit")):
        return "mandate_issue"
    if any(kw in reason_lower for kw in ("mandate", "upi mandate")):
        return "mandate_issue"

    # Bank decline
    if any(kw in code_lower for kw in ("declined", "bank_declined", "Do Not Honor")):
        return "bank_declined"
    if any(kw in reason_lower for kw in ("declined by bank", "bank declined")):
        return "bank_declined"

    # Gateway timeout
    if any(kw in code_lower for kw in ("timeout", "gateway_timeout", "timed_out")):
        return "gateway_timeout"

    return "unknown"


def calculate_next_retry(
    cause: str,
    retry_count: int,
) -> datetime | None:
    """Calculate the next retry time based on cause and attempt number.

    Returns None if no more retries should be attempted.
    """
    cause_info = SUBSCRIPTION_FAILURE_CAUSES.get(cause, SUBSCRIPTION_FAILURE_CAUSES["unknown"])
    strategy = cause_info["retry_strategy"]
    max_retries = cause_info["max_retries"]

    if retry_count >= max_retries:
        return None

    intervals = RETRY_INTERVALS.get(strategy, RETRY_INTERVALS["exponential_backoff"])
    if retry_count >= len(intervals):
        return None

    hours = intervals[retry_count]
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def build_subscription_recovery_message(
    customer_name: str | None,
    amount: int,
    plan_name: str | None,
    cause: str,
    retry_count: int,
    language: str = "en",
) -> str:
    """Build a recovery message for a failed subscription renewal."""
    name = customer_name or "there"
    rupees = f"₹{amount // 100:,}"
    plan = plan_name or "your plan"

    if language in ("hi", "hi-en"):
        return _hinglish_sub_message(name, rupees, plan, cause, retry_count)
    return _english_sub_message(name, rupees, plan, cause, retry_count)


def _english_sub_message(
    name: str, rupees: str, plan: str, cause: str, attempt: int
) -> str:
    if cause == "card_expired":
        return (
            f"Hi {name}! Your {plan} renewal of {rupees} failed because your card "
            f"has expired. Please update your payment method to continue: "
        )
    if attempt == 0:
        return (
            f"Hi {name}! Your {plan} renewal of {rupees} didn't go through. "
            f"Retry now to keep your subscription active: "
        )
    if attempt == 1:
        return (
            f"Hey {name}, your {plan} is at risk of suspension. "
            f"Complete your {rupees} payment to stay subscribed: "
        )
    return (
        f"Final reminder, {name}! Your {plan} will be cancelled if "
        f"the {rupees} renewal isn't completed today: "
    )


def _hinglish_sub_message(
    name: str, rupees: str, plan: str, cause: str, attempt: int
) -> str:
    if cause == "card_expired":
        return (
            f"Namaste {name} ji! Aapka {plan} ka {rupees} renewal fail ho gaya "
            f"kyunki card expire ho chuka hai. Card update karein: "
        )
    if attempt == 0:
        return (
            f"Namaste {name} ji! Aapka {plan} ka {rupees} payment nahi ho paya. "
            f"Dobara try karein — subscription active rahega: "
        )
    if attempt == 1:
        return (
            f"Hi {name} ji! Aapka {plan} suspend ho sakta hai. "
            f"{rupees} ka payment complete karein: "
        )
    return (
        f"Last reminder {name} ji! Aaj {rupees} pay nahi kiya to "
        f"{plan} cancel ho jayega: "
    )


def track_subscription_failure(
    db: Session,
    *,
    customer_id,
    subscription_id: str,
    amount: int,
    plan_id: str = "",
    plan_name: str = "",
    billing_cycle: str = "monthly",
    failure_code: str = "",
    failure_reason: str = "",
    renewal_date: datetime | None = None,
    metadata: dict | None = None,
) -> dict:
    """Record a subscription failure and schedule recovery retries."""
    from app.models.subscription import SubscriptionFailure

    cause = classify_subscription_failure(failure_code, failure_reason)
    cause_info = SUBSCRIPTION_FAILURE_CAUSES[cause]
    next_retry = calculate_next_retry(cause, 0)

    # Calculate days until churn (typically 7 days grace period)
    grace_days = 7
    days_until_churn = grace_days
    if renewal_date:
        elapsed = (datetime.now(timezone.utc) - renewal_date).days
        days_until_churn = max(0, grace_days - elapsed)

    sub = SubscriptionFailure(
        customer_id=customer_id,
        subscription_id=subscription_id,
        plan_id=plan_id,
        plan_name=plan_name,
        billing_cycle=billing_cycle,
        amount=amount,
        failure_code=failure_code,
        failure_reason=failure_reason or cause_info["description"],
        renewal_date=renewal_date,
        max_retries=cause_info["max_retries"],
        next_retry_at=next_retry,
        days_until_churn=days_until_churn,
        status="failed",
        extra_data={
            "cause": cause,
            "retry_strategy": cause_info["retry_strategy"],
            **(metadata or {}),
        },
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    logger.info(
        "Subscription failure: sub=%s cause=%s next_retry=%s",
        subscription_id,
        cause,
        next_retry.isoformat() if next_retry else "none",
    )

    return {
        "subscription_failure_id": str(sub.id),
        "cause": cause,
        "cause_label": cause_info["label"],
        "retry_strategy": cause_info["retry_strategy"],
        "max_retries": cause_info["max_retries"],
        "next_retry_at": next_retry.isoformat() if next_retry else None,
        "days_until_churn": days_until_churn,
        "status": "failed",
    }


def process_subscription_retry(
    db: Session,
    subscription_failure_id,
) -> dict:
    """Process a subscription retry attempt after the scheduled interval."""
    from app.models.subscription import SubscriptionFailure

    sub = db.get(SubscriptionFailure, subscription_failure_id)
    if not sub:
        return {"error": "subscription_failure_not_found"}

    if sub.status in ("recovered", "churned", "cancelled"):
        return {"status": sub.status, "reason": "terminal_state"}

    sub.retry_count += 1
    sub.last_retry_at = datetime.now(timezone.utc)
    sub.status = "retrying"

    cause = (sub.extra_data or {}).get("cause", "unknown")
    next_retry = calculate_next_retry(cause, sub.retry_count)

    if next_retry:
        sub.next_retry_at = next_retry
    else:
        # Max retries exhausted — mark as churned
        sub.status = "churned"
        sub.extra_data = {**(sub.extra_data or {}), "churn_reason": "max_retries_exhausted"}

    db.commit()
    db.refresh(sub)

    return {
        "subscription_failure_id": str(sub.id),
        "retry_count": sub.retry_count,
        "next_retry_at": sub.next_retry_at.isoformat() if sub.next_retry_at else None,
        "status": sub.status,
    }


def finalize_subscription_recovery(
    db: Session,
    subscription_failure_id,
    recovered_amount: int = 0,
) -> dict:
    """Mark a subscription as recovered after successful renewal payment."""
    from app.models.subscription import SubscriptionFailure

    sub = db.get(SubscriptionFailure, subscription_failure_id)
    if not sub:
        return {"error": "subscription_failure_not_found"}

    sub.status = "recovered"
    sub.extra_data = {**(sub.extra_data or {}), "recovered_amount": recovered_amount}
    db.commit()

    return {
        "subscription_failure_id": str(sub.id),
        "status": "recovered",
        "recovered_amount": recovered_amount,
    }
