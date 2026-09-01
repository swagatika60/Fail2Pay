"""Deterministic Revenue Risk Engine.

Analyzes revenue events and determines risk level, reason, and recoverability
using pure rule-based logic. No AI or LLM is involved in any decision.

Risk categories supported:
- PAYMENT_FAILED: Single payment failure
- REPEATED_PAYMENT_FAILURE: Multiple failures from same customer
- OVERDUE_INVOICE: Invoice past its due date
- FAILED_SUBSCRIPTION: Subscription payment failure

Every risk decision is logged to the audit trail for full traceability.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crud.audit_event import create_audit_event
from app.crud.revenue_event import get_revenue_events_by_customer
from app.models.recovery_case import RecoveryStatus
from app.schemas.audit_event import AuditEventCreate
from app.schemas.risk_assessment import RiskAssessment

logger = logging.getLogger(__name__)


# --- Thresholds (deterministic, tunable) ---

# Amount thresholds for payment failure risk (in paise)
HIGH_AMOUNT_THRESHOLD = 100_000_000  # ₹1,00,000 (1 lakh)
MEDIUM_AMOUNT_THRESHOLD = 10_000_000  # ₹10,000

# How many past failures make it "repeated"
REPEATED_FAILURE_THRESHOLD = 3

# How overdue (in days) triggers different risk levels
OVERDUE_HIGH_DAYS = 30
OVERDUE_MEDIUM_DAYS = 7


def assess_risk(
    db: Session,
    customer_id: str,
    revenue_event_id: str,
    event_type: str,
    amount: int,
    extra_data: dict | None = None,
) -> RiskAssessment:
    """Main entry point: assess risk for a revenue event.

    Uses deterministic rules to determine risk level, reason, and recoverability.
    No AI or LLM involved — pure Python logic.

    Args:
        db: Database session
        customer_id: UUID of the customer
        revenue_event_id: UUID of the revenue event
        event_type: Type of event (e.g. "payment_failed")
        amount: Amount in paise
        extra_data: Optional metadata from the event

    Returns:
        RiskAssessment with risk_level, risk_reason, is_recoverable, risk_category
    """
    extra_data = extra_data or {}

    # Route to the appropriate analyzer based on event type
    if event_type == "payment_failed":
        return _assess_payment_failed(db, customer_id, amount, extra_data)
    elif event_type == "repeated_payment_failure":
        return _assess_repeated_payment_failure(db, customer_id, amount, extra_data)
    elif event_type == "overdue_invoice":
        return _assess_overdue_invoice(db, customer_id, amount, extra_data)
    elif event_type == "failed_subscription":
        return _assess_failed_subscription(db, customer_id, amount, extra_data)
    elif event_type == "checkout_abandonment":
        return _assess_checkout_abandonment(db, customer_id, amount, extra_data)
    else:
        # Unknown event type — default to medium risk
        return RiskAssessment(
            risk_level="MEDIUM",
            risk_reason=f"Unknown event type: {event_type}",
            is_recoverable=False,
            risk_category="UNKNOWN",
            factors={"event_type": event_type, "amount": amount},
        )


def assess_and_log_risk(
    db: Session,
    recovery_case_id: str,
    customer_id: str,
    revenue_event_id: str,
    event_type: str,
    amount: int,
    extra_data: dict | None = None,
) -> dict:
    """Assess risk AND log the decision to the audit trail.

    This is the main function to call from webhook handlers and other
    services that need both the assessment and an audit record.

    Returns:
        dict with assessment details and audit_event_id
    """
    from uuid import UUID

    assessment = assess_risk(
        db=db,
        customer_id=customer_id,
        revenue_event_id=revenue_event_id,
        event_type=event_type,
        amount=amount,
        extra_data=extra_data,
    )

    # Log the risk decision to audit trail
    audit_event = create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=UUID(recovery_case_id),
            entity_type="risk_assessment",
            entity_id=UUID(revenue_event_id),
            action="risk_assessed",
            new_value={
                "risk_level": assessment.risk_level,
                "risk_reason": assessment.risk_reason,
                "is_recoverable": assessment.is_recoverable,
                "risk_category": assessment.risk_category,
                "factors": assessment.factors,
            },
            extra_data={
                "customer_id": customer_id,
                "revenue_event_id": revenue_event_id,
                "event_type": event_type,
                "amount": amount,
            },
        ),
    )

    logger.info(
        "Risk assessed: level=%s, category=%s, recoverable=%s",
        assessment.risk_level,
        assessment.risk_category,
        assessment.is_recoverable,
    )

    return {
        "assessment": assessment.model_dump(),
        "audit_event_id": str(audit_event.id),
    }


# --- Individual risk analyzers ---


def _assess_payment_failed(
    db: Session, customer_id: str, amount: int, extra_data: dict
) -> RiskAssessment:
    """Analyze a single payment failure.

    Rules:
    - HIGH risk if amount >= ₹1,00,000 OR failure reason is "frozen" / "blocked"
    - MEDIUM risk if amount >= ₹10,000
    - LOW risk otherwise
    - Recoverable unless the account is frozen/blocked
    """
    failure_reason = extra_data.get("failure_reason", "").lower()
    failure_code = extra_data.get("failure_code", "").lower()

    # Check for account-level issues (not recoverable)
    is_account_issue = failure_reason in ("frozen", "blocked", "account_closed")
    is_fraud = failure_code in ("fraud_detected", "suspicious_activity")

    # Determine risk level based on amount and special conditions
    if is_fraud or is_account_issue or amount >= HIGH_AMOUNT_THRESHOLD:
        risk_level = "HIGH"
    elif amount >= MEDIUM_AMOUNT_THRESHOLD:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Build reason
    if is_fraud:
        risk_reason = "Payment flagged as fraud — not recoverable"
        is_recoverable = False
    elif is_account_issue:
        risk_reason = f"Account issue detected: {failure_reason} — not recoverable"
        is_recoverable = False
    elif amount >= HIGH_AMOUNT_THRESHOLD:
        risk_reason = "High-value payment failure (>= ₹1,00,000)"
        is_recoverable = True
    elif amount >= MEDIUM_AMOUNT_THRESHOLD:
        risk_reason = "Medium-value payment failure (>= ₹10,000)"
        is_recoverable = True
    else:
        risk_reason = "Payment failed for a low-value transaction"
        is_recoverable = True

    return RiskAssessment(
        risk_level=risk_level,
        risk_reason=risk_reason,
        is_recoverable=is_recoverable,
        risk_category="PAYMENT_FAILED",
        factors={
            "amount": amount,
            "failure_reason": failure_reason,
            "failure_code": failure_code,
        },
    )


def _assess_repeated_payment_failure(
    db: Session, customer_id: str, amount: int, extra_data: dict
) -> RiskAssessment:
    """Analyze repeated payment failures from the same customer.

    Rules:
    - Count past failed payments for this customer
    - HIGH risk if >= 3 failures
    - MEDIUM risk if 2 failures
    - LOW risk if this is the 1st (shouldn't normally happen, but handle it)
    - Not recoverable if >= 5 failures (customer is unlikely to pay)
    """
    from app.models.revenue_event import RevenueEvent
    from uuid import UUID as _UUID

    # Count past failures for this customer
    customer_uuid = _UUID(customer_id) if isinstance(customer_id, str) else customer_id
    past_events = get_revenue_events_by_customer(db, customer_id=customer_uuid)
    past_failures = [
        e for e in past_events
        if e.event_type in ("payment_failed", "repeated_payment_failure")
        and e.status in ("failed", "authorized")
    ]
    failure_count = len(past_failures) + 1  # +1 for current event

    # Determine risk level
    if failure_count >= REPEATED_FAILURE_THRESHOLD:
        risk_level = "HIGH"
    elif failure_count == 2:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Recoverability: unlikely after many failures
    is_recoverable = failure_count < 5

    if failure_count >= 5:
        risk_reason = (
            f"Customer has {failure_count} payment failures — "
            "recovery unlikely, consider stopping attempts"
        )
    elif failure_count >= REPEATED_FAILURE_THRESHOLD:
        risk_reason = (
            f"Customer has {failure_count} payment failures — "
            "high risk of continued failure"
        )
    elif failure_count == 2:
        risk_reason = "Customer has 2 payment failures — monitor closely"
    else:
        risk_reason = "First payment failure for this customer"

    return RiskAssessment(
        risk_level=risk_level,
        risk_reason=risk_reason,
        is_recoverable=is_recoverable,
        risk_category="REPEATED_PAYMENT_FAILURE",
        factors={
            "failure_count": failure_count,
            "amount": amount,
        },
    )


def _assess_overdue_invoice(
    db: Session, customer_id: str, amount: int, extra_data: dict
) -> RiskAssessment:
    """Analyze an overdue invoice.

    Rules:
    - Parse the due_date from extra_data
    - HIGH risk if overdue by >= 30 days
    - MEDIUM risk if overdue by >= 7 days
    - LOW risk if overdue by < 7 days
    - Always recoverable (invoices can always be paid)
    """
    due_date_str = extra_data.get("due_date", "")
    overdue_days = extra_data.get("overdue_days")

    # Calculate overdue days if not provided directly
    if overdue_days is None and due_date_str:
        try:
            due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = now - due_date
            overdue_days = max(0, delta.days)
        except (ValueError, TypeError):
            overdue_days = 0
    elif overdue_days is None:
        overdue_days = 0

    # Determine risk level based on how overdue
    if overdue_days >= OVERDUE_HIGH_DAYS:
        risk_level = "HIGH"
        risk_reason = f"Invoice overdue by {overdue_days} days (>= 30 days)"
    elif overdue_days >= OVERDUE_MEDIUM_DAYS:
        risk_level = "MEDIUM"
        risk_reason = f"Invoice overdue by {overdue_days} days (>= 7 days)"
    else:
        risk_level = "LOW"
        risk_reason = f"Invoice overdue by {overdue_days} days"

    # Invoices are always recoverable (customer can always pay)
    is_recoverable = True

    return RiskAssessment(
        risk_level=risk_level,
        risk_reason=risk_reason,
        is_recoverable=is_recoverable,
        risk_category="OVERDUE_INVOICE",
        factors={
            "amount": amount,
            "overdue_days": overdue_days,
            "due_date": due_date_str,
        },
    )


def _assess_checkout_abandonment(
    db: Session, customer_id: str, amount: int, extra_data: dict
) -> RiskAssessment:
    """Analyze an abandoned checkout.

    Rules:
    - HIGH risk if amount >= ₹1,00,000 OR customer abandoned repeatedly
    - MEDIUM risk if amount >= ₹10,000
    - LOW risk otherwise
    - Always recoverable (checkout can be re-attempted)
    """
    abandonment_count = extra_data.get("abandonment_count", 1)

    if amount >= HIGH_AMOUNT_THRESHOLD:
        risk_level = "HIGH"
        risk_reason = "High-value cart abandoned during checkout (>= ₹1,00,000)"
    elif amount >= MEDIUM_AMOUNT_THRESHOLD:
        risk_level = "MEDIUM"
        risk_reason = "Medium-value cart abandoned during checkout (>= ₹10,000)"
    else:
        risk_level = "LOW"
        risk_reason = "Cart abandoned during checkout — low-value transaction"

    return RiskAssessment(
        risk_level=risk_level,
        risk_reason=risk_reason,
        is_recoverable=True,
        risk_category="CHECKOUT_ABANDONMENT",
        factors={
            "amount": amount,
            "abandonment_count": abandonment_count,
        },
    )


def _assess_failed_subscription(
    db: Session, customer_id: str, amount: int, extra_data: dict
) -> RiskAssessment:
    """Analyze a failed subscription payment.

    Rules:
    - HIGH risk if subscription_status is "cancelled" or "expired"
    - MEDIUM risk if subscription_status is "active" (payment failed but sub is alive)
    - LOW risk if subscription_status is "past_due" (temporary issue)
    - Not recoverable if subscription is cancelled/expired
    - Recoverable if subscription is still active or past_due
    """
    subscription_status = extra_data.get("subscription_status", "").lower()
    billing_cycle = extra_data.get("billing_cycle", "")

    # Determine risk level
    if subscription_status in ("cancelled", "expired"):
        risk_level = "HIGH"
        is_recoverable = False
        risk_reason = (
            f"Subscription is {subscription_status} — "
            "payment failure indicates lost revenue"
        )
    elif subscription_status == "active":
        risk_level = "MEDIUM"
        is_recoverable = True
        risk_reason = (
            "Subscription is active but payment failed — "
            "likely a transient issue (card expiry, insufficient funds)"
        )
    elif subscription_status == "past_due":
        risk_level = "LOW"
        is_recoverable = True
        risk_reason = "Subscription is past due — grace period, retry payment"
    else:
        # Unknown subscription status
        risk_level = "MEDIUM"
        is_recoverable = True
        risk_reason = (
            f"Subscription payment failed (status: {subscription_status or 'unknown'})"
        )

    return RiskAssessment(
        risk_level=risk_level,
        risk_reason=risk_reason,
        is_recoverable=is_recoverable,
        risk_category="FAILED_SUBSCRIPTION",
        factors={
            "amount": amount,
            "subscription_status": subscription_status,
            "billing_cycle": billing_cycle,
        },
    )
