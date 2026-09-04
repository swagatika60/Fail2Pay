"""AI Assist — optional, non-authoritative LLM enhancements for recovery copy.

The recovery loop is deterministic by design: templates, policy engine, state
machine, opt-out rules, reminder cadence and payment math never depend on a
model. AI Assist adds three *optional* layers on top of that deterministic
core, each one validated and each with a guaranteed deterministic fallback:

1. ``personalize_message`` — rephrases a deterministic reply so it reads like a
   natural, human-written message in the customer's own language. The payment
   URL and amounts must appear VERBATIM in the output or the original text is
   kept. Any timeout, provider error, or invalid output falls back to the
   deterministic text unchanged.

2. ``explain_failure_reason`` — turns a gateway failure code into a short,
   jargon-free customer explanation in the customer's language. Falls back to
   the deterministic ``failure_reason_label`` mapping.

3. ``suggest_intervention_rank`` — a NON-BINDING ranking of allowed recovery
   interventions. The intent-action mapper and policy engine remain the single
   authority: AI may *suggest* an order, but it can never pick an action,
   change an amount, trigger a send, or override a stop rule.

AI is only consulted when ``AI_API_KEY`` is configured or a provider is
injected (tests). Everything here is advisory — money, stops, escalation and
state transitions stay deterministic and audited.
"""

import json
import logging
import re
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


class TextAIProvider(Protocol):
    """Provider capable of free-form text completion (used for copy/advice)."""

    def complete(self, system_prompt: str, user_message: str, timeout: float = 10.0, max_tokens: int = 400) -> str:
        ...


def _resolve_provider(provider=None):
    """Return an AI provider when one is available, else None.

    An injected provider always wins (tests). Otherwise the global settings
    are consulted and a provider is built only when a real (non-empty string)
    API key is configured — mock objects / empty env never construct one.
    """
    if provider is not None:
        return provider
    settings = get_settings()
    key = getattr(settings, "ai_api_key", "")
    if not isinstance(key, str) or not key.strip():
        return None
    try:
        from app.services.intent_detector import OpenAIProvider, resolve_ai_provider_config

        _api_key, _model, _base_url = resolve_ai_provider_config(settings)
        return OpenAIProvider(api_key=_api_key, model=_model, base_url=_base_url)
    except Exception as e:  # noqa: BLE001 - never let provider init break the flow
        logger.error("Failed to initialize AI provider: %s", str(e))
        return None


# ---------------------------------------------------------------------------
# Output hygiene
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s)\]\}>]+")
_FORBIDDEN_TOKENS = (
    "threat",
    "threatening",
    "legal action",
    "sue",
    "lawsuit",
    "collection agency",
    "blacklist",
    "will block",
    "jail",
    "police",
    "harass",
)


def _extract_text(raw: str) -> str:
    """Strip code fences / JSON wrappers / quotes from a raw model response."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for key in ("message", "text", "response", "reply"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    except (json.JSONDecodeError, ValueError):
        pass
    if (
        len(raw) >= 2
        and raw[0] in ('"', "'")
        and raw[-1] == raw[0]
    ):
        return raw[1:-1].strip()
    return raw


def _safe_candidate(candidate: str, original: str, required_urls: list[str]) -> str:
    """Return the candidate only when it passes every safety validation."""
    candidate = candidate.strip()
    if not candidate:
        return ""
    if candidate == original:
        return ""
    if len(candidate) < 20:
        return ""
    if len(candidate) > len(original) + 600:
        return ""
    lower = candidate.lower()
    if any(tok in lower for tok in _FORBIDDEN_TOKENS):
        return ""
    # Every URL in the original must survive verbatim; no new URLs allowed.
    urls_in_candidate = set(_URL_RE.findall(candidate))
    if urls_in_candidate != set(required_urls):
        return ""
    return candidate


# ---------------------------------------------------------------------------
# 1. Reply personalization
# ---------------------------------------------------------------------------

PERSONALIZATION_PROMPT = """You are the customer-facing assistant for Fail2Pay, a payment-recovery product.

A deterministic policy engine drafted the message below for a customer whose payment failed. Rewrite it so it reads like a warm, natural, human-written message in the customer's own language — without changing the meaning, the options offered, or the tone (empathetic, reassuring, never pushy or threatening).

