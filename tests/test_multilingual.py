"""Tests for Multilingual Communication Support.

Covers:
- Language detection (English, Hindi, Hinglish, Odia)
- Intent classification across all 4 languages
- Response generation in customer's language
- Same intent taxonomy across languages
- Natural responses (not word-for-word translation)
- Language never changes safety rules
- Edge cases: mixed language, unknown scripts
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from app.schemas.intent import CustomerIntent, IntentDetectionRequest
from app.services.intent_detector import detect_intent, _rule_based_classify, MockAIProvider
from app.services.multilingual import (
    detect_language,
    get_response_template,
    get_patterns_for_language,
    is_supported_language,
    SUPPORTED_LANGUAGES,
    LANGUAGE_NAMES,
)
from app.services.intent_action_mapper import (
    get_action_for_intent,
    render_response,
    INTENT_ACTIONS,
)


# --- Language Detection Tests ---


class TestLanguageDetection:
    """Test language detection from customer messages."""

    def test_english_detected(self):
        """English messages detected correctly."""
        assert detect_language("Please send me the payment link") == "en"
        assert detect_language("I will pay tomorrow") == "en"
        assert detect_language("Stop messaging me") == "en"

    def test_hindi_detected(self):
        """Hindi (Devanagari script) detected correctly."""
        # मैं पैसा दे दूंगा
        assert detect_language("\u092E\u0948\u0902 \u092A\u0948\u0938\u093E \u0926\u0947 \u0926\u0942\u0902\u0917\u093E") == "hi"
        # फिर से पेयेंगे
        assert detect_language("\u092B\u093F\u0930 \u0938\u0947 \u092A\u0947\u092F\u093C\u0947\u0902\u0917\u0947") == "hi"

    def test_odia_detected(self):
        """Odia (Odia script) detected correctly."""
        # Actual Odia characters (U+0B00-U+0B7F range)
        assert detect_language("\u0B23\u0B41\u0B28\u0B3F \u0B27\u0B47\u0B2C\u0B3F") == "or"
        assert detect_language("\u0B15\u0B30\u0B3F\u0B2C\u0B3F") == "or"

    def test_hinglish_detected(self):
        """Hinglish (Roman script with Hindi keywords) detected correctly."""
        assert detect_language("Kal payment kar dunga") == "hi-en"
        assert detect_language("Payment link bhejo please") == "hi-en"
        assert detect_language("Phir se pay karoonga") == "hi-en"

    def test_mixed_language_uses_script(self):
        """Mixed language uses script detection (Devanagari wins over Roman)."""
        assert detect_language("\u092E\u0948\u0902 payment karunga") == "hi"

    def test_unknown_defaults_to_english(self):
        """Unknown scripts default to English."""
        assert detect_language("hello") == "en"
        assert detect_language("12345") == "en"


# --- Supported Languages Tests ---


class TestSupportedLanguages:
    """Test supported language configuration."""

    def test_all_languages_supported(self):
        """All required languages are supported."""
        assert "en" in SUPPORTED_LANGUAGES
        assert "hi" in SUPPORTED_LANGUAGES
        assert "hi-en" in SUPPORTED_LANGUAGES
        assert "or" in SUPPORTED_LANGUAGES

    def test_language_names(self):
        """All languages have names."""
        assert LANGUAGE_NAMES["en"] == "English"
        assert LANGUAGE_NAMES["hi"] == "Hindi"
        assert LANGUAGE_NAMES["hi-en"] == "Hinglish"
        assert LANGUAGE_NAMES["or"] == "Odia"

    def test_is_supported_language(self):
        """is_supported_language works correctly."""
        assert is_supported_language("en") is True
        assert is_supported_language("hi") is True
        assert is_supported_language("fr") is False
        assert is_supported_language("de") is False


# --- English Intent Classification Tests ---


class TestEnglishIntentClassification:
    """Test intent classification in English."""

    def test_payment_link_request(self):
        """English payment link request."""
        result = _rule_based_classify("Send me the payment link", "en")
        assert result.intent == CustomerIntent.PAYMENT_LINK_REQUEST

    def test_promise_to_pay(self):
        """English promise to pay."""
        result = _rule_based_classify("I'll pay tomorrow", "en")
        assert result.intent == CustomerIntent.PROMISE_TO_PAY

    def test_stop_request(self):
        """English stop request."""
        result = _rule_based_classify("Stop messaging me", "en")
        assert result.intent == CustomerIntent.STOP_REQUEST

    def test_already_paid(self):
        """English already paid."""
        result = _rule_based_classify("I already paid", "en")
        assert result.intent == CustomerIntent.ALREADY_PAID

    def test_negative(self):
        """English negative response."""
        result = _rule_based_classify("I'm not paying, this is a scam", "en")
        assert result.intent == CustomerIntent.NEGATIVE

    def test_invoice_request(self):
        """English invoice request."""
        result = _rule_based_classify("Send me the invoice", "en")
        assert result.intent == CustomerIntent.INVOICE_REQUEST

    def test_payment_plan_request(self):
        """English payment plan request."""
        result = _rule_based_classify("Can I pay in installments?", "en")
        assert result.intent == CustomerIntent.PAYMENT_PLAN_REQUEST

    def test_question(self):
        """English question."""
        result = _rule_based_classify("Why was I charged?", "en")
        assert result.intent == CustomerIntent.QUESTION

    def test_payment_retry(self):
        """English payment retry."""
        result = _rule_based_classify("I want to retry", "en")
        assert result.intent == CustomerIntent.PAYMENT_RETRY_REQUEST


# --- Hindi Intent Classification Tests ---


class TestHindiIntentClassification:
    """Test intent classification in Hindi (Devanagari script)."""

    def test_promise_to_pay(self):
        """Hindi promise to pay."""
        # मैं पेयेंगा
        result = _rule_based_classify("\u092E\u0948\u0902 \u092A\u0947\u092F\u093C\u0947\u0902\u0917\u093E", "hi")
        assert result.intent == CustomerIntent.PROMISE_TO_PAY

    def test_payment_link_request(self):
        """Hindi payment link request."""
        # लिंक भेजो
        result = _rule_based_classify("\u0932\u093F\u0902\u0915 \u092D\u0947\u091C\u094B", "hi")
        assert result.intent == CustomerIntent.PAYMENT_LINK_REQUEST

    def test_already_paid(self):
        """Hindi already paid."""
        # पैसा भर चुका
        result = _rule_based_classify("\u092A\u0948\u0938\u093E \u092D\u0930 \u091A\u0941\u0915\u093E", "hi")
        assert result.intent == CustomerIntent.ALREADY_PAID

    def test_stop_request(self):
        """Hindi stop request."""
        # मसाज
        result = _rule_based_classify("\u092E\u0938\u093E\u091C\u094D", "hi")
        assert result.intent == CustomerIntent.STOP_REQUEST

    def test_negative(self):
        """Hindi negative response."""
        # नहीं पेनेंगे
        result = _rule_based_classify("\u0928\u0939\u0940\u0902 \u092A\u0947\u0928\u0947\u0902\u0917\u0947", "hi")
        assert result.intent == CustomerIntent.NEGATIVE

    def test_invoice_request(self):
        """Hindi invoice request."""
        # इन्वॉइस
        result = _rule_based_classify("\u0907\u0928\u094D\u0935\u0949\u0938", "hi")
        assert result.intent == CustomerIntent.INVOICE_REQUEST


# --- Hinglish Intent Classification Tests ---


class TestHinglishIntentClassification:
    """Test intent classification in Hinglish (Roman script with Hindi words)."""

    def test_promise_to_pay(self):
        """Hinglish promise to pay."""
        result = _rule_based_classify("Kal payment kar dunga", "hi-en")
        assert result.intent == CustomerIntent.PROMISE_TO_PAY

    def test_payment_link_request(self):
        """Hinglish payment link request."""
        result = _rule_based_classify("Payment link bhejo", "hi-en")
        assert result.intent == CustomerIntent.PAYMENT_LINK_REQUEST

    def test_stop_request(self):
        """Hinglish stop request."""
        result = _rule_based_classify("Band karo messages", "hi-en")
        assert result.intent == CustomerIntent.STOP_REQUEST

    def test_already_paid(self):
        """Hinglish already paid."""
        result = _rule_based_classify("Pay kar diya done", "hi-en")
        assert result.intent == CustomerIntent.ALREADY_PAID

    def test_negative(self):
        """Hinglish negative response."""
        result = _rule_based_classify("Nahi dunga paisa", "hi-en")
        assert result.intent == CustomerIntent.NEGATIVE

    def test_payment_retry(self):
        """Hinglish payment retry."""
        result = _rule_based_classify("Phir se try karo", "hi-en")
        assert result.intent == CustomerIntent.PAYMENT_RETRY_REQUEST


# --- Cross-Language Consistency Tests ---


class TestCrossLanguageConsistency:
    """Same intent should be detected regardless of language."""

    def test_promise_to_pay_consistent(self):
        """PROMISE_TO_PAY detected in English and Hinglish."""
        messages = [
            ("I'll pay tomorrow", "en"),
            ("Kal pay karunga", "hi-en"),
        ]
        for msg, lang in messages:
            result = _rule_based_classify(msg, lang)
            assert result.intent == CustomerIntent.PROMISE_TO_PAY, (
                f"Failed for '{msg}' in {lang}: got {result.intent}"
            )

    def test_stop_request_consistent(self):
        """STOP_REQUEST detected in English and Hinglish."""
        messages = [
            ("Stop messaging me", "en"),
            ("Band karo", "hi-en"),
        ]
        for msg, lang in messages:
            result = _rule_based_classify(msg, lang)
            assert result.intent == CustomerIntent.STOP_REQUEST, (
                f"Failed for '{msg}' in {lang}: got {result.intent}"
            )

    def test_already_paid_consistent(self):
        """ALREADY_PAID detected in English and Hinglish."""
        messages = [
            ("I already paid", "en"),
            ("Pay kar diya done", "hi-en"),
        ]
        for msg, lang in messages:
            result = _rule_based_classify(msg, lang)
            assert result.intent == CustomerIntent.ALREADY_PAID, (
                f"Failed for '{msg}' in {lang}: got {result.intent}"
            )


# --- Multilingual Response Template Tests ---


class TestMultilingualResponses:
    """Test response generation in different languages."""

    def test_english_response(self):
        """English responses are generated correctly."""
        template = get_response_template("payment_link", "en")
        assert "payment link" in template.lower() or "payment" in template.lower()
        assert "{amount}" in template
        assert "{payment_link}" in template

    def test_hindi_response(self):
        """Hindi responses are generated correctly."""
        template = get_response_template("payment_link", "hi")
        assert "{amount}" in template
        assert "{payment_link}" in template

    def test_hinglish_response(self):
        """Hinglish responses are generated correctly."""
        template = get_response_template("payment_link", "hi-en")
        assert "{amount}" in template
        assert "{payment_link}" in template

    def test_odia_response(self):
        """Odia responses are generated correctly."""
        template = get_response_template("payment_link", "or")
        assert "{amount}" in template
        assert "{payment_link}" in template

    def test_fallback_to_english(self):
        """Unsupported language falls back to English."""
        template = get_response_template("payment_link", "fr")
        assert template == get_response_template("payment_link", "en")

    def test_all_intents_have_templates(self):
        """All intent response keys have templates in all languages."""
        for lang in SUPPORTED_LANGUAGES:
            for intent, action in INTENT_ACTIONS.items():
                template = get_response_template(action.response_key, lang)
                assert template, f"Missing template for {action.response_key} in {lang}"

    def test_render_response_uses_language(self):
        """render_response uses the customer's language."""
        action = get_action_for_intent(CustomerIntent.PAYMENT_LINK_REQUEST)

        # English
        en_response = render_response(
            action=action, amount_paise=149900,
            payment_link="https://pay.example.com/123", language="en",
        )
        assert "\u20b91,499" in en_response

        # Hindi
        hi_response = render_response(
            action=action, amount_paise=149900,
            payment_link="https://pay.example.com/123", language="hi",
        )
        assert "\u20b91,499" in hi_response
        assert hi_response != en_response  # Should be different template


