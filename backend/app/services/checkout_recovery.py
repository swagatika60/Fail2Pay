"""Checkout Abandonment Recovery Service.

Handles the full lifecycle of checkout abandonment recovery:
1. Detect abandoned cart (from webhook or trigger endpoint)
2. Classify root cause (price hesitation, UX friction, payment failure, etc.)
3. Determine optimal re-engagement channel and timing
4. Execute bounded recovery: payment link, discount offer, or human handoff
5. Track re-engagement attempts and measure recovery

Recovery strategy is deterministic — AI is never in the loop for actions.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Root cause categories for checkout abandonment
ABANDONMENT_CAUSES = {
    "price_hesitation": {
        "label": "Price hesitation",
        "intervention": "discount_offer",
        "description": "Customer abandoned due to price sensitivity",
    },
    "ux_friction": {
        "label": "Checkout friction",
        "intervention": "simplified_payment_link",
        "description": "Customer dropped off during checkout flow",
    },
    "payment_failure": {
        "label": "Payment method failure",
        "intervention": "retry_with_alternative",
        "description": "Payment was attempted but failed at gateway",
    },
    "distraction": {
        "label": "Session timeout / distraction",
        "intervention": "payment_link_reminder",
        "description": "Customer left without completing checkout",
    },
    "comparison_shopping": {
        "label": "Comparison shopping",
        "intervention": "value_reinforcement",
        "description": "Customer is comparing options before purchasing",
    },
    "unknown": {
        "label": "Unknown cause",
        "intervention": "payment_link_reminder",
        "description": "Could not determine abandonment reason",
    },
}

# Re-engagement timing windows (hours after abandonment)
REENGAGEMENT_WINDOWS = {
    "immediate": 1,      # within 1 hour — strongest signal of intent
    "same_day": 24,       # within 24 hours — still warm
    "next_day": 48,       # within 48 hours — cooling off
    "final_nudge": 72,    # within 72 hours — last attempt before lost
}

# Maximum re-engagement attempts before marking as lost
MAXREENGAGEMENT_ATTEMPTS = 4


def classify_abandonment_cause(
    amount: int,
    abandonment_reason: str = "",
    source: str = "",
    metadata: dict | None = None,
) -> str:
    """Classify the likely cause of checkout abandonment.

    Deterministic keyword-based classification. Returns a canonical
    cause key from ABANDONMENT_CAUSES.
    """
    reason_lower = (abandonment_reason or "").lower()
    source_lower = (source or "").lower()
    meta = metadata or {}

    # Payment failure at gateway
    if any(kw in reason_lower for kw in ("payment", "failed", "declined", "error")):
        return "payment_failure"

    # Price-related signals
    if any(kw in reason_lower for kw in ("price", "expensive", "cost", "discount")):
        return "price_hesitation"

    # UX / session signals
    if any(kw in reason_lower for kw in ("timeout", "session", "expired", "abandoned")):
        return "distraction"

    # Cart page vs checkout page drop-off
    if source_lower == "cart_page":
        return "comparison_shopping"
    if source_lower == "payment_page":
        return "payment_failure"

    return "unknown"


def get_reengagement_window(reengagement_count: int) -> str:
    """Determine the timing window for the next re-engagement attempt."""
    if reengagement_count == 0:
        return "immediate"
    if reengagement_count == 1:
        return "same_day"
    if reengagement_count == 2:
        return "next_day"
    return "final_nudge"


def should_reengage(reengagement_count: int, status: str) -> bool:
    """Check if another re-engagement attempt is warranted."""
    if status in ("recovered", "lost", "cancelled"):
        return False
    return reengagement_count < MAXREENGAGEMENT_ATTEMPTS


def build_checkout_recovery_message(
    customer_name: str | None,
    amount: int,
    cause: str,
    reengagement_count: int,
    language: str = "en",
) -> str:
    """Build a deterministic re-engagement message based on cause and attempt.

    Language-aware: returns Hinglish when language is 'hi' or 'hi-en'.
    """
    name = customer_name or "there"
    rupees = f"₹{amount // 100:,}"
    cause_info = ABANDONMENT_CAUSES.get(cause, ABANDONMENT_CAUSES["unknown"])

    if language in ("hi", "hi-en"):
        return _hinglish_message(name, rupees, cause, reengagement_count)
    return _english_message(name, rupees, cause, reengagement_count)


def _english_message(name: str, rupees: str, cause: str, attempt: int) -> str:
    if attempt == 0:
        if cause == "payment_failure":
            return (
                f"Hi {name}! It looks like your payment of {rupees} didn't go through. "
                f"Here's a fresh link to complete your order: "
            )
        return (
            f"Hi {name}! You left something in your cart worth {rupees}. "
            f"Complete your order here: "
        )
    if attempt == 1:
        return (
            f"Hey {name}, just a quick reminder — your {rupees} order is still waiting. "
            f"Grab it before it's gone: "
        )
    return (
        f"Last chance, {name}! Your {rupees} cart expires soon. "
        f"Complete checkout now: "
    )


def _hinglish_message(name: str, rupees: str, cause: str, attempt: int) -> str:
    if attempt == 0:
        if cause == "payment_failure":
            return (
                f"Namaste {name} ji! Aapka {rupees} ka payment nahi ho paya. "
                f"Yeh raha naya link — abhi complete karein: "
            )
        return (
            f"Namaste {name} ji! Aapka {rupees} ka cart abhi bhi hai. "
            f"Order complete karein: "
        )
    if attempt == 1:
        return (
            f"Hi {name} ji! Aapka {rupees} ka order abhi available hai. "
            f"Jaldi karein: "
        )
    return (
        f"Last chance {name} ji! Aapka {rupees} ka cart expire ho raha hai. "
        f"Abhi checkout karein: "
    )


def track_checkout_abandonment(
    db: Session,
    *,
    customer_id,
    cart_ref: str,
    amount: int,
    currency: str = "INR",
    abandonment_reason: str = "",
    source: str = "checkout",
    metadata: dict | None = None,
) -> dict:
    """Record a checkout abandonment and initiate recovery.

    Creates a CheckoutAbandonment record, classifies the cause,
    and kicks off the bounded recovery workflow.
    """
    from app.models.checkout import CheckoutAbandonment

    cause = classify_abandonment_cause(amount, abandonment_reason, source, metadata)
    window = get_reengagement_window(0)

    checkout = CheckoutAbandonment(
        customer_id=customer_id,
        cart_ref=cart_ref,
        amount=amount,
        currency=currency,
        abandonment_reason=abandonment_reason or cause,
        source=source,
        status="abandoned",
        extra_data={
            "cause": cause,
            "reengagement_window": window,
            **(metadata or {}),
        },
    )
    db.add(checkout)
    db.commit()
    db.refresh(checkout)

    logger.info(
        "Checkout abandoned: cart=%s amount=%d cause=%s",
        cart_ref,
        amount,
        cause,
    )

    return {
        "checkout_id": str(checkout.id),
        "cause": cause,
        "cause_label": ABANDONMENT_CAUSES[cause]["label"],
        "reengagement_window": window,
        "status": "abandoned",
    }


def record_reengagement(
    db: Session,
    checkout_id,
    channel: str = "whatsapp",
) -> dict:
    """Record a re-engagement attempt on an abandoned checkout."""
    from app.models.checkout import CheckoutAbandonment

    checkout = db.get(CheckoutAbandonment, checkout_id)
    if not checkout:
        return {"error": "checkout_not_found"}

    if not should_reengage(checkout.reengagement_count, checkout.status):
        checkout.status = "lost"
        db.commit()
        return {"status": "lost", "reason": "max_reengagement_attempts"}

    checkout.reengagement_count += 1
    checkout.last_reengagement_at = datetime.now(timezone.utc)
    checkout.reengagement_channel = channel
    checkout.status = "recovering"
    db.commit()

    window = get_reengagement_window(checkout.reengagement_count)

    return {
        "checkout_id": str(checkout.id),
        "reengagement_count": checkout.reengagement_count,
        "window": window,
        "status": "recovering",
    }


def finalize_checkout_recovery(
    db: Session,
    checkout_id,
    recovered_amount: int = 0,
) -> dict:
    """Mark a checkout as recovered after successful payment."""
    from app.models.checkout import CheckoutAbandonment

    checkout = db.get(CheckoutAbandonment, checkout_id)
    if not checkout:
        return {"error": "checkout_not_found"}

    checkout.status = "recovered"
    checkout.extra_data = {**(checkout.extra_data or {}), "recovered_amount": recovered_amount}
    db.commit()

    return {
        "checkout_id": str(checkout.id),
        "status": "recovered",
        "recovered_amount": recovered_amount,
    }