HARD RULES:
- Keep every payment link URL exactly as-is (do not add or remove any URL).
- Keep all amounts and invoice numbers exactly as-is.
- Keep the language the message is written in (English or Hinglish) — do not translate.
- Do not add new payment options, new fees, or new promises.
- Do not threaten, pressure, or mention legal action or collections.
- Keep it concise: no more than {max_chars} characters.
- Return ONLY the rewritten message text — no preamble, no quotes, no markdown."""


def personalize_message(
    *,
    text: str,
    language: str = "en",
    intent: str = "",
    customer_name: str | None = None,
    amount_paise: int | None = None,
    case_id: str | None = None,
    failure_reason: str | None = None,
    provider=None,
) -> dict:
    """Rephrase a deterministic recovery message for a natural human tone.

    Returns ``{"text": ..., "meta": {"personalized": bool, "source": ...}}``.
    ``text`` is the original unless the model output passed every validation
    check (URLs verbatim, sane length, no threatening copy) — and even then
    only when an AI provider is available.
    """
    meta: dict = {"personalized": False, "source": "deterministic"}
    if not text:
        return {"text": text, "meta": meta}

    provider = _resolve_provider(provider)
    if provider is None:
        return {"text": text, "meta": meta}

    required_urls = _URL_RE.findall(text)
    lang_label = "Hinglish (Romanized Hindi)" if language in ("hi", "hi-en") else "English"
    context_lines = [
        f"Customer language: {lang_label}",
        f"Customer name: {customer_name or 'unknown'}",
        f"Intent: {intent or 'unknown'}",
        f"Amount due (paise): {amount_paise if amount_paise is not None else 'unknown'}",
        f"Gateway failure reason: {failure_reason or 'unknown'}",
        f"Case: {case_id or 'unknown'}",
    ]
    user_message = (
        "\n".join(context_lines)
        + "\n\nDETERMINISTIC MESSAGE TO REWRITE:\n"
        + text
    )
    try:
        settings = get_settings()
        timeout = float(getattr(settings, "ai_timeout_seconds", 5))
        raw = provider.complete(
            PERSONALIZATION_PROMPT.format(max_chars=len(text) + 400),
            user_message,
            timeout=timeout,
            max_tokens=600,
        )
    except Exception as e:  # noqa: BLE001 - timeout/API errors must never break sending
        logger.warning("AI personalization failed (%s) — using deterministic text", type(e).__name__)
        meta["reason"] = f"{type(e).__name__}"
        return {"text": text, "meta": meta}

    candidate = _safe_candidate(_extract_text(raw), text, required_urls)
    if not candidate:
        logger.info("AI personalization output failed validation — using deterministic text")
        meta["reason"] = "validation_failed"
        return {"text": text, "meta": meta}

    meta["personalized"] = True
    meta["source"] = "ai"
    return {"text": candidate, "meta": meta}


# ---------------------------------------------------------------------------
# 2. Failure-reason explanation
# ---------------------------------------------------------------------------

EXPLAIN_REASON_PROMPT = """You are a friendly customer-support assistant for a payment company.

Explain the payment failure reason below to a customer in ONE short, friendly sentence in {language}. No jargon, no technical error codes, no blame. Just what happened and that it can be retried.

