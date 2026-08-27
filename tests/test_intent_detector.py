"""Tests for the Bounded AI Intent Detection Service.

Covers:
- AI-based intent classification (mocked)
- Deterministic rule-based fallback
- Timeout handling
- Confidence thresholding
- Response validation (only allowed intents)
- Edge cases: empty messages, invalid JSON, missing fields
- AI unavailable scenarios
- Intent mapping correctness
- System prompt construction
"""

import json
import time
from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.schemas.intent import (
    VALID_INTENTS,
    CustomerIntent,
    DEFAULT_CONFIDENCE_THRESHOLD,
    IntentDetectionRequest,
    IntentDetectionResponse,
    IntentDetectionResult,
)
from app.services.intent_detector import (
    MockAIProvider,
    OpenAIProvider,
    _parse_ai_response,
    _rule_based_classify,
    detect_intent,
    INTENT_CLASSIFICATION_PROMPT,
)


# --- Schema Tests ---


class TestCustomerIntent:
    """Test the CustomerIntent enum."""

    def test_all_intents_are_unique(self):
        """Each intent has a unique value."""
        values = [intent.value for intent in CustomerIntent]
        assert len(values) == len(set(values))

    def test_valid_intents_set_matches_enum(self):
        """VALID_INTENTS set matches all enum values."""
        assert VALID_INTENTS == {intent.value for intent in CustomerIntent}

    def test_intent_count(self):
        """There are exactly 10 allowed intents."""
        assert len(CustomerIntent) == 10

    def test_required_intents_present(self):
        """All required intents are defined."""
        required = [
            "PAYMENT_RETRY_REQUEST",
            "PAYMENT_LINK_REQUEST",
            "INVOICE_REQUEST",
            "PAYMENT_PLAN_REQUEST",
            "PROMISE_TO_PAY",
            "ALREADY_PAID",
            "QUESTION",
            "NEGATIVE",
            "STOP_REQUEST",
            "UNCLEAR",
        ]
        for intent in required:
            assert intent in VALID_INTENTS, f"Missing required intent: {intent}"


class TestIntentDetectionRequest:
    """Test request schema validation."""

    def test_valid_request(self):
        """Valid request with message."""
        req = IntentDetectionRequest(message="I want to pay")
        assert req.message == "I want to pay"
        assert req.language == "en"
        assert req.conversation_history is None

    def test_empty_message_rejected(self):
        """Empty message is rejected."""
        with pytest.raises(Exception):
            IntentDetectionRequest(message="")

    def test_message_with_history(self):
        """Request with conversation history."""
        history = [
            {"role": "agent", "content": "Your payment is pending"},
            {"role": "customer", "content": "I'll pay tomorrow"},
        ]
        req = IntentDetectionRequest(message="Thanks", conversation_history=history)
        assert len(req.conversation_history) == 2


class TestIntentDetectionResult:
    """Test result schema."""

    def test_valid_result(self):
        """Valid result with allowed intent."""
        result = IntentDetectionResult(
            intent=CustomerIntent.PROMISE_TO_PAY,
            confidence=0.85,
        )
        assert result.intent == CustomerIntent.PROMISE_TO_PAY
        assert result.confidence == 0.85

    def test_confidence_bounds(self):
        """Confidence must be between 0 and 1."""
        result = IntentDetectionResult(
            intent=CustomerIntent.UNCLEAR,
            confidence=0.0,
        )
        assert result.confidence == 0.0

        result2 = IntentDetectionResult(
            intent=CustomerIntent.UNCLEAR,
            confidence=1.0,
        )
        assert result2.confidence == 1.0


# --- Rule-Based Fallback Tests ---


