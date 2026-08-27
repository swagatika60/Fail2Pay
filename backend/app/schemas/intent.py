"""Schemas for Bounded AI Intent Detection.

AI is ONLY responsible for understanding customer messages.
It must NOT directly execute actions. The backend decides what to do.

Allowed intents are strictly bounded — no arbitrary AI-generated commands.
"""

import enum
from pydantic import BaseModel, Field


class CustomerIntent(str, enum.Enum):
    """All allowed customer intents.

    These are the ONLY intents the AI can return.
    Any other intent is rejected and mapped to UNCLEAR.
    """

    PAYMENT_RETRY_REQUEST = "PAYMENT_RETRY_REQUEST"
    PAYMENT_LINK_REQUEST = "PAYMENT_LINK_REQUEST"
    INVOICE_REQUEST = "INVOICE_REQUEST"
    PAYMENT_PLAN_REQUEST = "PAYMENT_PLAN_REQUEST"
    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    ALREADY_PAID = "ALREADY_PAID"
    QUESTION = "QUESTION"
    NEGATIVE = "NEGATIVE"
    STOP_REQUEST = "STOP_REQUEST"
    UNCLEAR = "UNCLEAR"


# Set of all valid intent values for fast lookup
VALID_INTENTS: set[str] = {intent.value for intent in CustomerIntent}

# Default confidence threshold — below this, return UNCLEAR
DEFAULT_CONFIDENCE_THRESHOLD = 0.6


class IntentDetectionRequest(BaseModel):
    """Request to detect intent from a customer message."""

    message: str = Field(..., min_length=1, max_length=5000, description="Customer message text")
    language: str = Field(default="en", description="Language code of the message")
    conversation_history: list[dict] | None = Field(
        default=None,
        description="Recent conversation messages for context [{role: 'customer'|'agent', content: '...'}]",
    )


class IntentDetectionResult(BaseModel):
    """Structured result from intent detection.

    This is what the AI returns. The backend uses this to decide actions.
    AI never executes actions directly — it only classifies intent.
    """

    intent: CustomerIntent = Field(..., description="Detected customer intent")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    raw_response: str | None = Field(default=None, description="Raw AI response for debugging")


class IntentDetectionResponse(BaseModel):
    """Complete response from the intent detection service.

    Includes the result plus metadata about how it was determined.
    """

    result: IntentDetectionResult
    source: str = Field(
        ...,
        description="How intent was determined: 'ai', 'rule_based_fallback', or 'threshold_fallback'",
    )
    ai_available: bool = Field(default=True, description="Whether AI was available for this request")
    processing_time_ms: float | None = Field(default=None, description="Time taken for detection in ms")
