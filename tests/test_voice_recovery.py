"""Tests for Hinglish Voice Recovery Service."""

import pytest

from app.services.voice_recovery import (
    generate_twiml_greeting,
    generate_twiml_message,
    generate_twiml_payment_link,
    generate_twiml_stop,
    generate_twiml_fallback,
    map_dtmf_to_intent,
    transcribe_voice_to_intent,
    VOICE_GREETINGS,
    DTMF_INTENT_MAP,
)


class TestTwimlGeneration:
    """Test TwiML XML generation for voice IVR."""

    def test_english_greeting_is_valid_xml(self):
        twiml = generate_twiml_greeting("en")
        assert '<?xml version="1.0"' in twiml
        assert "<Response>" in twiml
        assert "</Response>" in twiml
        assert "<Say" in twiml
        assert "<Gather" in twiml

    def test_hindi_greeting_uses_hindi_voice(self):
        twiml = generate_twiml_greeting("hi")
        assert "hi-IN" in twiml
        assert "Aditi" in twiml

    def test_english_greeting_uses_english_voice(self):
        twiml = generate_twiml_greeting("en")
        assert "en-IN" in twiml

    def test_hinglish_greeting_uses_hindi_voice(self):
        twiml = generate_twiml_greeting("hi-en")
        assert "hi-IN" in twiml

    def test_payment_link_twiml(self):
        twiml = generate_twiml_payment_link("https://pay.test/abc", 500000, "en")
        assert "pay.test/abc" in twiml
        assert "₹5,000" in twiml
        assert "<Message>" in twiml
        assert "<Hangup/>" in twiml

    def test_stop_twiml(self):
        twiml = generate_twiml_stop("en")
        assert "not receive" in twiml.lower() or "will not" in twiml.lower()
        assert "<Hangup/>" in twiml

    def test_fallback_twiml(self):
        twiml = generate_twiml_fallback("en")
        assert "Press 1" in twiml
        assert "<Gather" in twiml

    def test_message_twiml(self):
        twiml = generate_twiml_message("Hello world", "en")
        assert "Hello world" in twiml
        assert "<Say" in twiml

    def test_xml_special_chars_escaped(self):
        twiml = generate_twiml_message("A < B & C > D", "en")
        assert "&amp;" in twiml
        assert "&lt;" in twiml
        assert "&gt;" in twiml


class TestDTMFMapping:
    """Test DTMF key press to intent mapping."""

    def test_key_1_is_pay_now(self):
        assert map_dtmf_to_intent("1") == "PAY_NOW"

    def test_key_2_is_split_emi(self):
        assert map_dtmf_to_intent("2") == "SPLIT_EMI"

    def test_key_3_is_pay_later(self):
        assert map_dtmf_to_intent("3") == "PAY_LATER"

    def test_key_9_is_support(self):
        assert map_dtmf_to_intent("9") == "SUPPORT"

    def test_key_0_is_support(self):
        assert map_dtmf_to_intent("0") == "SUPPORT"

    def test_unknown_key_is_unclear(self):
        assert map_dtmf_to_intent("5") == "UNCLEAR"

    def test_all_dtmf_keys_mapped(self):
        for key, intent in DTMF_INTENT_MAP.items():
            assert map_dtmf_to_intent(key) == intent


class TestVoiceToIntent:
    """Test STT transcription to intent classification."""

    def test_pay_now_english(self):
        assert transcribe_voice_to_intent("I want to pay now", 0.9) == "PAY_NOW"

    def test_pay_now_hinglish(self):
        assert transcribe_voice_to_intent("abhi pay karunga", 0.9) == "PAY_NOW"

    def test_split_emi_english(self):
        assert transcribe_voice_to_intent("can I split into installments", 0.9) == "SPLIT_EMI"

    def test_split_emi_hinglish(self):
        assert transcribe_voice_to_intent("kist mein de dunga", 0.9) == "SPLIT_EMI"

    def test_pay_later_english(self):
        assert transcribe_voice_to_intent("can I pay later", 0.9) == "PAY_LATER"

    def test_pay_later_hinglish(self):
        assert transcribe_voice_to_intent("baad mein karunga", 0.9) == "PAY_LATER"

    def test_stop_english(self):
        assert transcribe_voice_to_intent("please stop calling", 0.9) == "STOP_REQUEST"

    def test_stop_hinglish(self):
        assert transcribe_voice_to_intent("band karo calls", 0.9) == "STOP_REQUEST"

    def test_support_english(self):
        assert transcribe_voice_to_intent("I want to talk to an agent", 0.9) == "SUPPORT"

    def test_support_hinglish(self):
        assert transcribe_voice_to_intent("agent se baat karo", 0.9) == "SUPPORT"

    def test_low_confidence_returns_unclear(self):
        assert transcribe_voice_to_intent("pay now", 0.3) == "UNCLEAR"

    def test_unrecognized_returns_unclear(self):
        assert transcribe_voice_to_intent("random gibberish", 0.9) == "UNCLEAR"

    def test_empty_returns_unclear(self):
        assert transcribe_voice_to_intent("", 0.9) == "UNCLEAR"


class TestVoiceGreetingTemplates:
    """Test that all voice greeting templates exist."""

    def test_english_greetings_complete(self):
        required = ["initial", "payment_link", "emi_offer", "promise_ack", "stop_ack", "fallback"]
        for key in required:
            assert key in VOICE_GREETINGS["en"], f"Missing English greeting: {key}"

    def test_hindi_greetings_complete(self):
        required = ["initial", "payment_link", "emi_offer", "promise_ack", "stop_ack", "fallback"]
        for key in required:
            assert key in VOICE_GREETINGS["hi"], f"Missing Hindi greeting: {key}"

    def test_greetings_have_hinglish_words(self):
        # Hindi greetings should contain recognizable Hindi words
        initial = VOICE_GREETINGS["hi"]["initial"]
        assert any(w in initial for w in ("Namaste", "dabayein", "karne", "hai"))