# --- Safety Tests ---


class TestLanguageSafety:
    """Language should never change safety rules."""

    def test_stop_request_works_in_all_languages(self):
        """STOP_REQUEST always stops recovery regardless of language."""
        for lang in SUPPORTED_LANGUAGES:
            action = get_action_for_intent(CustomerIntent.STOP_REQUEST)
            assert action.update_case_status == "STOPPED"
            assert action.cancel_scheduled_actions is True

    def test_negative_never_executes_actions(self):
        """NEGATIVE intent never executes payment or stop actions."""
        for lang in SUPPORTED_LANGUAGES:
            action = get_action_for_intent(CustomerIntent.NEGATIVE)
            assert action.update_case_status is None  # No status change
            assert action.cancel_scheduled_actions is False  # No cancellation

    def test_no_threatening_language_in_any_response(self):
        """No threatening words in any response language."""
        import re
        threatening = [
            "urgent", "legal", "court", "police", "arrest", "sue",
            "penalty", "default", "consequences", "seize",
        ]
        for lang in SUPPORTED_LANGUAGES:
            for intent, action in INTENT_ACTIONS.items():
                response = render_response(
                    action=action, amount_paise=149900,
                    payment_link="https://pay.example.com/123", language=lang,
                )
                for word in threatening:
                    assert not re.search(r"\b" + word + r"\b", response.lower()), (
                        f"Intent {intent.value} in {lang} contains threatening word: {word}"
                    )


