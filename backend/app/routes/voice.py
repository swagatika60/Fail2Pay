"""Voice Recovery Routes — Twilio Webhook Endpoints.

Exposes the IVR (Interactive Voice Response) endpoints for Hinglish
voice-based revenue recovery:

    POST /api/voice/inbound         — Twilio webhook for incoming calls
    POST /api/voice/outbound        — Initiate an outbound recovery call
    POST /api/voice/ivr-action      — DTMF/voice input handler
    POST /api/voice/status          — Call status callback

All voice interactions follow the same policy engine guardrails as
WhatsApp/email. Hard stops apply identically.
"""

import logging

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


class OutboundCallRequest(BaseModel):
    case_id: str = Field(..., description="Recovery case ID")
    to_phone: str = Field(..., description="Recipient phone number with country code")
    language: str = Field(default="en", description="Language for the call")


class IVRActionRequest(BaseModel):
    CallSid: str = ""
    CallStatus: str = ""
    Digits: str | None = None
    SpeechResult: str | None = None
    Confidence: str | None = None
    From: str = ""
    To: str = ""
    case_id: str | None = None


@router.post("/inbound")
async def handle_inbound_call(request: Request, db: Session = Depends(get_db)):
    """Handle incoming voice call via Twilio webhook.

    When a customer calls back after receiving a recovery call,
    this webhook answers and presents the IVR menu.
    """
    from app.services.voice_recovery import generate_twiml_greeting

    form = await request.form()
    call_sid = form.get("CallSid", "")
    from_phone = form.get("From", "")

    logger.info("Inbound voice call: sid=%s from=%s", call_sid, from_phone)

    # Try to find an active case for this phone number
    language = "en"
    case_id = ""

    from app.models.recovery_case import RecoveryCase, RecoveryStatus
    from app.models.customer import Customer
    from sqlalchemy import select

    customer = db.execute(
        select(Customer).where(Customer.phone == from_phone)
    ).scalars().first()

    if customer:
        case = db.execute(
            select(RecoveryCase)
            .where(
                RecoveryCase.customer_id == customer.id,
                RecoveryCase.status.notin_([
                    RecoveryStatus.RECOVERED,
                    RecoveryStatus.LOST,
                ]),
            )
            .order_by(RecoveryCase.created_at.desc())
        ).scalars().first()

        if case:
            case_id = str(case.id)
            language = (case.extra_data or {}).get("language", "en")

    twiml = generate_twiml_greeting(language=language, case_id=case_id)

    # Log the interaction
    from app.services.voice_recovery import log_voice_interaction
    if case_id:
        from uuid import UUID
        log_voice_interaction(
            db,
            UUID(case_id),
            call_sid=call_sid,
            direction="inbound",
            language=language,
        )

    return Response(content=twiml, media_type="application/xml")


