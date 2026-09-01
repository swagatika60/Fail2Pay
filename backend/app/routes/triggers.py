"""External revenue-trigger ingestion endpoints.

These endpoints let non-Razorpay systems (checkout, billing, subscription
infrastructure) push revenue-at-risk signals into the recovery pipeline:

    POST /api/triggers/checkout-abandoned
    POST /api/triggers/aging-invoice
    POST /api/triggers/mandate-drop

Each call creates the revenue event → applies the deterministic risk policy →
spawns a recovery case → streams the agent-reasoning chain → starts the bounded
recovery workflow. Idempotent via external_event_id.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/triggers", tags=["triggers"])


class TriggerEvent(BaseModel):
    external_event_id: str = ""
    invoice_id: str = ""
    mandate_id: str = ""
    subscription_id: str = ""
    cart_ref: str = ""
    customer_id: str = ""
    email: str = ""
    phone: str = ""
    name: str | None = None
    amount: int = Field(0, description="Amount in paise")
    currency: str = "INR"
    due_date: str = ""
    overdue_days: int | None = None
    abandonment_count: int = 1
    failure_code: str = ""
    failure_reason: str = ""
    description: str = ""
    source: str = ""
    event_id: str = ""


@router.post("/checkout-abandoned")
def trigger_checkout_abandoned(payload: TriggerEvent, db: Session = Depends(get_db)):
    """Ingest a cart-abandonment signal as a recovery case."""
    from app.services import trigger_ingest

    return trigger_ingest.ingest_checkout_abandonment(db, payload.model_dump())


@router.post("/aging-invoice")
def trigger_aging_invoice(payload: TriggerEvent, db: Session = Depends(get_db)):
    """Ingest an overdue-invoice signal as a recovery case."""
    from app.services import trigger_ingest

    return trigger_ingest.ingest_aging_invoice(db, payload.model_dump())


@router.post("/mandate-drop")
def trigger_mandate_drop(payload: TriggerEvent, db: Session = Depends(get_db)):
    """Ingest a recurring-mandate-drop signal as a recovery case."""
    from app.services import trigger_ingest

    return trigger_ingest.ingest_mandate_drop(db, payload.model_dump())


@router.post("/subscription-failure")
def trigger_subscription_failure(payload: TriggerEvent, db: Session = Depends(get_db)):
    """Ingest a subscription renewal failure signal.

    Creates a SubscriptionFailure record and a linked RecoveryCase,
    then schedules smart retries based on the failure cause.
    """
    from app.services.subscription_recovery import track_subscription_failure
    from app.services import trigger_ingest

    # Create the recovery case via the standard pipeline
    case_result = trigger_ingest.ingest_trigger(
        db,
        trigger_type="subscription_failure",
        external_event_id=payload.external_event_id or payload.subscription_id,
        amount=payload.amount,
        customer_external_id=payload.customer_id,
        email=payload.email,
        phone=payload.phone,
        name=payload.name,
        failure_code=payload.failure_code,
        failure_reason=payload.failure_reason or payload.description,
        description=payload.description or "Subscription renewal failed",
        metadata={
            "subscription_id": payload.subscription_id,
            "plan_id": payload.customer_id,  # reuse field
            "currency": payload.currency,
            "source": payload.source or "razorpay_subscriptions",
        },
    )

    # Create the subscription failure record with retry scheduling
    if case_result.get("status") == "processed" and case_result.get("case_id"):
        from uuid import UUID

        from app.models.recovery_case import RecoveryCase
        case = db.get(RecoveryCase, UUID(case_result["case_id"]))
        if case:
            sub_result = track_subscription_failure(
                db,
                customer_id=case.customer_id,
                subscription_id=payload.subscription_id or case_result.get("case_id", ""),
                amount=payload.amount,
                plan_name=payload.description,
                failure_code=payload.failure_code,
                failure_reason=payload.failure_reason,
            )
            case_result["subscription_failure"] = sub_result

    return case_result