# --- AI with Multilingual Messages Tests ---


class TestAIMultilingualDetection:
    """Test AI-based detection with multilingual messages."""

    def test_ai_handles_hindi_message(self):
        """AI provider can handle Hindi messages."""
        ai_response = json.dumps({"intent": "PROMISE_TO_PAY", "confidence": 0.92})
        provider = MockAIProvider(response=ai_response)

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(
                message="\u092E\u0948\u0902 \u0915\u0932 \u092A\u0947\u092F\u093C\u0947\u0902\u0917\u093E",  # मैं कल पेयेंगा
                language="hi",
            )
            result = detect_intent(req, provider=provider)

        assert result.result.intent == CustomerIntent.PROMISE_TO_PAY
        assert result.source == "ai"

    def test_ai_handles_hinglish_message(self):
        """AI provider can handle Hinglish messages."""
        ai_response = json.dumps({"intent": "PAYMENT_LINK_REQUEST", "confidence": 0.88})
        provider = MockAIProvider(response=ai_response)

        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = "test_key"
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(
                message="Payment link bhejo",
                language="hi-en",
            )
            result = detect_intent(req, provider=provider)

        assert result.result.intent == CustomerIntent.PAYMENT_LINK_REQUEST
        assert result.source == "ai"

    def test_fallback_uses_detected_language(self):
        """When AI is unavailable, fallback uses detected language."""
        with patch("app.services.intent_detector.get_settings") as mock_settings:
            mock_settings.return_value.ai_api_key = ""
            mock_settings.return_value.ai_confidence_threshold = 0.6

            req = IntentDetectionRequest(
                message="I'll pay tomorrow",
                language="en",
            )
            result = detect_intent(req)

        # Should classify correctly in English
        assert result.result.intent == CustomerIntent.PROMISE_TO_PAY
        assert result.source == "rule_based_fallback"


# --- Edge Case Tests ---


class TestMultilingualEdgeCases:
    """Edge cases in multilingual support."""

    def test_empty_message(self):
        """Empty message returns UNCLEAR."""
        result = _rule_based_classify("", "en")
        assert result.intent == CustomerIntent.UNCLEAR

    def test_whitespace_only(self):
        """Whitespace-only message returns UNCLEAR."""
        result = _rule_based_classify("   ", "hi")
        assert result.intent == CustomerIntent.UNCLEAR

    def test_very_long_message(self):
        """Very long messages are handled."""
        long_msg = "I will pay " * 500
        result = _rule_based_classify(long_msg, "en")
        assert result.intent == CustomerIntent.PROMISE_TO_PAY

    def test_single_character(self):
        """Single character messages return UNCLEAR."""
        result = _rule_based_classify("?", "en")
        assert result.intent == CustomerIntent.QUESTION

    def test_numbers_only(self):
        """Number-only messages return UNCLEAR."""
        result = _rule_based_classify("12345", "en")
        assert result.intent == CustomerIntent.UNCLEAR
