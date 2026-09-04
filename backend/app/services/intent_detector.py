"""Bounded AI Intent Detection Service with Multilingual Support.

AI is ONLY responsible for understanding customer messages.
It must NOT directly execute actions. The backend decides what action to take.

Supports: English, Hindi, Hinglish, Odia
- Same intent taxonomy across languages
- Language-specific rule-based fallback
- AI can handle any language
- Language never changes safety rules

Architecture:
  1. Detect language from customer message
  2. Try AI-based intent detection (with timeout)
  3. If AI fails/unavailable → language-aware rule-based fallback
  4. If confidence below threshold → return UNCLEAR
  5. Backend maps intent → action (AI never does this)
"""

import json
import logging
import re
import time
from typing import Protocol

import httpx

from app.config import get_settings
from app.schemas.intent import (
    VALID_INTENTS,
    CustomerIntent,
    DEFAULT_CONFIDENCE_THRESHOLD,
    IntentDetectionRequest,
    IntentDetectionResponse,
    IntentDetectionResult,
)

logger = logging.getLogger(__name__)

# --- AI Provider Abstraction ---

# Google's OpenAI-compatible endpoint (works with Gemini API keys).
GOOGLE_GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
# Gemini API keys issued by Google AI Studio start with these prefixes.
GOOGLE_KEY_PREFIXES = ("AIza", "AQ.")
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def resolve_ai_provider_config(settings) -> tuple[str, str, str]:
    """Resolve (api_key, model, base_url) from settings with auto-detection.

    An explicit ``AI_BASE_URL`` always wins. When it is unset, Google-issued
    keys (``AIza…``/``AQ.…`` — Gemini API keys) route to Google's
    OpenAI-compatible endpoint with a Gemini model; everything else uses the
    OpenAI API. An explicit ``AI_MODEL`` is always respected.
    """
    api_key = (getattr(settings, "ai_api_key", "") or "").strip()
    base_url = (getattr(settings, "ai_base_url", "") or "").strip()
    model = (getattr(settings, "ai_model", "") or "").strip()
    is_google_key = api_key.startswith(GOOGLE_KEY_PREFIXES)
    if not base_url and is_google_key:
        base_url = GOOGLE_GEMINI_OPENAI_BASE_URL
        if not model or model == DEFAULT_OPENAI_MODEL:
            # The model was never explicitly set → pick a Gemini model.
            model = DEFAULT_GEMINI_MODEL
    return api_key, model or DEFAULT_OPENAI_MODEL, base_url or "https://api.openai.com/v1"


class AIProvider(Protocol):
    """Protocol for AI providers. Swap implementations for different LLMs."""

    def classify(self, system_prompt: str, user_message: str, timeout: float) -> str:
        """Send a classification request to the AI and return raw response text."""
        ...


class OpenAIProvider:
    """OpenAI-compatible API provider (works with OpenAI, Azure, etc.)."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def classify(self, system_prompt: str, user_message: str, timeout: float = 5.0) -> str:
        """Send classification request to OpenAI-compatible API."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.0,  # Deterministic responses
            "max_tokens": 100,
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    def complete(self, system_prompt: str, user_message: str, timeout: float = 5.0, max_tokens: int = 400) -> str:
        """Send a plain-text completion request (no JSON response format).

        Used by the AI Assist layer for free-form natural-language output
        (reply personalization, failure-reason explanations).
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.4,  # Low enough for consistent tone, high enough to feel human
            "max_tokens": max_tokens,
        }

        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]


class MockAIProvider:
    """Mock AI provider for testing."""

    def __init__(self, response: str = "", should_fail: bool = False):
        self._response = response
        self._should_fail = should_fail
        self.call_count = 0

    def classify(self, system_prompt: str, user_message: str, timeout: float = 10.0) -> str:
        self.call_count += 1
        if self._should_fail:
            raise RuntimeError("AI provider unavailable")
        return self._response

    def complete(self, system_prompt: str, user_message: str, timeout: float = 10.0, max_tokens: int = 400) -> str:
        self.call_count += 1
        if self._should_fail:
            raise RuntimeError("AI provider unavailable")
        return self._response


# --- System Prompt ---

INTENT_CLASSIFICATION_PROMPT = """Classify the customer message into ONE intent. Return ONLY JSON: {"intent": "INTENT", "confidence": 0.0-1.0}