Rules:
- Maximum 160 characters.
- Do not include any URLs or links.
- Never threaten or pressure the customer.
- Return ONLY the sentence text."""


def explain_failure_reason(
    reason_code: str | None,
    language: str = "en",
    provider=None,
) -> dict:
    """Customer-friendly explanation of a gateway failure reason.

    Deterministic labels are the guaranteed fallback; the AI version is only
    used when a provider is available and the output passes validation.
    Returns ``{"text": ..., "meta": {"source": "ai"|"deterministic"}}``.
    """
    from app.services.agent_engine import failure_reason_label, failure_reason_label_hin

    reason_code = (reason_code or "").strip()
    hinglish = language in ("hi", "hi-en")
    deterministic = (
        failure_reason_label_hin(reason_code) if hinglish else failure_reason_label(reason_code)
    )
    meta: dict = {"source": "deterministic", "reason_code": reason_code}
    if not reason_code:
        return {"text": deterministic, "meta": meta}

    provider = _resolve_provider(provider)
    if provider is None:
        return {"text": deterministic, "meta": meta}

    lang_label = "Hinglish (Romanized Hindi)" if hinglish else "English"
    try:
        settings = get_settings()
        timeout = float(getattr(settings, "ai_timeout_seconds", 5))
        raw = provider.complete(
            EXPLAIN_REASON_PROMPT.format(language=lang_label),
            f"Failure reason code: {reason_code}",
            timeout=timeout,
            max_tokens=120,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("AI failure-reason explanation failed (%s) — using deterministic label", type(e).__name__)
        return {"text": deterministic, "meta": meta}

    candidate = _extract_text(raw)
    if not (10 <= len(candidate) <= 180) or any(tok in candidate.lower() for tok in _FORBIDDEN_TOKENS):
        return {"text": deterministic, "meta": meta}

    meta["source"] = "ai"
    return {"text": candidate, "meta": meta}


# ---------------------------------------------------------------------------
# 3. Non-binding intervention ranking
# ---------------------------------------------------------------------------

DEFAULT_INTERVENTION_ORDER = [
    "pay_now",
    "split_2",
    "payment_plan",
    "promise_to_pay",
    "payment_link",
]
_ALLOWED_INTERVENTIONS = set(DEFAULT_INTERVENTION_ORDER)

SUGGESTION_PROMPT = """Rank these recovery interventions from most suitable to least suitable for this customer's situation.

Allowed interventions (use ONLY these ids):
pay_now, split_2, payment_plan, promise_to_pay, payment_link

Context:
- Amount due: {amount}
- Risk level: {risk}
- Payment failure reason: {reason}
- Attempts so far: {attempts}

Return ONLY a JSON array of intervention ids, e.g. ["pay_now", "split_2", "payment_plan", "promise_to_pay", "payment_link"].
Do not explain. This ranking is advisory only — it never overrides policy."""


def suggest_intervention_rank(
    *,
    amount_paise: int | None = None,
    risk_level: str = "MEDIUM",
    failure_reason: str | None = None,
    attempt_count: int = 0,
    provider=None,
) -> dict:
    """Non-binding ranking of allowed recovery interventions.

    Returns ``{"ranked": [...ids], "meta": {"source": ..., "binding": False}}``.
    The deterministic default order applies unless a provider returns a valid
    ranking drawn ONLY from the allowed intervention set. ``binding`` is
    always False: nothing here can select or execute an action.
    """
    meta: dict = {"source": "deterministic", "binding": False}
    provider = _resolve_provider(provider)
    if provider is None:
        return {"ranked": list(DEFAULT_INTERVENTION_ORDER), "meta": meta}

    user_message = SUGGESTION_PROMPT.format(
        amount=f"₹{(amount_paise or 0) // 100}" if amount_paise else "unknown",
        risk=risk_level,
        reason=failure_reason or "unknown",
        attempts=attempt_count,
    )
    try:
        settings = get_settings()
        timeout = float(getattr(settings, "ai_timeout_seconds", 5))
        raw = provider.complete(
            "You rank interventions. You only ever output JSON arrays of allowed ids.",
            user_message,
            timeout=timeout,
            max_tokens=120,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("AI intervention suggestion failed (%s) — using deterministic order", type(e).__name__)
        return {"ranked": list(DEFAULT_INTERVENTION_ORDER), "meta": meta}

    ranked = _parse_ranking(raw)
    if len(ranked) < 2:
        # Partial/invalid AI output is ignored entirely — never trust a model
        # with a half-baked intervention list.
        return {"ranked": list(DEFAULT_INTERVENTION_ORDER), "meta": meta}

    meta["source"] = "ai"
    return {"ranked": ranked, "meta": meta}


def _parse_ranking(raw: str) -> list[str]:
    """Parse a JSON-array (or comma list) ranking, filtered to allowed ids."""
    raw = (raw or "").strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        data = [part.strip().strip('"').strip("'") for part in re.split(r"[,]", raw) if part.strip()]
    if not isinstance(data, list):
        return []

    seen: list[str] = []
    for item in data:
        if not isinstance(item, str):
            continue
        item_id = item.strip().lower()
        if item_id in _ALLOWED_INTERVENTIONS and item_id not in seen:
            seen.append(item_id)
    return seen