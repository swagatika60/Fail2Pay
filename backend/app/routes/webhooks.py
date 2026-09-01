import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.webhook_handler import (
    process_mandate_auth_failed,
    process_order_paid,
    process_payment_captured,
    process_payment_failed,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str = Header(None),
):
    """Process Razorpay webhook events.

    This endpoint receives all Razorpay webhook events and processes them:
    - Verifies the webhook signature for security
    - Handles payment.failed events by creating recovery cases
    - Handles payment.captured events by updating recovery status
    - All processing is idempotent

    Returns:
        200 OK for successfully processed or skipped (duplicate) events
        400 Bad Request for invalid signatures
        422 Unprocessable Entity for unsupported event types
    """
    # Read the raw body for signature verification
    body = await request.body()

    # --- Step 1: Verify webhook signature ---
    if not verify_webhook_signature(body, x_razorpay_signature):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    # Parse the payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = payload.get("event", "")
    event_id = payload.get("id", "")

    logger.info("Received webhook: type=%s, id=%s", event_type, event_id)

    try:
        if event_type == "payment.failed":
            result = process_payment_failed(db, payload)
            return {"status": "ok", "event_type": event_type, "result": result}

        elif event_type == "payment.captured":
            result = process_payment_captured(db, payload)
            return {"status": "ok", "event_type": event_type, "result": result}

        elif event_type == "order.paid":
            result = process_order_paid(db, payload)
            return {"status": "ok", "event_type": event_type, "result": result}

        elif event_type in ("subscription.auth.failed", "payment.authorization.failed"):
            result = process_mandate_auth_failed(db, payload)
            return {"status": "ok", "event_type": event_type, "result": result}

        else:
            # Unsupported event type - return 200 but don't process
            logger.info("Ignoring unsupported event type: %s", event_type)
            return {
                "status": "ignored",
                "event_type": event_type,
                "reason": "unsupported_event_type",
            }

    except Exception as e:
        logger.error("Error processing webhook %s: %s", event_id, str(e))
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Webhook processing error: {str(e)}")