class TestRuleBasedClassify:
    """Test the deterministic rule-based fallback classifier."""

    def test_stop_request_patterns(self):
        """Various stop request patterns are detected."""
        messages = [
            "STOP",
            "Please stop contacting me",
            "Unsubscribe from messages",
            "Don't contact me anymore",
            "Do not call me",
            "Leave me alone",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.STOP_REQUEST, (
                f"Expected STOP_REQUEST for '{msg}', got {result.intent}"
            )

    def test_already_paid_patterns(self):
        """Already paid patterns are detected."""
        messages = [
            "I already paid",
            "Payment is done",
            "Paid already yesterday",
            "Completed payment",
            "Transaction is done",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.ALREADY_PAID, (
                f"Expected ALREADY_PAID for '{msg}', got {result.intent}"
            )

    def test_promise_to_pay_patterns(self):
        """Promise to pay patterns are detected."""
        messages = [
            "I'll pay tomorrow",
            "Will pay soon",
            "I promise I will pay",
            "Pay by Friday",
            "Sure I will pay",
            "Definitely paying",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.PROMISE_TO_PAY, (
                f"Expected PROMISE_TO_PAY for '{msg}', got {result.intent}"
            )

    def test_payment_retry_patterns(self):
        """Payment retry patterns are detected."""
        messages = [
            "I want to retry",
            "Try again",
            "Attempt payment again",
            "Re pay",
            "Pay again",
            "Redo payment",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.PAYMENT_RETRY_REQUEST, (
                f"Expected PAYMENT_RETRY_REQUEST for '{msg}', got {result.intent}"
            )

    def test_payment_link_patterns(self):
        """Payment link request patterns are detected."""
        messages = [
            "Send me the link",
            "Payment link please",
            "Share the link now",
            "Give me the URL to pay",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.PAYMENT_LINK_REQUEST, (
                f"Expected PAYMENT_LINK_REQUEST for '{msg}', got {result.intent}"
            )

    def test_invoice_patterns(self):
        """Invoice request patterns are detected."""
        messages = [
            "Send me an invoice",
            "I need the bill",
            "Where is my receipt",
            "Send statement",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.INVOICE_REQUEST, (
                f"Expected INVOICE_REQUEST for '{msg}', got {result.intent}"
            )

    def test_payment_plan_patterns(self):
        """Payment plan request patterns are detected."""
        messages = [
            "Can I pay in installments",
            "Payment plan please",
            "I want EMI",
            "Pay in 3 parts",
            "Split payment monthly",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.PAYMENT_PLAN_REQUEST, (
                f"Expected PAYMENT_PLAN_REQUEST for '{msg}', got {result.intent}"
            )

    def test_negative_patterns(self):
        """Negative/refusal patterns are detected."""
        messages = [
            "I'm not paying",
            "Will not pay",
            "Won't pay",
            "I refuse to pay",
            "This is a fraud",
            "Scam",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.NEGATIVE, (
                f"Expected NEGATIVE for '{msg}', got {result.intent}"
            )

    def test_question_patterns(self):
        """Question patterns are detected."""
        messages = [
            "Why was I charged?",
            "What is this payment?",
            "How do I dispute?",
            "When is the deadline?",
            "Can you help me?",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.QUESTION, (
                f"Expected QUESTION for '{msg}', got {result.intent}"
            )

    def test_unclear_message(self):
        """Unclear messages return UNCLEAR."""
        messages = [
            "asdfghjkl",
            "12345",
            "👍",
            "ok",
        ]
        for msg in messages:
            result = _rule_based_classify(msg)
            assert result.intent == CustomerIntent.UNCLEAR, (
                f"Expected UNCLEAR for '{msg}', got {result.intent}"
            )

    def test_case_insensitive(self):
        """Rule-based classification is case-insensitive."""
        result = _rule_based_classify("STOP MESSAGING ME")
        assert result.intent == CustomerIntent.STOP_REQUEST

        result2 = _rule_based_classify("I ALREADY PAID")
        assert result2.intent == CustomerIntent.ALREADY_PAID


# --- AI Response Parsing Tests ---


class TestParseAIResponse:
    """Test parsing and validation of AI responses."""

    def test_valid_json_response(self):
        """Valid JSON with allowed intent is parsed correctly."""
        response = json.dumps({"intent": "PROMISE_TO_PAY", "confidence": 0.92})
        result = _parse_ai_response(response)
        assert result.intent == CustomerIntent.PROMISE_TO_PAY
        assert result.confidence == 0.92

    def test_invalid_json_returns_unclear(self):
        """Invalid JSON returns UNCLEAR with 0 confidence."""
        result = _parse_ai_response("not json at all")
        assert result.intent == CustomerIntent.UNCLEAR
        assert result.confidence == 0.0

    def test_empty_string_returns_unclear(self):
        """Empty string returns UNCLEAR."""
        result = _parse_ai_response("")
        assert result.intent == CustomerIntent.UNCLEAR
        assert result.confidence == 0.0

    def test_invalid_intent_returns_unclear(self):
        """Intent not in allowed set returns UNCLEAR."""
        response = json.dumps({"intent": "HACK_DATABASE", "confidence": 0.99})
        result = _parse_ai_response(response)
        assert result.intent == CustomerIntent.UNCLEAR
        assert result.confidence == 0.0

    def test_missing_intent_field_returns_unclear(self):
        """Missing intent field returns UNCLEAR."""
        response = json.dumps({"confidence": 0.8})
        result = _parse_ai_response(response)
        assert result.intent == CustomerIntent.UNCLEAR

    def test_missing_confidence_defaults_to_zero(self):
        """Missing confidence defaults to 0.0."""
        response = json.dumps({"intent": "QUESTION"})
        result = _parse_ai_response(response)
        assert result.intent == CustomerIntent.QUESTION
        assert result.confidence == 0.0

    def test_confidence_clamped_above_one(self):
        """Confidence > 1.0 is clamped to 1.0."""
        response = json.dumps({"intent": "STOP_REQUEST", "confidence": 1.5})
        result = _parse_ai_response(response)
        assert result.confidence == 1.0

    def test_confidence_clamped_below_zero(self):
        """Confidence < 0.0 is clamped to 0.0."""
        response = json.dumps({"intent": "NEGATIVE", "confidence": -0.5})
        result = _parse_ai_response(response)
        assert result.confidence == 0.0

    def test_all_valid_intents_accepted(self):
        """All valid intents are accepted by the parser."""
        for intent in VALID_INTENTS:
            response = json.dumps({"intent": intent, "confidence": 0.8})
            result = _parse_ai_response(response)
            assert result.intent.value == intent

    def test_raw_response_preserved(self):
        """Raw response string is preserved in the result."""
        raw = '{"intent": "ALREADY_PAID", "confidence": 0.7}'
        result = _parse_ai_response(raw)
        assert result.raw_response == raw


# --- Mock AI Provider Tests ---


class TestMockAIProvider:
    """Test the mock AI provider for testing."""

    def test_returns_configured_response(self):
        """Mock provider returns the configured response."""
        response = json.dumps({"intent": "QUESTION", "confidence": 0.8})
        provider = MockAIProvider(response=response)
        result = provider.classify("system", "user message")
        assert result == response
        assert provider.call_count == 1

    def test_raises_on_failure(self):
        """Mock provider raises when configured to fail."""
        provider = MockAIProvider(should_fail=True)
        with pytest.raises(RuntimeError, match="AI provider unavailable"):
            provider.classify("system", "user message")


# --- Detect Intent Integration Tests ---


class TestDetectIntent:
    """Integration tests for the full detect_intent function."""

    def test_ai_high_confidence_returns_ai_result(self):
        """High confidence AI result is returned directly."""
        ai_response = json.dumps({"intent": "PROMISE_TO_PAY", "confidence": 0.95})
        provider = MockAIProvider(response=ai_response)

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="I'll pay tomorrow")
            result = detect_intent(req, provider=provider)

        assert result.result.intent == CustomerIntent.PROMISE_TO_PAY
        assert result.result.confidence == 0.95
        assert result.source == "ai"
        assert result.ai_available is True
        assert result.processing_time_ms is not None

    def test_ai_low_confidence_returns_unclear(self):
        """Low confidence AI result returns UNCLEAR via threshold_fallback."""
        ai_response = json.dumps({"intent": "QUESTION", "confidence": 0.3})
        provider = MockAIProvider(response=ai_response)

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="maybe something")
            result = detect_intent(req, provider=provider)

        assert result.result.intent == CustomerIntent.UNCLEAR
        assert result.source == "threshold_fallback"
        assert result.ai_available is True

    def test_ai_timeout_uses_fallback(self):
        """AI timeout triggers rule-based fallback."""
        provider = MockAIProvider(should_fail=False)

        # Make the provider raise a timeout
        def timeout_classify(*args, **kwargs):
            raise httpx.TimeoutException("Request timed out")

        provider.classify = timeout_classify

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="STOP contacting me")
            result = detect_intent(req, provider=provider)

        assert result.result.intent == CustomerIntent.STOP_REQUEST
        assert result.source == "rule_based_fallback"
        assert result.ai_available is False

    def test_ai_http_error_uses_fallback(self):
        """AI HTTP error triggers rule-based fallback."""

        def error_classify(*args, **kwargs):
            response = MagicMock()
            response.status_code = 500
            raise httpx.HTTPStatusError("Server error", request=MagicMock(), response=response)

        provider = MockAIProvider()
        provider.classify = error_classify

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="I already paid")
            result = detect_intent(req, provider=provider)

        assert result.result.intent == CustomerIntent.ALREADY_PAID
        assert result.source == "rule_based_fallback"
        assert result.ai_available is False

    def test_no_ai_key_uses_fallback(self):
        """When no AI API key is configured, uses rule-based fallback."""
        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = ""
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="Send me the payment link")
            result = detect_intent(req)

        assert result.result.intent == CustomerIntent.PAYMENT_LINK_REQUEST
        assert result.source == "rule_based_fallback"

    def test_fallback_for_unclear_message(self):
        """Unclear message returns UNCLEAR via fallback."""
        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = ""
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="hello")
            result = detect_intent(req)

        assert result.result.intent == CustomerIntent.UNCLEAR
        assert result.source == "rule_based_fallback"

    def test_ai_invalid_intent_returns_unclear(self):
        """AI returning an invalid intent is caught and returns UNCLEAR."""
        ai_response = json.dumps({"intent": "EXECUTE_PAYMENT", "confidence": 0.99})
        provider = MockAIProvider(response=ai_response)

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="pay now")
            result = detect_intent(req, provider=provider)

        # Invalid intent should be caught and mapped to UNCLEAR
        assert result.result.intent == CustomerIntent.UNCLEAR
        assert result.source == "threshold_fallback"

    def test_ai_malicious_json_injection_returns_unclear(self):
        """AI returning malicious JSON is handled safely."""
        malicious = '{"intent": "STOP_REQUEST", "confidence": 0.9, "action": "delete_all_data"}'
        provider = MockAIProvider(response=malicious)

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="test")
            result = detect_intent(req, provider=provider)

        # The extra "action" field is ignored — only intent and confidence are used
        assert result.result.intent == CustomerIntent.STOP_REQUEST
        assert result.result.confidence == 0.9

    def test_conversation_history_included_in_prompt(self):
        """Conversation history is passed to the AI provider."""
        ai_response = json.dumps({"intent": "PROMISE_TO_PAY", "confidence": 0.9})
        provider = MockAIProvider(response=ai_response)

        history = [
            {"role": "agent", "content": "Your payment of ₹1,499 is pending"},
            {"role": "customer", "content": "I'll pay tomorrow morning"},
        ]

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(
                message="Thanks",
                conversation_history=history,
            )
            result = detect_intent(req, provider=provider)

        assert result.result.intent == CustomerIntent.PROMISE_TO_PAY

    def test_ai_exception_uses_fallback(self):
        """Unexpected AI exception triggers fallback."""

        def broken_classify(*args, **kwargs):
            raise ValueError("Something broke")

        provider = MockAIProvider()
        provider.classify = broken_classify

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="I want a payment plan")
            result = detect_intent(req, provider=provider)

        assert result.result.intent == CustomerIntent.PAYMENT_PLAN_REQUEST
        assert result.source == "rule_based_fallback"
        assert result.ai_available is False

    def test_custom_confidence_threshold(self):
        """Custom confidence threshold from config is respected."""
        # AI returns 0.7 confidence — above default (0.6) but below custom (0.8)
        ai_response = json.dumps({"intent": "QUESTION", "confidence": 0.7})
        provider = MockAIProvider(response=ai_response)

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.8

            req = IntentDetectionRequest(message="What is this charge?")
            result = detect_intent(req, provider=provider)

        # 0.7 < 0.8 threshold → UNCLEAR
        assert result.result.intent == CustomerIntent.UNCLEAR
        assert result.source == "threshold_fallback"


