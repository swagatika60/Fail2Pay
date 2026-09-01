"""Hinglish Voice Recovery Service.

Provides an IVR-based (Interactive Voice Response) recovery channel using
Twilio for voice calls. Supports English and Hinglish TTS/STT.

Flow:
1. Outbound voice call initiated (from scheduler or manual trigger)
2. Customer answers → TwiML greeting in detected language
3. Customer speaks → STT transcription → intent classification
4. Agent response → TTS playback → payment link sent via SMS/WhatsApp
5. Conversation logged to audit trail

All voice interactions are logged and follow the same policy engine
guardrails as WhatsApp/email. Hard stops apply identically.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Voice greeting templates (TwiML-friendly plain text)
VOICE_GREETINGS = {
    "en": {
        "initial": (
            "Hello, this is an important call regarding your pending payment. "
            "Press 1 to pay now, press 2 to split into installments, "
            "or press 9 to speak with an agent."
        ),
        "payment_link": (
            "I've sent a payment link to your phone. "
            "Please check your messages and complete the payment. "
            "Thank you."
        ),
        "emi_offer": (
            "We can split your payment into easy installments. "
            "I've sent the details to your phone. "
            "Press 1 to confirm, or press 9 for support."
        ),
        "promise_ack": (
            "Thank you for your promise. We've noted your commitment. "
            "A reminder will be sent before the due date. Goodbye."
        ),
        "stop_ack": (
            "We've noted your request. You will not receive further calls. "
            "Goodbye."
        ),
        "fallback": (
            "Sorry, I didn't understand. "
            "Press 1 to pay now, or press 9 to speak with an agent."
        ),
    },
    "hi": {
        "initial": (
            "Namaste, yeh aapke pending payment ke baare mein ek zaroori call hai. "
            "Abhi pay karne ke liye 1 dabayein, kistoon mein baantne ke liye 2 dabayein, "
            "ya agent se baat karne ke liye 9 dabayein."
        ),
        "payment_link": (
            "Maine aapke phone par ek payment link bhej di hai. "
            "Kripya messages check karein aur payment complete karein. "
            "Dhanyavad."
        ),
        "emi_offer": (
            "Hum aapki payment ko aasaan kistoon mein baant sakte hain. "
            "Details aapke phone par bhej diye gaye hain. "
            "Confirm karne ke liye 1 dabayein, ya support ke liye 9 dabayein."
        ),
        "promise_ack": (
            "Aapke promise ke liye dhanyavad. Humne aapka commitment note kar liya hai. "
            "Due date se pehle reminder bhejega. Alvida."
        ),
        "stop_ack": (
            "Humne aapka request note kar liya hai. Aapko aur calls nahi aayengi. "
            "Alvida."
        ),
        "fallback": (
            "Maaf kijiye, main samajh nahi paya. "
            "Abhi pay karne ke liye 1 dabayein, ya agent se baat karne ke liye 9 dabayein."
        ),
    },
}

# DTMF (key press) intent mapping
DTMF_INTENT_MAP = {
    "1": "PAY_NOW",
    "2": "SPLIT_EMI",
    "3": "PAY_LATER",
    "9": "SUPPORT",
    "0": "SUPPORT",
}

# STT confidence threshold for voice commands
VOICE_CONFIDENCE_THRESHOLD = 0.6


def generate_twiml_greeting(language: str = "en", case_id: str = "") -> str:
    """Generate TwiML XML for the initial IVR greeting.

    Returns TwiML that plays the greeting and gathers DTMF/voice input.
    """
    lang_key = "hi" if language in ("hi", "hi-en") else "en"
    greeting = VOICE_GREETINGS[lang_key]["initial"]

    # Escape XML special characters
    greeting = greeting.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="{"hi-IN" if lang_key == "hi" else "en-IN"}" voice="{"Polly.Aditi" if lang_key == "hi" else "Polly.Raveena"}">
        {greeting}
    </Say>
    <Gather numDigits="1" action="/api/voice/ivr-action" method="POST"
            timeout="10" numAttempts="2">
        <Say language="{"hi-IN" if lang_key == "hi" else "en-IN"}" voice="{"Polly.Aditi" if lang_key == "hi" else "Polly.Raveena"}">
            {"1 dabayein ya 9 dabayein." if lang_key == "hi" else "Press a key."}
        </Say>
    </Gather>
    <Redirect>/api/voice/ivr-action?Digits=timeout</Redirect>
</Response>"""