@router.post("/outbound")
async def initiate_outbound_call(
    payload: OutboundCallRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Initiate an outbound recovery voice call via Twilio.

    This endpoint is called by the scheduler when a voice recovery
    action is scheduled.
    """
    from uuid import UUID
    from app.models.recovery_case import RecoveryCase, RecoveryStatus
    from app.services.voice_recovery import (
        generate_twiml_greeting,
        log_voice_interaction,
    )

    case = db.get(RecoveryCase, UUID(payload.case_id))
    if not case:
        return {"error": "case_not_found", "status": 404}

    # Hard stop check
    from app.services.hard_stop import check_hard_stop
    hard_stop = check_hard_stop(db, UUID(payload.case_id), action_type="voice_call")
    if hard_stop.blocked:
        return {
            "status": "blocked",
            "reason": hard_stop.reason,
            "stop_condition": hard_stop.stop_condition,
        }

    language = payload.language
    twiml = generate_twiml_greeting(language=language, case_id=payload.case_id)

    logger.info(
        "Outbound voice call initiated: case=%s to=%s lang=%s",
        payload.case_id,
        payload.to_phone,
        language,
    )

    # Log the outbound attempt
    log_voice_interaction(
        db,
        UUID(payload.case_id),
        direction="outbound",
        language=language,
        status="initiated",
    )

    # In production, this would call the Twilio REST API:
    # client.calls.create(to=to_phone, from=twilio_number, twiml=twiml)
    # For now, return the TwiML for testing
    return {
        "status": "initiated",
        "case_id": payload.case_id,
        "to_phone": payload.to_phone,
        "language": language,
        "twiml_preview": twiml[:200] + "...",
    }


@router.post("/ivr-action")
async def handle_ivr_action(request: Request, db: Session = Depends(get_db)):
    """Process DTMF or voice input from the IVR.

    Maps the input to an intent and returns the appropriate TwiML response.
    """
    from app.services.voice_recovery import (
        generate_twiml_payment_link,
        generate_twiml_stop,
        generate_twiml_fallback,
        generate_twiml_message,
        map_dtmf_to_intent,
        transcribe_voice_to_intent,
        log_voice_interaction,
    )

    form = await request.form()
    digits = form.get("Digits")
    speech_result = form.get("SpeechResult", "")
    confidence = float(form.get("Confidence", "0") or "0")
    call_sid = form.get("CallSid", "")
    from_phone = form.get("From", "")

    # Determine intent from DTMF or voice
    if digits and digits != "timeout":
        intent = map_dtmf_to_intent(digits)
        dtmf_input = digits
        transcription = ""
    elif speech_result:
        intent = transcribe_voice_to_intent(speech_result, confidence)
        dtmf_input = ""
        transcription = speech_result
    else:
        intent = "TIMEOUT"
        dtmf_input = "timeout"
        transcription = ""

    logger.info(
        "IVR action: sid=%s intent=%s digits=%s speech=%s",
        call_sid, intent, digits, speech_result[:50] if speech_result else "",
    )

    # Find the case for this call
    language = "en"
    case_id = None
    payment_url = ""

    from app.models.recovery_case import RecoveryCase, RecoveryStatus
    from app.models.customer import Customer
    from sqlalchemy import select

    customer = db.execute(
        select(Customer).where(Customer.phone == from_phone)
    ).scalars().first()

    if customer:
        case = db.execute(
            select(RecoveryCase)
            .where(
                RecoveryCase.customer_id == customer.id,
                RecoveryCase.status.notin_([
                    RecoveryStatus.RECOVERED,
                    RecoveryStatus.LOST,
                ]),
            )
            .order_by(RecoveryCase.created_at.desc())
        ).scalars().first()

        if case:
            case_id = case.id
            language = (case.extra_data or {}).get("language", "en")
            from app.services.agent_engine import payment_url_for_case
            payment_url = payment_url_for_case(str(case.id))

    # Log the interaction
    if case_id:
        log_voice_interaction(
            db,
            case_id,
            call_sid=call_sid,
            direction="inbound",
            transcription=transcription,
            intent=intent,
            dtmf_input=dtmf_input,
            language=language,
        )

    # Generate TwiML response based on intent
    if intent == "PAY_NOW" and payment_url:
        from app.models.recovery_case import RecoveryCase as RC
        case_obj = db.get(RC, case_id) if case_id else None
        amount = case_obj.remaining_amount if case_obj else 0
        twiml = generate_twiml_payment_link(payment_url, amount, language)
    elif intent == "STOP_REQUEST":
        twiml = generate_twiml_stop(language)
    elif intent == "SUPPORT":
        twiml = generate_twiml_message(
            "Hum aapko human agent se connect kar rahe hain. "
            if language in ("hi", "hi-en")
            else "I'm connecting you with a human agent. Please hold.",
            language,
        )
    elif intent == "TIMEOUT":
        # After timeout, disconnect gracefully
        twiml = generate_twiml_message(
            "Aapka call band ho raha hai. Phir se call karein."
            if language in ("hi", "hi-en")
            else "Ending call. Please call back when ready.",
            language,
        )
    else:
        twiml = generate_twiml_fallback(language)

    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def handle_call_status(request: Request, db: Session = Depends(get_db)):
    """Twilio status callback — receives call completion events.

    Logs the final call status for audit and analytics.
    """
    form = await request.form()
    call_sid = form.get("CallSid", "")
    call_status = form.get("CallStatus", "")
    call_duration = form.get("CallDuration", "0")

    logger.info(
        "Voice call status: sid=%s status=%s duration=%s",
        call_sid, call_status, call_duration,
    )

    return {"status": "received", "call_sid": call_sid}