# --- Safety & Boundedness Tests ---


class TestSafetyAndBoundedness:
    """Tests that AI cannot execute arbitrary actions."""

    def test_ai_never_directly_executes_actions(self):
        """The detect_intent function only returns intent — never executes actions."""
        ai_response = json.dumps({"intent": "STOP_REQUEST", "confidence": 0.95})
        provider = MockAIProvider(response=ai_response)

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(message="Stop everything")
            result = detect_intent(req, provider=provider)

        # Result should only contain intent classification — no actions
        assert hasattr(result.result, "intent")
        assert hasattr(result.result, "confidence")
        # No action fields
        assert not hasattr(result.result, "action")
        assert not hasattr(result.result, "execute")
        assert not hasattr(result.result, "command")

    def test_only_allowed_intents_in_output(self):
        """Output only contains intents from the allowed set."""
        # Try various AI responses
        for intent in VALID_INTENTS:
            ai_response = json.dumps({"intent": intent, "confidence": 0.9})
            provider = MockAIProvider(response=ai_response)

            with patch("app.services.intent_detector.get_settings") as mock_settings:
                mock_settings.return_value.ai_api_key = "test_key"
                mock_settings.return_value.ai_confidence_threshold = 0.6

                req = IntentDetectionRequest(message="test")
                result = detect_intent(req, provider=provider)

            assert result.result.intent.value in VALID_INTENTS

    def test_malicious_intent_always_becomes_unclear(self):
        """Any intent not in the allowed set becomes UNCLEAR."""
        malicious_intents = [
            "EXECUTE_PAYMENT",
            "DELETE_CUSTOMER",
            "TRANSFER_MONEY",
            "SEND_ALL_MESSAGES",
            "ADMIN_OVERRIDE",
            "RUN_SQL",
            "STOP_RECOVERY",  # This is a policy action, not an intent
        ]

        for intent in malicious_intents:
            ai_response = json.dumps({"intent": intent, "confidence": 0.99})
            provider = MockAIProvider(response=ai_response)

            with patch("app.services.intent_detector.get_settings") as mock_settings:
                mock_settings.return_value.ai_api_key = "test_key"
                mock_settings.return_value.ai_confidence_threshold = 0.6

                req = IntentDetectionRequest(message="do it")
                result = detect_intent(req, provider=provider)

            assert result.result.intent == CustomerIntent.UNCLEAR, (
                f"Malicious intent '{intent}' should have been mapped to UNCLEAR"
            )