Intents (pick the best match):
- PAY_NOW: wants to pay immediately ("pay now", "abhi pay")
- SPLIT_EMI: wants installments ("split", "EMI", "kist")
- PAY_LATER: wants to delay ("later", "baad mein", "tomorrow")
- PAYMENT_RETRY_REQUEST: wants to retry payment ("retry", "dobara pay")
- PAYMENT_PLAN_REQUEST: wants payment plan setup
- PROMISE_TO_PAY: promising to pay ("kal kar dunga", "will pay")
- PAYMENT_LINK_REQUEST: wants payment link ("send link", "link bhejo")
- INVOICE_REQUEST: wants invoice/bill ("send invoice", "bill bhejo")
- ALREADY_PAID: claims already paid
- QUESTION: general question about billing
- NEGATIVE: refusing/frustrated ("not paying", "nahi karunga")
- STOP_REQUEST: wants to stop messages
- SUPPORT: wants human agent
- GREETING: casual hello/thanks
- FALLBACK: uninterpretable
- UNCLEAR: ambiguous

Rules:
- Same rules for ALL languages (English, Hindi, Hinglish, Odia)
- Be conservative: high confidence (>0.8) only when clear
- You ONLY classify — never take actions or generate links
- Aliases are accepted and normalized: PAYMENT_NOW->PAY_NOW, PAYMENT_FAILED->PAYMENT_RETRY_REQUEST, SPLIT_PAYMENT->SPLIT_EMI, EMI/PAYMENT_PLAN->PAYMENT_PLAN_REQUEST, NEED_HELP->SUPPORT, NOT_INTERESTED->NEGATIVE, STOP_CONTACT->STOP_REQUEST, OTHER->UNCLEAR