def generate_twiml_message(text: str, language: str = "en") -> str:
    """Generate TwiML for a spoken message."""
    lang_key = "hi" if language in ("hi", "hi-en") else "en"
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="{"hi-IN" if lang_key == "hi" else "en-IN"}" voice="{"Polly.Aditi" if lang_key == "hi" else "Polly.Raveena"}">
        {text}
    </Say>
</Response>"""


def generate_twiml_payment_link(
    payment_url: str, amount: int, language: str = "en"
) -> str:
    """Generate TwiML that announces the payment link and sends it via SMS."""
    lang_key = "hi" if language in ("hi", "hi-en") else "en"
    rupees = f"₹{amount // 100:,}"
    msg = VOICE_GREETINGS[lang_key]["payment_link"]
    msg = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    payment_url_escaped = payment_url.replace("&", "&amp;")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="{"hi-IN" if lang_key == "hi" else "en-IN"}" voice="{"Polly.Aditi" if lang_key == "hi" else "Polly.Raveena"}">
        {msg}
    </Say>
    <Message>Aapka payment link: {payment_url} ({rupees})</Message>
    <Pause length="3"/>
    <Hangup/>
</Response>"""


def generate_twiml_stop(language: str = "en") -> str:
    """Generate TwiML for opt-out acknowledgment."""
    lang_key = "hi" if language in ("hi", "hi-en") else "en"
    msg = VOICE_GREETINGS[lang_key]["stop_ack"]
    msg = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="{"hi-IN" if lang_key == "hi" else "en-IN"}" voice="{"Polly.Aditi" if lang_key == "hi" else "Polly.Raveena"}">
        {msg}
    </Say>
    <Hangup/>
</Response>"""


def generate_twiml_fallback(language: str = "en") -> str:
    """Generate TwiML for unrecognized input."""
    lang_key = "hi" if language in ("hi", "hi-en") else "en"
    msg = VOICE_GREETINGS[lang_key]["fallback"]
    msg = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="{"hi-IN" if lang_key == "hi" else "en-IN"}" voice="{"Polly.Aditi" if lang_key == "hi" else "Polly.Raveena"}">
        {msg}
    </Say>
    <Gather numDigits="1" action="/api/voice/ivr-action" method="POST" timeout="10">
        <Say language="{"hi-IN" if lang_key == "hi" else "en-IN"}" voice="{"Polly.Aditi" if lang_key == "hi" else "Polly.Raveena"}">
            {"1 ya 9 dabayein." if lang_key == "hi" else "Press 1 or 9."}
        </Say>
    </Gather>
    <Redirect>/api/voice/ivr-action?Digits=timeout</Redirect>
</Response>"""


def map_dtmf_to_intent(digits: str) -> str:
    """Map DTMF key press to an intent string."""
    return DTMF_INTENT_MAP.get(digits, "UNCLEAR")


def transcribe_voice_to_intent(transcription: str, confidence: float) -> str:
    """Map STT transcription text to an intent.

    Uses keyword matching (same pattern as multilingual intent detection).
    Returns UNCLEAR if confidence is too low.
    """
    if confidence < VOICE_CONFIDENCE_THRESHOLD:
        return "UNCLEAR"

    text = transcription.lower().strip()

    if any(kw in text for kw in ("pay now", "abhi pay", "abhi kar", "pay kar")):
        return "PAY_NOW"
    if any(kw in text for kw in ("installment", "split", "kist", "emi")):
        return "SPLIT_EMI"
    if any(kw in text for kw in ("later", "baad", "kal", "tomorrow")):
        return "PAY_LATER"
    if any(kw in text for kw in ("stop", "unsubscribe", "band")):
        return "STOP_REQUEST"
    if any(kw in text for kw in ("support", "agent", "human", "baat")):
        return "SUPPORT"

    return "UNCLEAR"


def log_voice_interaction(
    db: Session,
    case_id,
    *,
    call_sid: str = "",
    direction: str = "outbound",
    duration_seconds: int = 0,
    transcription: str = "",
    intent: str = "",
    dtmf_input: str = "",
    language: str = "en",
    status: str = "completed",
) -> dict:
    """Log a voice interaction to the audit trail.

    Every voice call is persisted for compliance and debugging.
    """
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate

    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case_id,
            entity_type="voice_call",
            entity_id=case_id,
            action="voice_interaction",
            new_value={
                "call_sid": call_sid,
                "direction": direction,
                "duration_seconds": duration_seconds,
                "transcription": transcription,
                "intent": intent,
                "dtmf_input": dtmf_input,
                "language": language,
                "status": status,
            },
            extra_data={
                "channel": "voice",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ),
    )

    return {
        "logged": True,
        "call_sid": call_sid,
        "intent": intent,
        "language": language,
    }