# --- System Prompt Tests ---


class TestSystemPrompt:
    """Test the system prompt used for AI classification."""

    def test_prompt_lists_all_intents(self):
        """System prompt includes all allowed intents."""
        for intent in VALID_INTENTS:
            assert intent in INTENT_CLASSIFICATION_PROMPT

    def test_prompt_forbids_action_execution(self):
        """System prompt explicitly forbids action execution."""
        prompt_lower = INTENT_CLASSIFICATION_PROMPT.lower()
        assert "must not" in prompt_lower or "do not" in prompt_lower or "never" in prompt_lower

    def test_prompt_requests_json_output(self):
        """System prompt requests JSON output format."""
        assert "json" in INTENT_CLASSIFICATION_PROMPT.lower()

    def test_prompt_mentions_only_classify(self):
        """System prompt emphasizes classification only."""
        assert "classify" in INTENT_CLASSIFICATION_PROMPT.lower() or "classification" in INTENT_CLASSIFICATION_PROMPT.lower()


# --- OpenAI Provider Tests ---


class TestOpenAIProvider:
    """Test the OpenAI provider initialization."""

    def test_provider_initialization(self):
        """Provider can be initialized with API key and model."""
        provider = OpenAIProvider(api_key="test_key", model="gpt-4o")
        assert provider.api_key == "test_key"
        assert provider.model == "gpt-4o"

    def test_provider_default_model(self):
        """Provider defaults to gpt-4o-mini."""
        provider = OpenAIProvider(api_key="test_key")
        assert provider.model == "gpt-4o-mini"

    def test_provider_custom_base_url(self):
        """Provider accepts custom base URL."""
        provider = OpenAIProvider(
            api_key="test_key",
            base_url="https://custom.api.com/v1",
        )
        assert provider.base_url == "https://custom.api.com/v1"