Examples:
"hyy" → GREETING 0.9 | "pay now" → PAY_NOW 0.95 | "2 installments mein" → SPLIT_EMI 0.9
"Kal payment" → PROMISE_TO_PAY 0.85 | "link bhejo" → PAYMENT_LINK_REQUEST 0.9
"stop messaging" → STOP_REQUEST 0.95 | "talk to support" → SUPPORT 0.95
"baad mein" → PAY_LATER 0.85 | "pehle kar diya" → ALREADY_PAID 0.9
"dobara pay" → PAYMENT_RETRY_REQUEST 0.9 | "why charged" → QUESTION 0.85
"I can pay 2000 today" → PAY_NOW 0.9 | "I'll pay tomorrow" → PROMISE_TO_PAY 0.9
"i don't have the full amount right now" → PAYMENT_PLAN_REQUEST 0.9"""


# --- Deterministic Rule-Based Fallback ---


def _rule_based_classify(message: str, language: str = "en") -> IntentDetectionResult:
    """Deterministic rule-based intent classification with multilingual support.

    Used as fallback when AI is unavailable or times out.
    Uses language-specific patterns from the multilingual service.
    """
    from app.services.multilingual import get_patterns_for_language

    msg_lower = message.lower().strip()
    patterns = get_patterns_for_language(language)

    # Stop request patterns
    if patterns.stop and any(re.search(p, msg_lower) for p in patterns.stop):
        return IntentDetectionResult(intent=CustomerIntent.STOP_REQUEST, confidence=0.85)

    # Already paid patterns
    if patterns.already_paid and any(re.search(p, msg_lower) for p in patterns.already_paid):
        return IntentDetectionResult(intent=CustomerIntent.ALREADY_PAID, confidence=0.80)

    # Negative patterns (checked before promise — "not paying" is not a promise)
    if patterns.negative and any(re.search(p, msg_lower) for p in patterns.negative):
        return IntentDetectionResult(intent=CustomerIntent.NEGATIVE, confidence=0.80)

    # Pay-now patterns (checked before promise so "i'll pay now" reads as an
    # immediate payment intent, not a deferred one).
    if patterns.pay_now and any(re.search(p, msg_lower) for p in patterns.pay_now):
        return IntentDetectionResult(intent=CustomerIntent.PAY_NOW, confidence=0.85)

    # Promise to pay patterns
    if patterns.promise_to_pay and any(re.search(p, msg_lower) for p in patterns.promise_to_pay):
        return IntentDetectionResult(intent=CustomerIntent.PROMISE_TO_PAY, confidence=0.75)

    # Payment retry patterns
    if patterns.payment_retry and any(re.search(p, msg_lower) for p in patterns.payment_retry):
        return IntentDetectionResult(intent=CustomerIntent.PAYMENT_RETRY_REQUEST, confidence=0.80)

    # Invoice request patterns (checked before payment_link to avoid false positives)
    if patterns.invoice and any(re.search(p, msg_lower) for p in patterns.invoice):
        return IntentDetectionResult(intent=CustomerIntent.INVOICE_REQUEST, confidence=0.75)

    # Payment link request patterns
    if patterns.payment_link and any(re.search(p, msg_lower) for p in patterns.payment_link):
        return IntentDetectionResult(intent=CustomerIntent.PAYMENT_LINK_REQUEST, confidence=0.80)

    # Payment plan patterns
    if patterns.payment_plan and any(re.search(p, msg_lower) for p in patterns.payment_plan):
        return IntentDetectionResult(intent=CustomerIntent.PAYMENT_PLAN_REQUEST, confidence=0.80)

    # Support handoff patterns (checked before question to avoid false positives)
    _support_re = re.compile(
        r"\b(support|human|agent|representative|customer\s*service|speak\s*to|talk\s*to|"
        r"need\s*help|madad)\b",
        re.IGNORECASE,
    )
    if _support_re.search(msg_lower):
        return IntentDetectionResult(intent=CustomerIntent.SUPPORT, confidence=0.85)

    # Question patterns
    if patterns.question and any(re.search(p, msg_lower) for p in patterns.question):
        return IntentDetectionResult(intent=CustomerIntent.QUESTION, confidence=0.65)

    # Default: UNCLEAR
    return IntentDetectionResult(intent=CustomerIntent.UNCLEAR, confidence=0.30)


# --- AI Response Parsing ---


def _parse_ai_response(raw_response: str) -> IntentDetectionResult:
    """Parse and validate AI response into IntentDetectionResult.

    Validates that the intent is in the allowed set.
    Supports both canonical intent names and Recovery Specialist aliases.
    If invalid, returns UNCLEAR.
    """
    try:
        data = json.loads(raw_response)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse AI response as JSON: %s", raw_response)
        return IntentDetectionResult(
            intent=CustomerIntent.UNCLEAR,
            confidence=0.0,
            raw_response=raw_response,
        )

    intent_str = data.get("intent", "")
    confidence = float(data.get("confidence", 0.0))

    # Resolve Recovery Specialist aliases to canonical intent names
    from app.schemas.intent import RECOVERY_INTENT_ALIASES
    resolved_intent = RECOVERY_INTENT_ALIASES.get(intent_str, intent_str)

    # Validate intent is in allowed set
    if resolved_intent not in VALID_INTENTS:
        logger.warning("AI returned invalid intent: %s (not in allowed set)", intent_str)
        return IntentDetectionResult(
            intent=CustomerIntent.UNCLEAR,
            confidence=0.0,
            raw_response=raw_response,
        )

    # Clamp confidence to [0.0, 1.0]
    confidence = max(0.0, min(1.0, confidence))

    return IntentDetectionResult(
        intent=CustomerIntent(resolved_intent),
        confidence=confidence,
        raw_response=raw_response,
    )


# --- Main Detection Function ---


def detect_intent(
    request: IntentDetectionRequest,
    provider: AIProvider | None = None,
) -> IntentDetectionResponse:
    """Detect customer intent from a message.

    This is the main entry point. It:
    1. Detects the language of the message
    2. Tries AI-based classification (with timeout)
    3. Falls back to language-aware deterministic rules if AI fails
    4. Applies confidence threshold

    Args:
        request: The intent detection request with message and context
        provider: Optional AI provider override (for testing)

    Returns:
        IntentDetectionResponse with the detected intent and metadata
    """
    start_time = time.monotonic()
    settings = get_settings()
    confidence_threshold = settings.ai_confidence_threshold or DEFAULT_CONFIDENCE_THRESHOLD

    # --- Step 0: Detect language ---
    from app.services.multilingual import detect_language
    detected_language = detect_language(request.message)
    # Use provided language if it's more specific, otherwise use detected
    language = request.language if request.language != "en" else detected_language

    # Build system prompt with conversation history context
    system_prompt = INTENT_CLASSIFICATION_PROMPT
    if request.conversation_history:
        history_text = "\n".join(
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in request.conversation_history[-5:]  # Last 5 messages for context
        )
        system_prompt += f"\n\nRecent conversation context:\n{history_text}"

    user_message = f"[{language}] {request.message}"

    # --- Step 1: Try AI classification ---
    ai_result = None
    ai_available = True

    if provider is None and settings.ai_api_key:
        try:
            _api_key, _model, _base_url = resolve_ai_provider_config(settings)
            provider = OpenAIProvider(
                api_key=_api_key,
                model=_model,
                base_url=_base_url,
            )
        except Exception as e:
            logger.error("Failed to initialize AI provider: %s", str(e))
            ai_available = False

    if provider is not None:
        try:
            timeout = float(getattr(settings, "ai_timeout_seconds", 10))
            raw_response = provider.classify(system_prompt, user_message, timeout=timeout)
            ai_result = _parse_ai_response(raw_response)
        except httpx.TimeoutException:
            logger.warning("AI request timed out — falling back to rules")
            ai_available = False
        except httpx.HTTPStatusError as e:
            logger.warning("AI API error (status=%d) — falling back to rules", e.response.status_code)
            ai_available = False
        except Exception as e:
            logger.error("Unexpected AI error: %s — falling back to rules", str(e))
            ai_available = False

    # --- Step 2: Apply confidence threshold ---
    if ai_result is not None:
        elapsed_ms = (time.monotonic() - start_time) * 1000

        if ai_result.confidence >= confidence_threshold:
            return IntentDetectionResponse(
                result=ai_result,
                source="ai",
                ai_available=True,
                processing_time_ms=round(elapsed_ms, 2),
            )
        else:
            # Below threshold — return UNCLEAR with the AI's reasoning
            logger.info(
                "AI confidence %.2f below threshold %.2f — returning UNCLEAR",
                ai_result.confidence,
                confidence_threshold,
            )
            return IntentDetectionResponse(
                result=IntentDetectionResult(
                    intent=CustomerIntent.UNCLEAR,
                    confidence=ai_result.confidence,
                    raw_response=ai_result.raw_response,
                ),
                source="threshold_fallback",
                ai_available=True,
                processing_time_ms=round(elapsed_ms, 2),
            )

    # --- Step 3: Deterministic fallback (language-aware) ---
    # Use the language *detected from the message content* (script + keywords)
    # rather than the caller's coarse language hint. WhatsApp reports text
    # language as e.g. "hi" regardless of whether the customer wrote Devanagari
    # or Romanized Hinglish; detection is what actually reads the script, so a
    # Romanized "Kal payment kar dunga" maps to the hi-en patterns and classifies
    # as a promise instead of falling through to UNCLEAR.
    fallback_language = detected_language or language
    logger.info("Using rule-based fallback for intent detection (language=%s)", fallback_language)
    fallback_result = _rule_based_classify(request.message, fallback_language)
    elapsed_ms = (time.monotonic() - start_time) * 1000

    return IntentDetectionResponse(
        result=fallback_result,
        source="rule_based_fallback",
        ai_available=ai_available,
        processing_time_ms=round(elapsed_ms, 2),
    )
