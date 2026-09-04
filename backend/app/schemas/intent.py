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

    Primary intents (AI Recovery Specialist prompt):
      PAY_NOW          — customer wants to pay immediately
      SPLIT_EMI        — customer wants to split into installments
      PAY_LATER        — customer wants to delay payment
      GREETING         — casual greeting or acknowledgment
      SUPPORT          — wants to talk to a human agent
      FALLBACK         — uninterpretable message

    Legacy / granular intents (backward-compatible):
      PAYMENT_RETRY_REQUEST  — retry a failed payment
      PAYMENT_LINK_REQUEST   — asking for a payment link
      INVOICE_REQUEST        — wants an invoice
      PAYMENT_PLAN_REQUEST   — wants to set up a payment plan
      PROMISE_TO_PAY         — promising to pay (with or without a date)
      ALREADY_PAID           — claims they already paid
      QUESTION               — general question about billing
      NEGATIVE               — refusing to pay, angry, frustrated
      STOP_REQUEST           — wants to stop receiving messages
      UNCLEAR                — ambiguous or unsupported message
    """

    # --- Primary Recovery Specialist intents ---
    PAY_NOW = "PAY_NOW"
    SPLIT_EMI = "SPLIT_EMI"
    PAY_LATER = "PAY_LATER"
    GREETING = "GREETING"

    # --- Legacy / granular intents ---
    PAYMENT_RETRY_REQUEST = "PAYMENT_RETRY_REQUEST"
    PAYMENT_LINK_REQUEST = "PAYMENT_LINK_REQUEST"
    INVOICE_REQUEST = "INVOICE_REQUEST"
    PAYMENT_PLAN_REQUEST = "PAYMENT_PLAN_REQUEST"
    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    ALREADY_PAID = "ALREADY_PAID"
    QUESTION = "QUESTION"
    NEGATIVE = "NEGATIVE"
    STOP_REQUEST = "STOP_REQUEST"
    SUPPORT = "SUPPORT"
    UNCLEAR = "UNCLEAR"
    FALLBACK = "FALLBACK"


# Canonical intent name used in the AI Recovery Specialist prompt.
# Maps the AI's short-form routing keys to full CustomerIntent values.
RECOVERY_INTENT_ALIASES: dict[str, CustomerIntent] = {
    "PAY_NOW": CustomerIntent.PAY_NOW,
    "SPLIT_EMI": CustomerIntent.SPLIT_EMI,
    "PAY_LATER": CustomerIntent.PAY_LATER,
    "GREETING": CustomerIntent.GREETING,
    "SUPPORT": CustomerIntent.SUPPORT,
    "FALLBACK": CustomerIntent.FALLBACK,
    # Legacy mappings (kept for backward compatibility)
    "PAYMENT_RETRY_REQUEST": CustomerIntent.PAYMENT_RETRY_REQUEST,
    "PAYMENT_LINK_REQUEST": CustomerIntent.PAYMENT_LINK_REQUEST,
    "INVOICE_REQUEST": CustomerIntent.INVOICE_REQUEST,
    "PAYMENT_PLAN_REQUEST": CustomerIntent.PAYMENT_PLAN_REQUEST,
    "PROMISE_TO_PAY": CustomerIntent.PROMISE_TO_PAY,
    "ALREADY_PAID": CustomerIntent.ALREADY_PAID,
    "QUESTION": CustomerIntent.QUESTION,
    "NEGATIVE": CustomerIntent.NEGATIVE,
    "STOP_REQUEST": CustomerIntent.STOP_REQUEST,
    "UNCLEAR": CustomerIntent.UNCLEAR,
    # Recovery Agent challenge taxonomy (normalized to the canonical intents)
    "PAYMENT_NOW": CustomerIntent.PAY_NOW,
    "PAYMENT_FAILED": CustomerIntent.PAYMENT_RETRY_REQUEST,
    "SPLIT_PAYMENT": CustomerIntent.SPLIT_EMI,
    "EMI": CustomerIntent.PAYMENT_PLAN_REQUEST,
    "PAYMENT_PLAN": CustomerIntent.PAYMENT_PLAN_REQUEST,
    "NEED_HELP": CustomerIntent.SUPPORT,
    "NOT_INTERESTED": CustomerIntent.NEGATIVE,
    "STOP_CONTACT": CustomerIntent.STOP_REQUEST,
    "OTHER": CustomerIntent.UNCLEAR,
}

# Intents that should trigger a payment card widget in the UI.
PAYMENT_INTENTS: frozenset[CustomerIntent] = frozenset({
    CustomerIntent.PAY_NOW,
    CustomerIntent.SPLIT_EMI,
    CustomerIntent.PAYMENT_LINK_REQUEST,
    CustomerIntent.PAYMENT_RETRY_REQUEST,
    CustomerIntent.PAYMENT_PLAN_REQUEST,
    CustomerIntent.PROMISE_TO_PAY,
    CustomerIntent.QUESTION,
})

# Intents that are clarifications / handoffs / non-payment acknowledgments.
# These turns must NEVER carry the interactive payment-plan widgets.
NO_PAYMENT_WIDGET_INTENTS: frozenset[CustomerIntent] = frozenset({
    CustomerIntent.SUPPORT,
    CustomerIntent.FALLBACK,
    CustomerIntent.STOP_REQUEST,
    CustomerIntent.ALREADY_PAID,
    CustomerIntent.NEGATIVE,
    CustomerIntent.INVOICE_REQUEST,
    CustomerIntent.UNCLEAR,
    CustomerIntent.GREETING,
    CustomerIntent.PAY_LATER,
})


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
