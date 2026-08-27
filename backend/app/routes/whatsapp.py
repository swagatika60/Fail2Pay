"""WhatsApp Webhook Routes.

Handles:
- GET /api/webhooks/whatsapp — Webhook verification
- POST /api/webhooks/whatsapp — Inbound messages and status updates
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.whatsapp import process_inbound_message, verify_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["whatsapp"])


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Verify WhatsApp webhook subscription.

    Meta sends this GET request to verify your webhook URL.
    You must respond with the challenge string if verification succeeds.
    """
    if not hub_mode or not hub_token or not hub_challenge:
        raise HTTPException(
            status_code=400,
            detail="Missing required query parameters: hub.mode, hub.verify_token, hub.challenge",
        )

    challenge = verify_webhook(hub_mode, hub_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status_code=403, detail="Webhook verification failed")

    # Return plain text challenge (not JSON)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=challenge)


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Process incoming WhatsApp messages and status updates.

    This endpoint receives:
    - Inbound text messages from customers
    - Delivery status updates (sent, delivered, read)
    - Read receipts

    Returns:
        200 OK with processing summary
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info("Received WhatsApp webhook payload")

    try:
        result = process_inbound_message(db, payload)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error("Error processing WhatsApp webhook: %s", str(e))
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Webhook processing error: {str(e)}",
        )