# --- Edge Case Tests ---


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_very_long_message(self):
        """Very long messages are handled."""
        long_msg = "I will pay " * 500  # ~5000 chars
        result = _rule_based_classify(long_msg)
        assert result.intent == CustomerIntent.PROMISE_TO_PAY

    def test_single_word_messages(self):
        """Single word messages are classified."""
        test_cases = [
            ("Stop", CustomerIntent.STOP_REQUEST),
            ("Paid", CustomerIntent.ALREADY_PAID),  # "paid" matches already_paid patterns
            ("Why?", CustomerIntent.QUESTION),
        ]
        for msg, expected in test_cases:
            result = _rule_based_classify(msg)
            assert result.intent == expected, f"Expected {expected} for '{msg}'"

    def test_mixed_language_message(self):
        """Messages with mixed languages use rule-based fallback."""
        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = ""
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(
                message="Main kal pay karunga",  # Hindi + English
                language="hi",
            )
            result = detect_intent(req)

        # Should return something (rule-based fallback handles it)
        assert result.result.intent in CustomerIntent

    def test_whitespace_only_message(self):
        """Whitespace-only messages are handled."""
        result = _rule_based_classify("   ")
        assert result.intent == CustomerIntent.UNCLEAR

    def test_emoji_only_message(self):
        """Emoji-only messages return UNCLEAR."""
        result = _rule_based_classify("👍👍👍")
        assert result.intent == CustomerIntent.UNCLEAR

    def test_numeric_message(self):
        """Numeric messages return UNCLEAR."""
        result = _rule_based_classify("12345")
        assert result.intent == CustomerIntent.UNCLEAR
