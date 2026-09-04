"""Contextual & Empathetic Recovery Agent Engine.

Generates realistic, human-like agent copy and a structured *action payload*
that the WhatsApp UI renders as quick-reply buttons, a rich payment link card
and language selectors.

Design rules (hard constraints):
  - All copy is deterministic and composed from merchant-safe templates, never
    generated ad hoc by an AI model.
  - The copy is personalised from real context: customer name, amount, invoice
    id, failure reason and the current recovery stage.
  - The structured ``agent_payload`` carried in an outbound message's
    ``extra_data`` only ever describes presentational actions (buttons, a
    payment URL, language options). It NEVER records money — only verified
    captured payments count as recovered revenue.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

# Gateway label shown on the payment card.
GATEWAY_LABEL = "Razorpay"

# Intents that are clarifications / handoffs / non-payment acknowledgments.
# These turns must NEVER carry the interactive payment-plan widgets (split
# options card / checkout card) so they are not re-spammed mid-dialogue.
_NO_PAYMENT_WIDGET_INTENTS = frozenset(
    {
        "SUPPORT",
        "QUESTION",
        "STOP_REQUEST",
        "LANGUAGE_SWITCHED",
        "NEGATIVE",
        "INVOICE_REQUEST",
        "ALREADY_PAID",
        # A genuinely ambiguous input is answered with a single clarifying
        # question and must never attach a payment/checkout widget.
        "UNCLEAR",
    }
)

# Human readable, lower-case reasons we understand specifically; anything else
# falls back to a generic line.
FAILURE_REASON_LABELS = {
    "bank_timeout": "a bank timeout",
    "insufficient_funds": "insufficient funds",
    "insufficient balance": "insufficient funds",
    "card_expired": "an expired card",
    "transaction_declined": "the bank declining the transaction",
    "authentication_failed": "a verification failure on your bank's side",
    "daily_limit_exceeded": "your bank's daily limit being exceeded",
    "payment_gateway_timeout": "a temporary payment gateway interruption",
    "network_error": "a temporary network interruption",
}


# ============================================================
# SENTIMENT ASSESSMENT (deterministic, keyword-based)
# ============================================================

# Cooperative signals: willingness to pay, gratitude, acknowledgment
_COOPERATIVE_WORDS = {
    "thank", "thanks", "shukriya", "dhanyavad", "sure", "zaroor",
    "bilkul", "haan", "yes", "ok", "theek", "kar dunga", "pay karunga",
    "done", "sorted", "samajh", "done", "jaldi", "abhi", "tonight",
    "aaj", "kal", "tomorrow", "promise", "pakka",
}

# Frustrated signals: anger, threats, urgency, profanity
_FRUSTRATED_WORDS = {
    "angry", "frustrated", "gussa", "pareshan", "bakwas", "worst",
    "terrible", "horrible", "ridiculous", "absurd", "unfair",
    "cheat", "fraud", "scam", "illegal", "lawyer", "court",
    "complaint", "report", "rbi", "cancel", "refund now",
    "pathetic", "useless", "nonsense", "stupid",
}

# Negative signals: refusal to pay, disinterest (but not angry)
_NEGATIVE_WORDS = {
    "no", "nahi", "nahin", "mat", "not paying", "won't pay",
    "can't pay", "cannot pay", "mujhse nahi hoga", "busy",
    "later", "baad mein", "kabhi", "not now",
}


def assess_sentiment(message_text: str) -> str:
    """Classify customer sentiment from message text.

    Returns one of: Cooperative, Neutral, Frustrated, Unengaged.
    Deterministic keyword-based — no AI involved.
    """
    if not message_text:
        return "Unengaged"

    msg_lower = message_text.lower().strip()

    frustrated_score = sum(1 for w in _FRUSTRATED_WORDS if w in msg_lower)
    cooperative_score = sum(1 for w in _COOPERATIVE_WORDS if w in msg_lower)
    negative_score = sum(1 for w in _NEGATIVE_WORDS if w in msg_lower)

    if frustrated_score > 0:
        return "Frustrated"
    if cooperative_score >= 2:
        return "Cooperative"
    if cooperative_score >= 1 and negative_score == 0:
        return "Cooperative"
    if negative_score > 0:
        return "Unengaged"
    if len(msg_lower) < 3:
        return "Neutral"
    return "Neutral"


@lru_cache(maxsize=512)
def format_amount(amount_paise: int) -> str:
    """Format paise as Indian rupee (e.g. 1999000 -> ₹19,999).

    Cached because the same amounts are formatted repeatedly across
    build_reply calls, split summaries and payment cards.
    """
    rupees = amount_paise // 100
    s = str(rupees)
    if len(s) <= 3:
        return f"\u20b9{s}"
    last_three = s[-3:]
    remaining = s[:-3]
    formatted = ""
    while len(remaining) > 2:
        formatted = "," + remaining[-2:] + formatted
        remaining = remaining[:-2]
    formatted = remaining + formatted + "," + last_three
    return f"\u20b9{formatted}"


def invoice_id_for_case(case_id: str) -> str:
    """A stable, readable invoice id shown in the UI (INV-<first 8>)."""
    return f"INV-{str(case_id)[:8].upper()}"


@lru_cache(maxsize=256)
def payment_url_for_case(case_id: str) -> str:
    """Clickable dynamic payment URL for a recovery case.

    Resolves against the configured payment portal host and always uses the
    frontend-routed ``/pay/{case_id}`` path (see PayNowPage). Never emits an
    unreachable/hardcoded domain — the host is environment-driven.

    Cached because the same URL is generated repeatedly per case.
    """
    return f"{get_pay_host()}/pay/{case_id}"


def get_pay_host() -> str:
    """Resolve the payment portal base host for the current environment.

    Precedence: ``PAYMENT_PORTAL_URL`` env > configured ``payment_portal_base_url``
    > configured ``payment_link_base_url`` (when it is an explicit HTTP URL) >
    localhost dev default. This keeps local development on a reachable host and
    production on the real portal domain.
    """
    try:
        from app.config import get_settings

        settings = get_settings()
        portal = (
            settings.payment_portal_base_url.strip()
            if settings.payment_portal_base_url
            else ""
        )
        if portal.startswith(("http://", "https://")):
            return portal.rstrip("/")
    except Exception:
        pass

    # Fall back to an explicit, non-placeholder payment link base URL.
    try:
        from app.config import get_settings

        configured = get_settings().payment_link_base_url.strip()
        if configured.startswith(("http://", "https://")) and "fail2pay.example.com" not in configured:
            return configured.rstrip("/")
    except Exception:
        pass

    return "http://localhost:5173"


def calculate_installments(total_amount: int, count: int = 2) -> list[int]:
    """Split ``total_amount`` (paise) into ``count`` installments.

    Uses half-up rounding for the base amount, then distributes the exact
    remainder (``total_amount % count``) across the *initial* tranches
    (one extra paisa per tranche). Guarantees the sum of the returned amounts
    equals the total — no rupees/paise lost or invented.

    Examples (paise):
      750000 (₹7,500) into 2 → [375000, 375000] (₹3,750 each)
      749900 (₹7,499) into 2 → [374950, 374950] (₹3,749.50 each)

    Mirrors the frontend ``calculateInstallments`` helper so both the API and
    the UI agree on the exact breakdown.
    """
    if count <= 0:
        raise ValueError("count must be a positive integer")
    base = total_amount // count
    remainder = total_amount % count
    # Spread the remainder over the FIRST `remainder` tranches.
    return [base + 1 if i < remainder else base for i in range(count)]


# Free-text "Part N (...) now in M installments" — the console's SplitActionCard
# dispatches exactly this message when a merchant picks a part of an existing
# plan and asks to re-split it (e.g. "I want to pay Part 1 (₹499) now in 2
# installments"). Parsed deterministically; no AI involved.
_NESTED_PART_RE = re.compile(r"part\s*(\d+)", re.IGNORECASE)
_NESTED_AMOUNT_RE = re.compile(r"\(\s*([^)]*?)\s*\)")
_NESTED_COUNT_RE = re.compile(r"now\s*in\s*(\d{1,2})\s*installments?", re.IGNORECASE)


def _parse_amount_label(label: str) -> int | None:
    """Extract an INR amount (in paise) from a display label like "₹1,23,456.50".

    Tolerates lakh/crore digit groupings, decimals and currency glyphs. Returns
    ``None`` when no amount or an impossible value is present.
    """
    m = re.search(r"\d[\d,]*(?:\.\d+)?", label or "")
    if not m:
        return None
    try:
        rupees = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    paise = int(round(rupees * 100))
    return paise if paise > 0 else None


def parse_nested_split(text: str) -> dict | None:
    """Parse a "Part N (₹X) now in M installments" sub-split request.

    Returns ``{"part": n, "amount_paise": paise, "count": m}`` when the message
    names one specific plan part, its amount, and a follow-up installment count;
    ``None`` otherwise (caller falls back to the standard EMI offer).
    """
    if not text:
        return None
    part_m = _NESTED_PART_RE.search(text)
    amount_m = _NESTED_AMOUNT_RE.search(text)
    count_m = _NESTED_COUNT_RE.search(text)
    if not (part_m and amount_m and count_m):
        return None
    amount_paise = _parse_amount_label(amount_m.group(1))
    count = int(count_m.group(1))
    if amount_paise is None or amount_paise <= 0 or count < 2 or count > 12:
        return None
    return {
        "part": int(part_m.group(1)),
        "amount_paise": amount_paise,
        "count": count,
    }


# A customer-named amount in free text ("₹2,000", "2000", "2000 rs").
_AMOUNT_IN_TEXT_RE = re.compile(
    r"(?:\u20b9|inr|rs\.?|rupees?)?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s*"
    r"(?:\u20b9|inr|rs\.?|rupees?)?",
    re.IGNORECASE,
)


def extract_partial_amount(text: str | None, remaining_paise: int | None) -> int | None:
    """Parse the amount a customer names in free text ("I can pay 2000 today").

    Returns paise only when the amount is a plausible *partial* payment
    (0 < amount < remaining). Equal-to-balance amounts are not "partial", and
    anything larger is treated as not-a-payment-amount. Deterministic — no AI.
    """
    if not text or remaining_paise is None or remaining_paise <= 0:
        return None
    m = _AMOUNT_IN_TEXT_RE.search(text)
    if not m:
        return None
    try:
        rupees = int(m.group(1).replace(",", ""))
        paise_digits = m.group(2) or ""
        paise = int((paise_digits + "00")[:2]) if paise_digits else 0
        amount_paise = rupees * 100 + paise
    except (ValueError, TypeError):
        return None
    if amount_paise <= 0 or amount_paise >= remaining_paise:
        return None
    return amount_paise


@lru_cache(maxsize=128)
def _split_summary_cached(total_amount: int, count: int) -> tuple:
    """Cached core computation for split_summary. Returns a tuple (hashable)."""
    amounts = calculate_installments(total_amount, count)

    def _due(i: int) -> str:
        if i == 0:
            return "aaj" if count <= 2 else "first tranche"
        if i == 1:
            return "15 din baad" if count <= 2 else "second tranche"
        return f"{i * 15} din baad"

    if count == 2:
        label = (
            f"2 installments of {format_amount(amounts[0])} today and "
            f"{format_amount(amounts[1])} after 15 days"
        )
        later_hint = "after 15 days"
    else:
        label = (
            f"{count} installments: "
            + ", ".join(f"{format_amount(a)} ({_due(i)})" for i, a in enumerate(amounts))
        )
        later_hint = f"{count} staged payments"

    return (count, tuple(amounts), tuple(format_amount(a) for a in amounts), label, later_hint, total_amount)


def split_summary(total_amount: int, count: int = 2) -> dict:
    """Human copy for an N-installment split offer (N >= 2).

    Internally cached to avoid recomputing the same (amount, count) pair.
    """
    cached = _split_summary_cached(total_amount, count)
    # cached = (count, amounts_tuple, amounts_formatted_tuple, label, later_hint, total)
    return {
        "count": cached[0],
        "amounts": list(cached[1]),
        "amounts_formatted": list(cached[2]),
        "label": cached[3],
        "later_hint": cached[4],
        "total": cached[5],
    }


def _first_name(customer_name: str | None) -> str:
    if not customer_name:
        return "Customer"
    return customer_name.strip().split()[0]


def _honorific(customer_name: str | None) -> str:
    """A light, respectful Hinglish honorific for personalisation."""
    return "ji" if customer_name else ""


def failure_reason_label(failure_reason: str | None) -> str:
    """Map a stored failure reason to human-friendly copy."""
    if not failure_reason:
        return "an unexpected issue"
    key = failure_reason.strip().lower()
    return FAILURE_REASON_LABELS.get(key, f"some difficulty with the payment")


def failure_reason_label_hin(failure_reason: str | None) -> str:
    """Romanized Hinglish failure phrase for Hinglish agent copy."""
    if not failure_reason:
        return "kuch technical dikkat"
    return {
        "bank_timeout": "bank ka timeout",
        "insufficient_funds": "bank account mein insufficient funds",
        "insufficient balance": "bank account mein insufficient funds",
        "card_expired": "card expiry ho chuki hai",
        "transaction_declined": "bank ne transaction decline kiya",
        "authentication_failed": "bank verification fail hui",
        "daily_limit_exceeded": "daily limit exceed ho gayi",
        "payment_gateway_timeout": "payment gateway mein temporary interruption",
        "network_error": "network mein temporary rukawat",
    }.get(failure_reason.strip().lower(), "payment mein kuch dikkat")


def build_initial_outbound(
    *,
    case_id: str,
    customer_name: str | None,
    amount_paise: int,
    failure_reason: str | None = None,
    invoice_id: str | None = None,
    language: str = "en",
) -> dict:
    """Build the trigger (first touch) agent message + action payload.

    Tailors the first-touch copy based on the payment failure reason:
    - **Daily limit exceeded**: Acknowledge bank UPI/card limit, suggest
      Net Banking or Credit Card as alternatives, offer split and retry
      tomorrow after midnight.
    - **Insufficient funds**: Low-urgency, discreet tone. Ask for a
      preferred retry date or offer flexible payment plans.
    - **Bank/Gateway timeout**: Confirm whether the amount was deducted,
      reassure about duplicate charges, provide an instant retry link.
    - **Other failures**: Generic empathetic copy with the root cause.

    Returns an ``agent_payload`` dict the UI renders as a WhatsApp message
    with a rich payment card and quick replies.
    """
    name = _first_name(customer_name)
    ji = _honorific(customer_name)
    amount = format_amount(amount_paise)
    inv = invoice_id or invoice_id_for_case(case_id)
    reason = failure_reason_label(failure_reason)
    reason_hin = failure_reason_label_hin(failure_reason)
    url = payment_url_for_case(case_id)
    hinglish = language in ("hi", "hi-en")
    fr = (failure_reason or "").strip().lower()

    # --- Failure-specific body copy (English) ---
    if fr == "daily_limit_exceeded":
        en_body = (
            f"We noticed your payment of {amount} for Invoice #{inv} failed "
            f"due to your bank's daily UPI/card transaction limit. Don't worry "
            f"\u2014 your order is temporarily held for you.\n\n"
            f"You can try one of these alternatives:\n"
            f"\u2022 Pay via Net Banking or Credit Card instead\n"
            f"\u2022 Split into 2 installments\n"
            f"\u2022 Retry automatically after midnight (00:00)\n\n"
            f"Tap below to complete your payment:\n\U0001f449 {url}"
        )
        hi_body = (
            f"Namaste {name}{ji}! Aapka Invoice #{inv} ka {amount} ka bhugtan "
            f"aapke bank ki daily UPI/card limit exceed hone ki wajah se fail "
            f"hua. Chinta mat karein \u2014 aapka order hold par hai.\n\n"
            f"Aap yeh alternatives try kar sakte hain:\n"
            f"\u2022 Net Banking ya Credit Card se pay karein\n"
            f"\u2022 2 kishton mein split karein\n"
            f"\u2022 Raat 12 baje ke baad retry karein\n\n"
            f"Neeche se apna option chunein:\n\U0001f449 {url}"
        )
    elif fr in ("insufficient_funds", "insufficient balance"):
        en_body = (
            f"Hi {name}{ji}, your payment of {amount} for Invoice #{inv} "
            f"couldn't go through due to insufficient funds. This happens "
            f"sometimes \u2014 no worries at all.\n\n"
            f"Would you like to:\n"
            f"\u2022 Tell us a preferred date to retry\n"
            f"\u2022 Split into flexible installments\n"
            f"\u2022 Pay now when you're ready\n\n"
            f"Your payment link is active whenever you're ready:\n\U0001f449 {url}"
        )
        hi_body = (
            f"Namaste {name}{ji}! Aapka Invoice #{inv} ka {amount} ka bhugtan "
            f"insufficient funds ki wajah se ruka. Koi baat nahi \u2014 yeh "
            f"kabhi kabhi hota hai.\n\n"
            f"Aap yeh kar sakte hain:\n"
            f"\u2022 Retry ki tarikh batayein\n"
            f"\u2022 Installments mein pay karein\n"
            f"\u2022 Jab ready ho, abhi pay karein\n\n"
            f"Aapka payment link active hai:\n\U0001f449 {url}"
        )
    elif fr in ("bank_timeout", "payment_gateway_timeout", "network_error"):
        en_body = (
            f"Hi {name}{ji}, your payment of {amount} for Invoice #{inv} was "
            f"interrupted due to a temporary {reason}. Please rest assured \u2014 "
            f"if any amount was deducted, it will be automatically reversed "
            f"within 3-5 business days. No duplicate charges will apply.\n\n"
            f"You can retry instantly using the link below:\n"
            f"\U0001f449 {url}\n\n"
            f"Need help? We're here for you."
        )
        hi_body = (
            f"Namaste {name}{ji}! Aapka Invoice #{inv} ka {amount} ka bhugtan "
            f"temporary {reason_hin} ki wajah se ruk gaya. Chinta mat karein \u2014 "
            f"agar koi amount kat gaya hai, wo 3-5 business days mein reverse "
            f"ho jayega. Koi double charge nahi hoga.\n\n"
            f"Instantly retry karein link se:\n\U0001f449 {url}\n\n"
            f"Madad chahiye? Hum yahan hain."
        )
    else:
        # Generic fallback for other failure reasons.
        en_body = (
            f"We noticed your payment of {amount} for Invoice #{inv} failed "
            f"due to {reason}. Don't worry \u2014 your order is temporarily "
            f"held for you.\n\n"
            f"You can complete it securely using the link below:\n"
            f"\U0001f449 {url}\n\n"
            f"Need help? Reply with your preferred option below."
        )
        hi_body = (
            f"Namaste {name}{ji}! Aapka Invoice #{inv} ka bhugtan "
            f"{amount} {reason_hin} ki wajah se fail hua. Chinta mat karein \u2014 "
            f"aapka order aapke liye temporarily hold hai.\n\n"
            f"Aap ise securely complete kar sakte hain link se:\n"
            f"\U0001f449 {url}\n\n"
            f"Madad chahiye? Neeche se apna preferred option chunein."
        )

    text = hi_body if hinglish else en_body

    if hinglish:
        pay_now = f"Abhi Pay Karein {amount}"
        split2 = "2 Kishton mein baantein"
        split4 = "4 Kishton mein baantein"
        support = "Support Se Baat Karein"
    else:
        pay_now = f"Pay Now {amount}"
        split2 = "Split in 2 EMIs"
        split4 = "Split in 4 EMIs"
        support = "Talk to Support"

    return {
        "payload_type": "whatsapp",
        "text": text,
        "language_options": [
            {"code": "en", "label": "English"},
            {"code": "hi", "label": "\u0939\u093f\u0902\u0926\u0940 / Hinglish"},
        ],
        "quick_replies": [
            {"id": "pay_now", "label": pay_now},
            {"id": "split_2", "label": split2},
            {"id": "split_4", "label": split4},
            {"id": "support", "label": support},
        ],
        "split_options": [
            {
                "id": "split_2",
                "count": 2,
                "label": split2,
                "amounts_formatted": split_summary(amount_paise, 2)["amounts_formatted"],
            },
            {
                "id": "split_4",
                "count": 4,
                "label": split4,
                "amounts_formatted": split_summary(amount_paise, 4)["amounts_formatted"],
            },
        ],
        "payment_card": {
            "amount": amount_paise,
            "amount_formatted": amount,
            "invoice_id": inv,
            "gateway": GATEWAY_LABEL,
            "url": url,
            "label": f"Pay {amount} securely",
        },
    }


def _resolve_emi_amount(split_details: dict | None) -> int | None:
    """Return the exact installment due today (paise) from a split plan payload.

    ``split_details`` is the rich payload produced by ``split_plan_payload`` /
    ``split_summary`` and carries an ``amounts`` list in *paise*. The first
    tranche is due today, so that is the amount a payment card / CTA should
    show (never the full balance, never ₹0).

    Returns None when there is no usable computed split (so callers fall back
    to the full remaining balance).
    """
    if not split_details:
        return None
    amounts = split_details.get("amounts")
    if isinstance(amounts, (list, tuple)) and amounts:
        first = amounts[0]
        if isinstance(first, int) and first > 0:
            return first
    return None


# ============================================================
# REPLY TEMPLATE REGISTRY
# ============================================================
# Maps (intent, language) → text template. Placeholders:
#   {name}  - first name
#   {ji}    - honorific ("ji" or "")
#   {amount} - formatted total amount
#   {due}   - formatted amount due today (installment or full)
#   {inv}   - invoice ID
#   {url}   - payment link
#   {ack}   - context-aware acknowledgment (filled at call time)
#   {repeat} - repeat-context prefix (filled at call time)
#   {promise_label} - promise date label
#   {escalate_note} - escalation note
#
# This registry eliminates the massive hinglish/english if/else duplication
# in build_reply. Each intent has exactly one entry per language.
# ============================================================

@dataclass(frozen=True)
class _ReplyTemplate:
    text: str
    quick_reply_ids: tuple[str, ...] = ("pay_now", "split_2", "support")
    include_payment_card: bool = True
    include_split_options: bool = True
    extra_quick_replies: tuple[dict, ...] = ()


def _p(rid: str, label: str) -> dict:
    """Shorthand to build a quick-reply dict."""
    return {"id": rid, "label": label}


# English quick-reply labels
_EN = {
    "pay_now": "Pay Now {due}",
    "pay_full": "Pay Full {amount}",
    "split_2": "Split in 2 EMIs",
    "split_4": "Split in 4 EMIs",
    "activate_plan": "Activate EMI Plan",
    "support": "Talk to Support",
    "pay_later": "Pay Later",
    "lang_hi": "\u0939\u093f\u0902\u0926\u0940 / Hinglish",
    "lang_en": "English",
}

# Hinglish quick-reply labels
_HI = {
    "pay_now": "Abhi Pay Karein {due}",
    "pay_full": "Poora {amount} Abhi Pay Karein",
    "split_2": "2 Kishton mein baantein",
    "split_4": "4 Kishton mein baantein",
    "activate_plan": "EMI Plan Activate Karein",
    "support": "Support Se Baat Karein",
    "pay_later": "Baad Mein Pay Karein",
    "lang_hi": "\u0939\u093f\u0902\u0926\u0940 / Hinglish",
    "lang_en": "English",
}

# Promise date option labels
_EN_PROMISE = ("Pay Tomorrow \u00b7 11 AM", "Need 3 Days", "Choose a Date")
_HI_PROMISE = ("Kal 11 Baje", "3 Din Mein", "Date Chunein")


def _qr(labels: dict, *ids: str, due: str = "", amount: str = "") -> list[dict]:
    """Build quick-reply list from an intent's id tuple + label map."""
    fmt = {"due": due, "amount": amount}
    return [_p(rid, labels[rid].format(**fmt)) for rid in ids]


# ── English templates ──────────────────────────────────────────
_EN_TEMPLATES: dict[str, _ReplyTemplate] = {
    "PAYMENT_PLAN_REQUEST": _ReplyTemplate(
        text="Split: {split_label}. Activate: {url}",
        quick_reply_ids=("activate_plan", "pay_now", "support"),
    ),
    "PAYMENT_PLAN_REQUEST_ACTIVE": _ReplyTemplate(
        text="Split: {split_label}. First installment {due} due today: {url}",
        quick_reply_ids=("pay_now", "pay_full", "support"),
    ),
    "PROMISE_TO_PAY": _ReplyTemplate(
        text=(
            "{ack}, {name}{ji}! Promise locked in for {promise_label}. "
            "I've paused reminders{monitor_note}"
            "\n\nYour payment link stays active:\n{url}"
        ),
        quick_reply_ids=("pay_now", "split_2", "split_4", "support"),
    ),
    "PROMISE_TO_PAY_ASK": _ReplyTemplate(
        text=(
            "{ack}, {name}{ji}! I've paused reminders and can hold this for you.{monitor_note}"
            "\n\nYour payment link for {due} stays active:\n{url}\n\n"
            "When would you like to pay? Pick a day below \u2014 the earliest option "
            "is tomorrow at 11:00 AM."
        ),
        quick_reply_ids=(),  # filled dynamically
    ),
    "QUESTION": _ReplyTemplate(
        text=(
            "{ack}, {name}{ji}. {repeat}I've paused "
            "automated follow-ups and connected our billing desk. Someone "
            "will reach out here or by email within a few hours \u2014 no need "
            "to repeat yourself.{escalate}"
        ),
        quick_reply_ids=("support",),
        include_payment_card=False,
        include_split_options=False,
    ),
    "STOP_REQUEST": _ReplyTemplate(
        text=(
            "Understood, {name}{ji}. We have stopped all reminders for "
            "this account. If you need help later, feel free to reach out."
        ),
        quick_reply_ids=(),
        include_payment_card=False,
        include_split_options=False,
    ),
    "PAYMENT_LINK_REQUEST": _ReplyTemplate(
        text=(
            "{link_line}\n\n"
            "Tap it anytime to complete your payment of {due} for Invoice #{inv}."
        ),
        quick_reply_ids=("pay_now", "split_2", "split_4", "support"),
    ),
    "UNCLEAR": _ReplyTemplate(
        text=(
            "I'm sorry {name}{ji}, I didn't quite catch that. Would you "
            "like to pay the full balance today, split it into "
            "installments, or talk to support?"
        ),
        quick_reply_ids=("pay_now", "split_2", "split_4", "support"),
    ),
    "LANGUAGE_SWITCHED": _ReplyTemplate(
        text=(
            "Of course, {name}{ji}! I'll switch to English. Would you "
            "like to pay now, split this into installments, or talk to "
            "our support team?"
        ),
        quick_reply_ids=("pay_now", "split_2", "split_4", "support"),
    ),
    "SUPPORT": _ReplyTemplate(
        text=(
            "{ack}, {name}{ji}! I'm looping in our human support team "
            "right now \u2014 someone will join this chat within 2-3 minutes "
            "or reply here directly."
        ),
        quick_reply_ids=(),
        include_payment_card=False,
        include_split_options=False,
    ),
    "NEGATIVE": _ReplyTemplate(
        text=(
            "{ack}, {name}{ji}. We understand \u2014 no pressure at all. "
            "I'll hold off on any further reminders for now. Whenever "
            "you're ready, just message us and we'll work out an "
            "arrangement that suits you."
        ),
        quick_reply_ids=("support",),
        include_payment_card=False,
        include_split_options=False,
    ),
    "INVOICE_REQUEST": _ReplyTemplate(
        text=(
            "{ack}, {name}{ji}! Your invoice #{inv} is for {due}. "
            "We've sent a copy to your email. For any questions, feel "
            "free to reach our support team."
        ),
        quick_reply_ids=("support",),
        include_payment_card=False,
        include_split_options=False,
    ),
    "DEFAULT": _ReplyTemplate(
        text=(
            "Thanks for reaching out, {name}{ji}! For invoice #{inv} you "
            "can complete your payment of {due} here: {url}"
        ),
        quick_reply_ids=("pay_now", "split_2", "split_4", "support"),
    ),
    # --- Recovery Specialist intents ---
    "PAY_NOW": _ReplyTemplate(
        text=(
            "Here is your direct link to settle the balance of {due}: "
            "{url}"
        ),
        quick_reply_ids=("pay_now", "split_2", "support"),
    ),
    "SPLIT_EMI": _ReplyTemplate(
        text="Split: {split_label}. Activate: {url}",
        quick_reply_ids=("activate_plan", "pay_now", "support"),
    ),
    "SPLIT_EMI_ACTIVE": _ReplyTemplate(
        text="Split: {split_label}. First installment {due} due today: {url}",
        quick_reply_ids=("pay_now", "pay_full", "support"),
    ),
    "PAY_LATER": _ReplyTemplate(
        text=(
            "{ack}, {name}{ji}! I've paused reminders and can hold this "
            "for you. {monitor_note}\n\nYour payment link for {due} stays "
            "active:\n{url}\n\n"
            "When would you like to pay? Pick a day below \u2014 the earliest "
            "option is tomorrow at 11:00 AM."
        ),
        quick_reply_ids=(),  # filled dynamically
    ),
    "GREETING": _ReplyTemplate(
        text=(
            "Hello {name}{ji}! I'm here to help with your pending invoice "
            "of {due}. Would you like to complete the payment or split it "
            "into EMIs?"
        ),
        quick_reply_ids=("pay_now", "split_2", "split_4", "support"),
    ),
    "FALLBACK": _ReplyTemplate(
        text=(
            "I'm sorry {name}{ji}, I didn't quite catch that. Would you "
            "like to pay the full balance today, split it into "
            "installments, or talk to support?"
        ),
        quick_reply_ids=("pay_now", "split_2", "split_4", "support"),
    ),
}

# ── Hinglish templates ────────────────────────────────────────
_HI_TEMPLATES: dict[str, _ReplyTemplate] = {
    "PAYMENT_PLAN_REQUEST": _ReplyTemplate(
        text="EMI options hain {name}{ji}: 2 ya 4 kisht. Activate: {url}",
        quick_reply_ids=("activate_plan", "pay_now", "support"),
    ),
    "PAYMENT_PLAN_REQUEST_ACTIVE": _ReplyTemplate(
        text="Samajh gaya {name}{ji}, split done: {split_breakdown}. Pehli kist {due} aaj: {url}",
        quick_reply_ids=("pay_now", "pay_full", "support"),
    ),
    "PROMISE_TO_PAY": _ReplyTemplate(
        text=(
            "Ho gaya {name}{ji}! {promise_label} ke liye promise note kar liya. "
            "Reminders pause hain{monitor_note}" +
            "\n\nAapka payment link active rahega:\n{url}"
        ),
        quick_reply_ids=("pay_now", "split_2", "support"),
    ),
    "PROMISE_TO_PAY_ASK": _ReplyTemplate(
        text=(
            "{ack} {name}{ji}! Reminder pause kar ke invoice hold kar sakte hain.{monitor_note}"
            "\n\nAap kis din pay karna chahenge? Neeche se chunein \u2014 kal "
            "(11:00 baje), 3 din mein, koi aur date, ya support se baat karein.\n{url}"
        ),
        quick_reply_ids=(),
    ),
    "QUESTION": _ReplyTemplate(
        text=(
            "{ack} {name}{ji}.{repeat}Main automated follow-up pause "
            "kar deta hoon aur hamari billing team aapse connect hogi. "
            "Revised breakdown email se jaayega.{escalate}"
        ),
        quick_reply_ids=("support",),
        include_payment_card=False,
        include_split_options=False,
    ),
    "STOP_REQUEST": _ReplyTemplate(
        text=(
            "Samajh gaya {name}{ji}. Humne is account ke liye saari "
            "reminders band kar di hain. Agar baad mein madad chahiye toh "
            "humein message karein."
        ),
        quick_reply_ids=(),
        include_payment_card=False,
        include_split_options=False,
    ),
    "PAYMENT_LINK_REQUEST": _ReplyTemplate(
        text=(
            "{link_line}\n\n{due} ka bhugtan kabhi bhi karein, Invoice #{inv} ke liye."
        ),
        quick_reply_ids=("pay_now", "split_2", "support"),
    ),
    "UNCLEAR": _ReplyTemplate(
        text=(
            "Maaf kijiye {name}{ji}, main theek se samajh nahi paya. "
            "Kya aap aaj poora bhugtan karna chahenge, kishton mein, "
            "ya support se baat karein?"
        ),
        quick_reply_ids=("pay_now", "split_2", "support"),
    ),
    "LANGUAGE_SWITCHED": _ReplyTemplate(
        text=(
            "Bilkul {name}{ji}! Ab main aapse Hinglish mein baat karunga. "
            "Bataiye, invoice #{inv} ka bhugtan aaj karna chahenge, "
            "installments mein, ya support se baat karein?"
        ),
        quick_reply_ids=("pay_now", "split_2", "split_4", "support"),
    ),
    "SUPPORT": _ReplyTemplate(
        text=(
            "{ack} {name}{ji}! Main abhi hamari human support team ko "
            "connect kar raha hoon \u2014 koi 2-3 minute mein issi chat mein "
            "aayega ya yahin reply karega."
        ),
        quick_reply_ids=(),
        include_payment_card=False,
        include_split_options=False,
    ),
    "NEGATIVE": _ReplyTemplate(
        text=(
            "{ack} {name}{ji}. Hum samajh gaye \u2014 koi tension nahi. "
            "Main abhi koi aur reminder nahi bhejunga. Jab aap ready hon, "
            "humein message karein aur hum aapke hisaab se arrangement karenge."
        ),
        quick_reply_ids=("support",),
        include_payment_card=False,
        include_split_options=False,
    ),
    "INVOICE_REQUEST": _ReplyTemplate(
        text=(
            "{ack} {name}{ji}! Invoice #{inv} {due} ka hai. "
            "Humne isse aapke email par bhej diya hai. Kisi bhi sawaal "
            "ke liye support se baat kar sakte hain."
        ),
        quick_reply_ids=("support",),
        include_payment_card=False,
        include_split_options=False,
    ),
    "DEFAULT": _ReplyTemplate(
        text=(
            "Shukriya {name}{ji}! Invoice #{inv} ke liye aap aaj "
            "{due} ka bhugtan yahan se complete kar sakte hain: {url}"
        ),
        quick_reply_ids=("pay_now", "split_2", "support"),
    ),
    # --- Recovery Specialist intents ---
    "PAY_NOW": _ReplyTemplate(
        text=(
            "Yeh raha aapka direct payment link {due} ke liye: {url}"
        ),
        quick_reply_ids=("pay_now", "split_2", "support"),
    ),
    "SPLIT_EMI": _ReplyTemplate(
        text="Split {name}{ji}: {split_label}. Activate: {url}",
        quick_reply_ids=("activate_plan", "pay_now", "support"),
    ),
    "SPLIT_EMI_ACTIVE": _ReplyTemplate(
        text="Split {name}{ji}: {split_label}. Pehli kist {due} aaj: {url}",
        quick_reply_ids=("pay_now", "pay_full", "support"),
    ),
    "PAY_LATER": _ReplyTemplate(
        text=(
            "{ack} {name}{ji}! Reminder pause kar ke invoice hold kar sakte "
            "hain. {monitor_note}\n\nAap kis din pay karna chahenge? Neeche se "
            "chunein \u2014 kal (11:00 baje), 3 din mein, koi aur date, ya "
            "support se baat karein.\n{url}"
        ),
        quick_reply_ids=(),
    ),
    "GREETING": _ReplyTemplate(
        text=(
            "Namaste {name}{ji}! Aapki pending invoice {due} ke liye "
            "hai. Kya aap aaj poora bhugtan karna chahenge ya kishton "
            "mein baantein?"
        ),
        quick_reply_ids=("pay_now", "split_2", "split_4", "support"),
    ),
    "FALLBACK": _ReplyTemplate(
        text=(
            "Maaf kijiye {name}{ji}, main theek se samajh nahi paya. "
            "Kya aap aaj poora bhugtan karna chahenge, kishton mein, "
            "ya support se baat karein?"
        ),
        quick_reply_ids=("pay_now", "split_2", "support"),
    ),
}


def _select_template(intent: str, hinglish: bool, split_details, emi_active, promise_at) -> _ReplyTemplate:
    """Resolve the correct template for an intent, handling dynamic variants."""
    lang = "hi" if hinglish else "en"
    pool = _HI_TEMPLATES if hinglish else _EN_TEMPLATES

    # Dynamic variants based on runtime state
    if intent in ("PAYMENT_PLAN_REQUEST", "SPLIT_EMI") and split_details and emi_active:
        return pool["SPLIT_EMI_ACTIVE"] if intent == "SPLIT_EMI" else pool["PAYMENT_PLAN_REQUEST_ACTIVE"]
    if intent in ("PROMISE_TO_PAY", "PAY_LATER") and not promise_at:
        return pool["PAY_LATER"] if intent == "PAY_LATER" else pool["PROMISE_TO_PAY_ASK"]

    # PAYMENT_RETRY_REQUEST uses the same template as PAYMENT_LINK_REQUEST
    resolved_intent = "PAYMENT_LINK_REQUEST" if intent == "PAYMENT_RETRY_REQUEST" else intent
    return pool.get(resolved_intent, pool["DEFAULT"])


def build_reply(
    *,
    case_id: str,
    customer_name: str | None,
    amount_paise: int,
    intent: str,
    invoice_id: str | None = None,
    language: str = "en",
    split_details: dict | None = None,
    split_count: int | None = None,
    escalate_note: str | None = None,
    history: list[str] | None = None,
    pay_today: int | None = None,
    recovered: bool = False,
    failure_reason: str | None = None,
    attempt_count: int = 0,
    customer_message: str | None = None,
    promise_at: datetime | None = None,
    monitor_mode: bool = False,
    plan_modification: dict | None = None,
) -> dict:
    """Build the contextual agent reply + action payload for a customer reply.

    ``intent`` is one of the resolved intent keys used by the demo handlers:
    PROMISE_TO_PAY, PAYMENT_PLAN_REQUEST, QUESTION (wrong bill), STOP_REQUEST,
    PAYMENT_LINK_REQUEST, UNCLEAR, SUPPORT.

    ``language`` of "hi"/"hi-en" renders Romanized Hinglish copy (with a
    Hindi-transliterated payment link line) instead of the English template.

    ``history`` supplies the recent inbound customer messages so the engine can
    acknowledge a repeated query dynamically (instead of echoing the same
    generic line every turn) and never repeat an identical apology/EMI script
    back-to-back.

    ``amount_paise`` is the *live remaining balance* (never the original) so
    copy, split summaries and the payment card always reflect what is actually
    due. ``pay_today`` overrides the amount shown on the payment card / "Pay
    Now" CTA with the exact installment due today once an EMI plan is
    confirmed (this fixes the previously mismatched "full invoice vs ₹0" card).
    ``recovered`` switches the reply to a payment-received acknowledgement with
    no payment card (the old behaviour emitted a ₹0 card after full recovery).

    ``promise_at`` is set once a promise date has been confirmed so the
    PROMISE_TO_PAY reply acknowledges the exact committed date (deterministic,
    11:00 AM IST normalized). ``monitor_mode`` signals the attempt limit has
    been reached: automated reminders stay paused and the reply never claims a
    new automated reminder was queued.
    """
    name = _first_name(customer_name)
    ji = _honorific(customer_name)
    amount = format_amount(amount_paise)
    inv = invoice_id or invoice_id_for_case(case_id)
    url = payment_url_for_case(case_id)
    hinglish = language in ("hi", "hi-en")
    history = history or []

    # Never emit a ₹0 / stale payment card. An amount of 0 (or below) means the
    # balance is already settled, so the reply degrades to a payment-received
    # acknowledgement with NO payment card — regardless of what the caller asked.
    if amount_paise is not None and amount_paise <= 0:
        recovered = True

    # Exact amount due now: today's installment when an EMI plan is active,
    # otherwise the live remaining balance.
    due_amount_paise = pay_today if pay_today is not None else amount_paise
    due_amount = format_amount(due_amount_paise)
    emi_active = pay_today is not None and due_amount_paise < amount_paise

    # Count how many times the same intent has come up for dedup/variation.
    intent_repeats = history.count(intent) if history else 0

    def _split_replies(counts=(2, 4)):
        return [
            {"id": f"split_{c}", "label": _split_label(c)}
            for c in counts
        ]

    def _split_options():
        return [
            {
                "id": f"split_{c}",
                "count": c,
                "label": _split_label(c),
                "amounts_formatted": split_summary(amount_paise, c)["amounts_formatted"],
            }
            for c in (2, 4)
        ]

    def _link_line():
        return (
            f"Yeh raha aapka secure payment link: {url}"
            if hinglish
            else f"Here is your secure payment link: {url}"
        )

    def _pay_now_label():
        return f"Abhi Pay Karein {due_amount}" if hinglish else f"Pay Now {due_amount}"

    def _pay_full_label():
        return f"Poora {amount} Abhi Pay Karein" if hinglish else f"Pay Full {amount}"

    def _talk_support_label():
        return "Support Se Baat Karein" if hinglish else "Talk to Support"

    def _promise_date_label(when) -> str:
        """Human label for a confirmed promise datetime (11:00 AM IST centered).

        "tomorrow at 11:00 AM" for the very next day (keeps the verified demo
        copy/tests stable), otherwise a localized "<day> <month> at HH:MM AM/PM".
        """
        from datetime import datetime as _dt, timezone as _tz
        from zoneinfo import ZoneInfo

        if not when:
            return ""
        local = when.astimezone(ZoneInfo("Asia/Kolkata")) if when.tzinfo else when
        today = _dt.now(_tz.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
        if local.date() == today and local.hour >= 11:
            day_ref = "tomorrow"
        else:
            day_ref = local.strftime("%d %b")
        if hinglish:
            return (
                "kal 11:00 baje"
                if day_ref == "tomorrow"
                else f"{local.strftime('%d %b')} ko {local.strftime('%I:%M')} baje"
            )
        return (
            "tomorrow at 11:00 AM"
            if day_ref == "tomorrow"
            else f"{local.strftime('%d %b')} at {local.strftime('%I:%M %p')}"
        )

    def _promise_option_replies():
        return [
            {"id": "promise_tomorrow", "label": "Pay Tomorrow · 11 AM" if not hinglish else "Kal 11 Baje"},
            {"id": "promise_3days", "label": "Need 3 Days" if not hinglish else "3 Din Mein"},
            {"id": "promise_custom", "label": "Choose a Date" if not hinglish else "Date Chunein"},
            {"id": "support", "label": _talk_support_label()},
        ]

    def _activate_plan_label():
        return "EMI Plan Activate Karein" if hinglish else "Activate EMI Plan"

    def _split_label(count):
        return f"{count} Kishton mein baantein" if hinglish else f"Split in {count} EMIs"

    def _split_breakdown(details: dict | None) -> str:
        """Localized, Romanized Hinglish installment breakdown for a split plan.

        Uses the formatted amounts from the computed split (never the English
        ``label``) so Hinglish copy embeds a clean localized breakdown instead
        of an English sentence.
        """
        if not details:
            return ""
        fmt = details.get("amounts_formatted") or []
        count = details.get("count") or len(fmt)
        if not fmt:
            return ""
        if count == 2 and len(fmt) >= 2:
            return f"{fmt[0]} aaj aur {fmt[1]} agle 15 dinon mein"
        parts = [f"{fmt[0]} aaj"]
        for i in range(1, len(fmt)):
            if i == 1:
                parts.append(f"{fmt[i]} 15 din baad")
            else:
                parts.append(f"{fmt[i]} {i * 15} din baad")
        return ", ".join(parts)


    # --- Payment received affiliation (full recovery) ---
    # A recovered turn must thank the customer and NOT emit a payment card
    # (the old flow produced a ₹0 card once remaining_amount hit zero).
    if recovered:
        if amount_paise is not None and amount_paise > 0:
            # Verified payment received for a known amount.
            if hinglish:
                text = (
                    f"Dhanyavad {name}{ji}! Aapka {amount} ka bhugtan kamyabi "
                    f"se ho gaya hai. Invoice #{inv} ab fully settled hai. "
                    f"Aur madad chahiye toh yahin batayein."
                )
            else:
                text = (
                    f"Thank you, {name}{ji}! Your payment of {amount} for Invoice "
                    f"#{inv} has been received and your balance is now fully "
                    f"settled. If you need anything else, just reply here."
                )
        else:
            # Balance already settled (guarded ≤0 path) — never print a ₹0 amount.
            if hinglish:
                text = (
                    f"Dhanyavad {name}{ji}! Aapka balance ab fully settled hai "
                    f"aur invoice ka bhugtan ho chuka hai. Aur madad chahiye toh "
                    f"yahin batayein."
                )
            else:
                text = (
                    f"Thank you, {name}{ji}! Your balance is now fully settled "
                    f"and the invoice is closed. If you need anything else, "
                    f"just reply here."
                )
        return {
            "payload_type": "whatsapp",
            "text": text,
            "language_options": [
                {"code": "en", "label": "English"},
                {"code": "hi", "label": "\u0939\u093f\u0902\u0926\u0940 / Hinglish"},
            ],
            "quick_replies": [],
            # Settled/payment-received acknowledgment: never re-offer the split
            # widget here.
            "split_options": [],
            "payment_card": None,
        }


    # Context-aware acknowledgment that references prior commitments.
    # When the same intent has been expressed before, we acknowledge
    # the prior context instead of repeating a canned template.
    def _context_ack(intent: str) -> str:
        """Return an intent-appropriate acknowledgment that varies by repeat count."""
        if hinglish:
            # Hinglish: keep natural Hindi greeting words.
            if intent in ("PROMISE_TO_PAY", "PAY_LATER"):
                return "Bilkul"
            if intent in ("PAYMENT_PLAN_REQUEST", "SPLIT_EMI"):
                return "Bilkul"
            if intent == "QUESTION":
                return "Mujhe afsos hai" if intent_repeats == 0 else "Samajh gaya"
            if intent == "SUPPORT":
                return "Bilkul"
            if intent in ("PAYMENT_LINK_REQUEST", "PAYMENT_RETRY_REQUEST", "PAY_NOW"):
                return "Zaroor" if intent_repeats == 0 else "Jaise pehle bataya"
            if intent == "GREETING":
                return "Namaste"
            return "Shukriya"
        # English: context-aware ack that changes on repeat.
        if intent in ("PROMISE_TO_PAY", "PAY_LATER"):
            return "Absolutely" if intent_repeats == 0 else "As mentioned earlier"
        if intent in ("PAYMENT_PLAN_REQUEST", "SPLIT_EMI"):
            return "Of course" if intent_repeats == 0 else "As we discussed"
        if intent == "QUESTION":
            return "Sorry for the inconvenience" if intent_repeats == 0 else "I hear you"
        if intent == "SUPPORT":
            return "Of course"
        if intent in ("PAYMENT_LINK_REQUEST", "PAYMENT_RETRY_REQUEST", "PAY_NOW"):
            return "Sure" if intent_repeats == 0 else "As shared earlier"
        if intent == "GREETING":
            return "Hello"
        return "Thanks for reaching out"

    # ============================================================
    # TEMPLATE-BASED REPLY RESOLUTION
    # ============================================================
    # Uses _select_template to pick the right text template for the
    # intent+language combination, then fills placeholders. Edge cases
    # (plan_modification, split_details, promise_at) are handled inline.
    # ============================================================

    labels = _HI if hinglish else _EN
    ack = _context_ack(intent)
    repeat = "" if intent_repeats == 0 else (
        " Pehle bhi bataya tha, " if hinglish else " I see you're still trying to sort this out —"
    )
    monitor_note = (
        " — monitor mode mein automated reminders band hain."
        if hinglish and monitor_mode
        else " — we're in monitor mode, so no automated reminder was queued."
        if monitor_mode
        else " — isse pehle koi automated follow-up nahi bhejenge."
        if hinglish
        else " — no automated follow-ups until then."
    )
    link_line = (
        f"Yeh raha aapka secure payment link: {url}"
        if hinglish
        else f"Here is your secure payment link: {url}"
    )
    split_label_fn = lambda c: f"{c} Kishton mein baantein" if hinglish else f"Split in {c} EMIs"
    split_breakdown_text = ""

    # --- Partial-payment turn ("I can pay ₹2,000 today") ---
    # The customer names an amount they can send NOW. Acknowledge exactly that
    # amount on the card/CTA, never claim the full balance is being settled,
    # and offer to split the remainder or pay later. Deterministic parse only.
    partial_paise = (
        extract_partial_amount(customer_message, amount_paise)
        if customer_message and intent == "PAY_NOW"
        else None
    )
    if partial_paise is not None:
        partial_due = format_amount(partial_paise)
        remaining_due = format_amount(amount_paise)
        if hinglish:
            partial_text = (
                f"{ack}, {name}{ji}! Bilkul — aap aaj {partial_due} bhej sakte "
                f"hain. Yeh raha aapka payment link:\n{url}\n\n"
                f"Baaki {remaining_due} ke liye aap split kar sakte hain ya baad "
                f"mein pay kar sakte hain."
            )
        else:
            partial_text = (
                f"{ack}, {name}{ji}! You can pay {partial_due} today — here is "
                f"your payment link:\n{url}\n\n"
                f"Would you like to split the remaining {remaining_due} into "
                f"installments, or pay it later?"
            )
        partial_replies = [
            _p("pay_now", labels["pay_now"].format(due=partial_due)),
            _p("split_2", labels["split_2"]),
            _p("pay_later", labels["pay_later"]),
            _p("support", labels["support"]),
        ]
        partial_replies.append(
            {"id": "language_hi", "label": "\u0939\u093f\u0902\u0926\u0940 / Hinglish"}
        )
        partial_replies.append({"id": "language_en", "label": "English"})
        partial_sentiment = assess_sentiment(customer_message)
        return {
            "payload_type": "whatsapp",
            "text": partial_text,
            "language_options": [
                {"code": "en", "label": "English"},
                {"code": "hi", "label": "\u0939\u093f\u0902\u0926\u0940 / Hinglish"},
            ],
            "intent": intent,
            "recovered": False,
            "quick_replies": partial_replies,
            "split_options": [],
            "payment_card": {
                "amount": partial_paise,
                "amount_formatted": partial_due,
                "invoice_id": inv,
                "gateway": GATEWAY_LABEL,
                "url": url,
                "label": f"Pay {partial_due} securely",
                "installment": False,
                "remaining_amount": amount_paise,
                "remaining_amount_formatted": remaining_due,
            },
            "installment_breakdown": None,
            "payment_plan": None,
            "policy_action": {
                "increment_attempt_counter": False,
                "next_state": "ENGAGED",
            },
            "thought_process": (
                f"Customer can pay {partial_due} today (of {remaining_due} due) — "
                "offering a partial payment now plus split/pay-later options."
            ),
            "sentiment_assessment": partial_sentiment,
            "proposed_action": "send_payment_link",
            "recommended_channel": "WhatsApp",
        }

    # --- Intent-specific edge cases (before template resolution) ---
    # Map Recovery Specialist intents to legacy processing paths
    _plan_intent = intent in ("PAYMENT_PLAN_REQUEST", "SPLIT_EMI")
    _promise_intent = intent in ("PROMISE_TO_PAY", "PAY_LATER")

    if intent == "PAYMENT_PLAN_REQUEST" and plan_modification:
        new_count = plan_modification.get("new_count", 2)
        new_amounts = calculate_installments(amount_paise, new_count)
        new_formatted = [format_amount(a) for a in new_amounts]
        if hinglish:
            text = f"Thik hai {name}{ji}, {new_count} kishton mein split: {', '.join(new_formatted)}. Activate: {url}"
        else:
            text = f"Updated to {new_count} installments: {', '.join(new_formatted)}. Activate: {url}"
        quick_replies = [
            _p("activate_plan", labels["activate_plan"]),
            _p("pay_now", labels["pay_now"].format(due=due_amount)),
            _p("support", labels["support"]),
        ]
    elif _plan_intent and split_details:
        if hinglish:
            breakdown = _split_breakdown(split_details)
            if emi_active:
                text = (
                    f"Samajh gaya {name}{ji}, split done: {breakdown}. "
                    f"Pehli kist {due_amount} aaj: {url}"
                )
            else:
                text = f"Split {name}{ji}: {breakdown}. Activate: {url}"
        else:
            label = split_details.get("label") or ""
            if not label:
                today = split_details.get("pay_today")
                later = split_details.get("pay_later")
                hint = split_details.get("later_hint", "after 15 days")
                label = f"2 installments of {today} today and {later} {hint}"
            if emi_active:
                text = f"Split: {label}. First installment {due_amount} due today: {url}"
            else:
                text = f"Split: {label}. Activate: {url}"
        quick_replies = [
            _p("pay_now", labels["pay_now"].format(due=due_amount)),
            _p("pay_full", labels["pay_full"].format(amount=amount)),
            _p("support", labels["support"]),
        ] if emi_active else [
            _p("activate_plan", labels["activate_plan"]),
            _p("pay_now", labels["pay_now"].format(due=due_amount)),
            _p("support", labels["support"]),
        ]
    elif _promise_intent:
        tmpl = _select_template(intent, hinglish, split_details, emi_active, promise_at)
        if promise_at:
            text = tmpl.text.format(
                name=name, ji=ji, url=url, due=due_amount,
                promise_label=_promise_date_label(promise_at),
                monitor_note=monitor_note, ack=ack, repeat="", escalate="",
                link_line="", split_breakdown="", split_label="",
            )
            quick_replies = [
                _p("pay_now", labels["pay_now"].format(due=due_amount)),
                _p("split_2", split_label_fn(2)),
                _p("split_4", split_label_fn(4)),
                _p("support", labels["support"]),
            ]
        else:
            text = tmpl.text.format(
                name=name, ji=ji, url=url, due=due_amount,
                promise_label="", monitor_note=monitor_note, ack=ack,
                repeat="", escalate="", link_line="",
                split_breakdown="", split_label="",
            )
            promise_labels = _HI_PROMISE if hinglish else _EN_PROMISE
            quick_replies = [
                _p("promise_tomorrow", promise_labels[0]),
                _p("promise_3days", promise_labels[1]),
                _p("promise_custom", promise_labels[2]),
                _p("support", labels["support"]),
            ]
    elif intent == "PAYMENT_LINK_REQUEST" or intent == "PAYMENT_RETRY_REQUEST":
        tmpl = _select_template(intent, hinglish, split_details, emi_active, promise_at)
        text = tmpl.text.format(
            name=name, ji=ji, url=url, due=due_amount, inv=inv,
            ack="", repeat="", escalate="", promise_label="",
            monitor_note="", split_breakdown="", split_label="",
            link_line=link_line,
        )
        quick_replies = [
            _p("pay_now", labels["pay_now"].format(due=due_amount)),
            _p("split_2", split_label_fn(2)),
            _p("split_4", split_label_fn(4)),
            _p("support", labels["support"]),
        ]
    else:
        # All other intents: resolve from template registry
        tmpl = _select_template(intent, hinglish, split_details, emi_active, promise_at)
        escalate = f"\n\n{escalate_note}" if escalate_note else ""
        repeat_prompt = "" if intent_repeats <= 1 else (
            " Pehle bhi bataya tha, " if hinglish else " I see you're still trying to sort this out —"
        )
        text = tmpl.text.format(
            name=name, ji=ji, url=url, due=due_amount, inv=inv,
            ack=ack, repeat=repeat_prompt, escalate=escalate,
            promise_label="", monitor_note="", link_line=link_line,
            split_breakdown="", split_label="",
        )
        # Build quick replies from template ids + label map
        quick_replies = _qr(labels, *tmpl.quick_reply_ids, due=due_amount, amount=amount)

    # --- Post-resolution: add plan_modification quick replies override ---
    if intent == "PAYMENT_PLAN_REQUEST" and plan_modification:
        pass  # already set above

    # Always offer the conversation control chips (Pay Later + Choose Language)
    # alongside the primary action chips, appended LAST so earlier "activate_plan"
    # first-position assertions in tests keep passing. PROMISE_TO_PAY already
    # carries its own date-option chips, so the redundant "Pay Later" control is
    # skipped there.
    if quick_replies and intent not in (
        "STOP_REQUEST",
        "SUPPORT",
        "QUESTION",
        "PROMISE_TO_PAY",
        "NEGATIVE",
        "INVOICE_REQUEST",
        "LANGUAGE_SWITCHED",
    ):
        quick_replies.append(
            {"id": "pay_later", "label": "Pay Later" if not hinglish else "Baad Mein Pay Karein"},
        )
        quick_replies.append({"id": "language_hi", "label": "हिंदी / Hinglish"})
        quick_replies.append({"id": "language_en", "label": "English"})

    payment_card = {
        "amount": due_amount_paise,
        "amount_formatted": due_amount,
        "invoice_id": inv,
        "gateway": GATEWAY_LABEL,
        "url": url,
        "label": f"Pay {due_amount} securely",
        "installment": emi_active,
        "remaining_amount": amount_paise,
        "remaining_amount_formatted": amount,
    }

    # --- Structured recovery intelligence fields ---
    # These fields power the Recovery Decision panel and audit trail.
    # Deterministic: no AI involved in any of these lookups.
    _sentiment = assess_sentiment(customer_message) if customer_message else "Neutral"
    _proposed_action = _action_for_intent(intent)
    _recommended_channel = (
        "WhatsApp" if intent not in ("QUESTION", "SUPPORT") else "Email"
    )
    _failure_label = failure_reason_label(failure_reason) if failure_reason else None
    _thought = (
        f"Attempt {attempt_count}: Customer intent is {intent.replace('_', ' ').lower()}"
        + (f", sentiment is {_sentiment.lower()}" if customer_message else "")
        + (f", root cause: {_failure_label}" if _failure_label else "")
        + f". Routing to {_proposed_action} via {_recommended_channel}."
    )

    # --- Installment breakdown with due dates ---
    installment_breakdown = None
    if intent == "PAYMENT_PLAN_REQUEST" and (split_details or plan_modification):
        target_count = split_count or (plan_modification or {}).get("new_count") or 2
        target_amount = amount_paise
        if plan_modification:
            target_amount = plan_modification.get("part_amount", amount_paise)
            target_count = plan_modification.get("new_count", target_count)
        custom_plan = custom_installment_plan(target_amount, count=target_count)
        installment_breakdown = {
            "count": custom_plan["count"],
            "amounts": custom_plan["amounts"],
            "amounts_formatted": custom_plan["amounts_formatted"],
            "due_dates": custom_plan["due_dates"],
            "due_dates_formatted": custom_plan["due_dates_formatted"],
            "label": custom_plan["label"],
        }

    # --- Structured payment_plan payload (enterprise schema) ---
    payment_plan_payload = None
    if intent == "PAYMENT_PLAN_REQUEST" and (split_details or plan_modification):
        target_count = split_count or (plan_modification or {}).get("new_count") or 2
        target_amount = amount_paise
        if plan_modification:
            target_amount = plan_modification.get("part_amount", amount_paise)
            target_count = plan_modification.get("new_count", target_count)
        payment_plan_payload = _build_payment_plan_payload(
            total_amount_paise=target_amount,
            count=target_count,
            case_id=case_id,
        )
        # Repetition suppression: flag if this is a repeat request
        if intent_repeats > 0:
            payment_plan_payload["is_repeat"] = True
            payment_plan_payload["modification_note"] = (
                "Updated plan based on your request. Previous plan replaced."
            )

    # --- Policy action (deterministic, no AI) ---
    policy_action = {
        "increment_attempt_counter": False,
        "next_state": _next_state_for_intent(intent, recovered, split_details is not None),
    }

    return {
        "payload_type": "whatsapp",
        "text": text,
        "language_options": [
            {"code": "en", "label": "English"},
            {"code": "hi", "label": "\u0939\u093f\u0902\u0926\u0940 / Hinglish"},
        ],
        "intent": intent,
        "recovered": bool(recovered),
        "quick_replies": quick_replies,
        # Non-negotiation turns (handoff, clarification, language switch,
        # negative feedback, invoice copy, already paid) never carry the split
        # widget, so the EMIs chip/card is not re-spammed mid-dialogue.
        "split_options": (
            []
            if recovered or intent in _NO_PAYMENT_WIDGET_INTENTS
            else _split_options()
        ),
        # Rule: an interactive checkout card is only dispatched on a link/plan
        # turn. Clarifying / handoff / language-switch turns stay text-only so
        # the card is never re-spammed mid-dialogue.
        "payment_card": (
            payment_card
            if quick_replies
            and not recovered
            and intent not in _NO_PAYMENT_WIDGET_INTENTS
            else None
        ),
        # Structured installment breakdown with due dates
        "installment_breakdown": installment_breakdown,
        # Enterprise payment plan schema
        "payment_plan": payment_plan_payload,
        # Policy action (deterministic, no AI)
        "policy_action": policy_action,
        # Recovery Intelligence fields
        "thought_process": _thought,
        "sentiment_assessment": _sentiment,
        "proposed_action": _proposed_action,
        "recommended_channel": _recommended_channel,
    }


def _build_payment_plan_payload(
    total_amount_paise: int,
    count: int,
    case_id: str,
    include_payment_link: bool = False,
) -> dict:
    """Build the enterprise payment_plan payload with installments.

    Returns a dict matching the exact schema:
    {
        "total_amount": <number>,
        "currency": "INR",
        "installments": [
            {
                "part": <number>,
                "total_parts": <number>,
                "amount": <number>,
                "due_date": "<Date or relative time>",
                "status": "DUE_NOW" | "SCHEDULED"
            }
        ]
    }
    """
    from datetime import date as _date, timedelta as _td

    total_inr = total_amount_paise // 100
    start = _date.today()

    # Calculate installment amounts directly in INR to avoid paise->INR rounding errors
    base_inr = total_inr // count
    remainder = total_inr % count
    amounts_inr = [base_inr + 1 if i < remainder else base_inr for i in range(count)]

    installments = []
    for i, amt_inr in enumerate(amounts_inr):
        due = start + _td(days=i * 15)
        if i == 0:
            due_label = "Today"
            status = "DUE_NOW"
        elif i == 1:
            due_label = "In 15 days"
            status = "SCHEDULED"
        else:
            due_label = f"In {i * 15} days"
            status = "SCHEDULED"

        inst = {
            "part": i + 1,
            "total_parts": count,
            "amount": amt_inr,
            "due_date": due_label,
            "status": status,
        }
        # payment_link only included when explicitly requested
        if include_payment_link:
            inst["payment_link"] = payment_url_for_case(case_id)
        installments.append(inst)

    return {
        "total_amount": total_inr,
        "currency": "INR",
        "installments": installments,
    }


def _next_state_for_intent(intent: str, recovered: bool, has_plan: bool) -> str:
    """Determine the next state for the policy_action payload.

    Returns the deterministic next state based on the current intent.
    """
    if recovered:
        return "RECOVERED"
    return {
        "PAYMENT_PLAN_REQUEST": "NEGOTIATION_ACTIVE",
        "PROMISE_TO_PAY": "PROMISED",
        "PAYMENT_LINK_REQUEST": "ENGAGED",
        "PAYMENT_RETRY_REQUEST": "ENGAGED",
        "QUESTION": "ENGAGED",
        "SUPPORT": "ENGAGED",
        "STOP_REQUEST": "STOPPED",
        "NEGATIVE": "ENGAGED",
        "UNCLEAR": "ENGAGED",
    }.get(intent, "ENGAGED")


def split_plan_payload(amount_paise: int, count: int = 2, pay_today: int | None = None, pay_later: int | None = None) -> dict:
    """Human copy for an N-installment split offer.

    When ``pay_today``/``pay_later`` are provided (legacy 2-EMI callers) they are
    used verbatim; otherwise the amounts are derived from ``calculate_installments``.
    """
    if pay_today is not None and pay_later is not None:
        summary = split_summary(amount_paise, 2)
        summary["amounts"] = [pay_today, pay_later]
        summary["amounts_formatted"] = [format_amount(pay_today), format_amount(pay_later)]
        summary["label"] = (
            f"2 installments of {format_amount(pay_today)} today and "
            f"{format_amount(pay_later)} after 15 days"
        )
        return summary
    return split_summary(amount_paise, count)


# ============================================================
# DYNAMIC PLAN CALCULATION (custom installments + sub-splits)
# ============================================================

def custom_installment_plan(
    total_amount: int,
    count: int = 2,
    start_date: str | None = None,
    interval_days: int = 15,
) -> dict:
    """Calculate a custom installment plan with specific start date and interval.

    ``start_date`` is an ISO-format date string (e.g. "2026-09-01").
    ``interval_days`` defaults to 15 but can be customized (e.g. 7 for weekly).

    Returns a dict with:
    - amounts: list of per-installment amounts in paise
    - amounts_formatted: list of formatted strings (e.g. ["₹3,750", "₹3,750"])
    - due_dates: list of ISO date strings for when each installment is due
    - due_dates_formatted: list of human-readable date strings
    - label: English summary text
    - total: total amount in paise
    """
    from datetime import date as _date, timedelta as _td

    amounts = calculate_installments(total_amount, count)

    # Resolve start date (default: today)
    try:
        if start_date:
            start = _date.fromisoformat(start_date)
        else:
            start = _date.today()
    except (ValueError, TypeError):
        start = _date.today()

    due_dates = []
    due_dates_formatted = []
    for i in range(count):
        due = start + _td(days=i * interval_days)
        due_dates.append(due.isoformat())
        due_dates_formatted.append(due.strftime("%d %b %Y"))

    parts = []
    for i, (amt, dd) in enumerate(zip(amounts, due_dates_formatted)):
        if i == 0:
            parts.append(f"{format_amount(amt)} due {dd} (today)")
        else:
            parts.append(f"{format_amount(amt)} due {dd}")

    label = f"{count} installments: " + ", ".join(parts)

    return {
        "count": count,
        "amounts": amounts,
        "amounts_formatted": [format_amount(a) for a in amounts],
        "due_dates": due_dates,
        "due_dates_formatted": due_dates_formatted,
        "label": label,
        "total": total_amount,
        "interval_days": interval_days,
    }


def build_subsplit_breakdown(
    part_amount: int,
    part_count: int,
    parent_amount: int,
    parent_count: int,
) -> dict:
    """Build a breakdown for a sub-split (splitting an existing plan part).

    Returns a structured payload with:
    - sub_plan: the sub-split details
    - parent_remaining: what's left on the parent plan
    - full_converted: the fully-converted 4-installment alternative
    - modification_ack: explicit acknowledgment text
    """
    sub_plan = custom_installment_plan(part_amount, count=part_count)
    remaining = parent_amount - part_amount
    full_converted = custom_installment_plan(parent_amount, count=parent_count)

    return {
        "sub_plan": sub_plan,
        "parent_remaining": remaining,
        "parent_remaining_formatted": format_amount(remaining),
        "full_converted": full_converted,
        "modification_ack": (
            f"Sure, we can break that {format_amount(part_amount)} into "
            f"{part_count} smaller installments of "
            f"{', '.join(sub_plan['amounts_formatted'])} each."
        ),
    }


def detect_plan_modification(
    message_text: str,
    current_split_count: int | None = None,
) -> dict | None:
    """Detect if a customer is requesting to modify an existing plan.

    Looks for patterns like:
    - "can we do 4 instead" -> changing from current to 4
    - "make it 3 installments" -> changing to 3
    - "split into 6 parts" -> changing to 6

    Returns {"new_count": N, "modification_type": "change_count"} or None.
    """
    if not message_text:
        return None

    import re

    # Patterns for changing installment count
    patterns = [
        r"(?:can|could|make|change|do|try|want|prefer).*(?:\b(\d+)\s*(?:installments?|parts?|kisht|emi)\b)",
        r"(?:\b(\d+)\s*(?:installments?|parts?|kisht|emi)\b).*(?:instead|instead|do|try)",
        r"(?:instead|instead).*(?:\b(\d+)\s*(?:installments?|parts?|kisht|emi)\b)",
        r"(?:\b(\d+)\s*(?:installments?|parts?|kisht|emi)\b)",
    ]

    for pattern in patterns:
        m = re.search(pattern, message_text.lower())
        if m:
            new_count = int(m.group(1))
            if 2 <= new_count <= 12 and new_count != current_split_count:
                return {
                    "new_count": new_count,
                    "modification_type": "change_count",
                }

    return None


def is_plan_modification_context(history: list[str] | None) -> bool:
    """Check if the conversation history suggests the customer is modifying a plan.

    Returns True if there was a recent PAYMENT_PLAN_REQUEST in the history,
    indicating the customer is adjusting an existing plan rather than requesting
    a new one.
    """
    if not history:
        return False
    # If the last 2 intents include a PAYMENT_PLAN_REQUEST, we're in modification context
    recent = history[-2:] if len(history) >= 2 else history
    return "PAYMENT_PLAN_REQUEST" in recent


# ============================================================
# SYNCHRONIZED TRANSACTIONAL EMAIL (HTML)
# ============================================================


def build_email_subject(amount_paise: int, invoice_id: str) -> str:
    """Subject for the synchronized payment-failed email."""
    return f"Action Required: Payment failed for Invoice #{invoice_id} ({format_amount(amount_paise)})"


def render_payment_failed_email_html(
    *,
    customer_name: str | None,
    amount_paise: int,
    invoice_id: str,
    case_id: str,
    failure_reason: str | None = None,
) -> str:
    """Render a professional HTML transactional email for a failed payment.

    Includes an invoice breakdown, a Pay Now CTA, alternative payment options
    (UPI / Netbanking / Cards) and a mandatory DND/unsubscribe footer.
    """
    name = _first_name(customer_name)
    amount = format_amount(amount_paise)
    reason = failure_reason_label(failure_reason)
    url = payment_url_for_case(case_id)
    base_host = get_pay_host()

    return f"""<!DOCTYPE html>
<html lang="en">
  <body style="margin:0;padding:0;background-color:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6;padding:24px 0;">
      <tr><td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">
          <tr>
            <td style="background-color:#1e3a8a;padding:24px 28px;">
              <span style="font-size:20px;font-weight:700;color:#ffffff;">Fail2Pay</span>
              <span style="float:right;font-size:12px;color:#bfdbfe;">Action Required</span>
            </td>
          </tr>
          <tr><td style="padding:28px;">
            <p style="margin:0 0 12px;font-size:16px;color:#111827;">Hi {name},</p>
            <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">
              Your payment of <strong>{amount}</strong> for Invoice
              <strong>#{invoice_id}</strong> could not be completed due to
              <strong>{reason}</strong>. Don't worry &mdash; your order is
              temporarily held for you.
            </p>

            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;margin:0 0 20px;">
              <tr><td style="padding:16px;">
                <p style="margin:0 0 8px;font-size:13px;color:#6b7280;">Invoice Breakdown</p>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;color:#111827;">
                  <tr>
                    <td style="padding:4px 0;">Invoice ID</td>
                    <td align="right" style="font-weight:600;">#{invoice_id}</td>
                  </tr>
                  <tr>
                    <td style="padding:4px 0;">Amount due</td>
                    <td align="right" style="font-weight:700;color:#111827;">{amount}</td>
                  </tr>
                </table>
              </td></tr>
            </table>

            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px;">
              <tr><td align="center">
                <a href="{url}" style="display:inline-block;background-color:#16a34a;color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;padding:14px 32px;border-radius:8px;">Pay Now {amount}</a>
              </td></tr>
            </table>

            <p style="margin:0 0 8px;font-size:13px;color:#6b7280;">Alternative payment options:</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px;">
              <tr>
                <td style="padding:6px;background-color:#f3f4f6;border-radius:6px;text-align:center;font-size:13px;color:#374151;">\U0001F4F1 UPI</td>
                <td style="width:8px;"></td>
                <td style="padding:6px;background-color:#f3f4f6;border-radius:6px;text-align:center;font-size:13px;color:#374151;">\U0001F3E6 Netbanking</td>
                <td style="width:8px;"></td>
                <td style="padding:6px;background-color:#f3f4f6;border-radius:6px;text-align:center;font-size:13px;color:#374151;">\U0001F4B3 Cards</td>
              </tr>
            </table>

            <p style="margin:0 0 20px;font-size:13px;color:#6b7280;line-height:1.6;">
              If you've already paid, please ignore this email. Need help?
              Reply to this email or contact support and we'll assist you right away.
            </p>

            <hr style="border:none;border-top:1px solid #e5e7eb;margin:0 0 12px;" />
            <p style="margin:0;font-size:11px;color:#9ca3af;line-height:1.5;">
              You are receiving this email because you have an outstanding payment with Fail2Pay.
              <a href="{base_host}/dnd/unsubscribe" style="color:#9ca3af;">Unsubscribe</a>
              &nbsp;|&nbsp; <a href="#" style="color:#9ca3af;">DND Settings</a>
            </p>
          </td></tr>
          <tr><td style="background-color:#f9fafb;padding:12px 28px;border-top:1px solid #e5e7eb;">
            <p style="margin:0;font-size:11px;color:#9ca3af;">This is a transactional message from Fail2Pay. Do not reply directly to this email.</p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""


# ============================================================
# AUTONOMOUS CONVERSATION ENGINE (single-turn handler)
# ============================================================


def _resolve_language(
    language_pref: str | None, message_text: str | None, persisted_lang: str | None
) -> str:
    """Resolve the reply language: explicit pref > message sniff > persisted.

    ``hi``/``hi-en`` (and the underscore variant) render Romanized Hinglish
    copy, everything else stays English. An explicit customer preference always
    wins; otherwise the current message is sniffed for Hindi/Hinglish script or
    keywords so the agent responds in the customer's own tone.
    """
    if language_pref:
        if language_pref in ("hi", "hi-en", "hi_en"):
            return "hi-en"
        if language_pref in ("en", "en-us", "en-gb"):
            return "en"
    if message_text:
        from app.services.multilingual import detect_language

        detected = detect_language(message_text)
        if detected in ("hi", "hi-en", "or"):
            return "hi-en"
    return persisted_lang or "en"


_PROMISE_HOUR_TOKEN = {
    "12am": 0, "midnight": 0,
    "1am": 1, "2am": 2, "3am": 3, "4am": 4, "5am": 5,
    "6am": 6, "7am": 7, "8am": 8, "9am": 9, "10am": 10, "11am": 11,
    "12pm": 12, "noon": 12, "midday": 12,
    "1pm": 13, "2pm": 14, "3pm": 15, "4pm": 16, "5pm": 17,
    "6pm": 18, "7pm": 19, "8pm": 20, "9pm": 21, "10pm": 22, "11pm": 23,
}


def _parse_promise_time(message_text: str, now=None) -> datetime:
    """Parse a promised pay time from a customer message.

    Times are interpreted in the merchant/customer timezone (Asia/Kolkata) —
    "kal" / "tomorrow 11:00 baje" means 11:00 IST the next day — and returned
    as an aware UTC datetime (DB-compatible with the timezone-aware columns).

    Looks for hour tokens ("5 pm", "17:30", "at 5"), defaulting to the next
    day whenever the customer mentions "tomorrow", "kal", or a bare time that
    has already passed today. Minute resolution is preserved when provided.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")

    base_utc = now or _dt.now(_tz.utc)
    if base_utc.tzinfo is None:
        base_utc = base_utc.replace(tzinfo=_tz.utc)
    base = base_utc.astimezone(ist)
    lower = message_text.lower()

    # Determine the target day.
    day_offset = 0
    if any(t in lower for t in (" tomorrow", "tomorrow", " kal ", "kal ")):
        day_offset = 1
    elif any(t in lower for t in ("day after", "parson", "parso")):
        day_offset = 2

    # Resolve the hour (handle "5 PM", "5:30pm", "at 5", "11:00").
    hour_min = None

    def _merge(hh, mm, suffix):
        if suffix == "pm" and hh < 12:
            hh += 12
        elif suffix == "am" and hh == 12:
            hh = 0
        return (hh, mm)

    if hour_min is None:
        m = re.search(r"(\d{1,2})\s*(?::(\d{2}))?\s*(am|pm)\b", lower)
        if m:
            hour_min = _merge(int(m.group(1)), int(m.group(2) or 0), m.group(3))
    if hour_min is None:
        m = re.search(r"(\d{1,2}):(\d{2})\b", lower)
        if m:
            hour_min = (int(m.group(1)) % 24, int(m.group(2)))
    if hour_min is None:
        m = re.search(r"\bat\s+(\d{1,2})\b(?!\s*am|\s*pm)", lower)
        if m:
            hour_min = (int(m.group(1)) % 24, 0)
    if hour_min is None:
        for token, hh in _PROMISE_HOUR_TOKEN.items():
            normalized = re.sub(r"\s+", "", lower)
            if token in lower or token in normalized:
                hour_min = (hh, 0)
                break
    if hour_min is None:
        hour_min = (11, 0)

    day = base.date() + _td(days=day_offset)
    when = _dt(day.year, day.month, day.day, hour_min[0], hour_min[1], 0)
    # A bare time that's already behind us (before we add "tomorrow") slips
    # naturally to the next day unless the customer explicitly said "tomorrow".
    if day_offset == 0 and when.replace(tzinfo=ist) < base:
        when = when + _td(days=1)
    # Cap the promised time at, say, 11 PM so a late-night mention doesn't
    # schedule a reminder for the very next instant.
    if when.hour >= 23:
        when = when + _td(days=1)
        when = when.replace(hour=11, minute=0, second=0, microsecond=0)
    when = when.replace(second=0, microsecond=0)
    return when.replace(tzinfo=ist).astimezone(_tz.utc)


def _create_promise_reminder(db, case_id, when: datetime, label: str) -> dict:
    """Persist a ScheduledAction for a promise reminder (reuses scheduler)."""
    from app.crud.scheduled_action import create_scheduled_action
    from app.schemas.scheduled_action import ScheduledActionCreate

    action = create_scheduled_action(
        db,
        data=ScheduledActionCreate(
            recovery_case_id=case_id,
            action_type="reminder",
            attempt_number=1,
            channel="whatsapp",
            scheduled_for=when,
            extra_data={
                "reason": "promise_to_pay",
                "reminder_label": label,
            },
        ),
    )
    return {
        "action_id": str(action.id),
        "action_type": action.action_type,
        "scheduled_for": action.scheduled_for.isoformat() if action.scheduled_for else None,
        "label": label,
    }


def _action_for_intent(intent: str) -> str:
    """Map a detected CustomerIntent to the canonical agent action label."""
    return {
        # Recovery Specialist intents
        "PAY_NOW": "send_payment_link",
        "SPLIT_EMI": "propose_payment_plan",
        "PAY_LATER": "record_promise",
        "GREETING": "send_clarification",
        "FALLBACK": "send_clarification",
        # Legacy / granular intents
        "PAYMENT_LINK_REQUEST": "send_payment_link",
        "PAYMENT_RETRY_REQUEST": "send_payment_link",
        "INVOICE_REQUEST": "send_invoice",
        "PAYMENT_PLAN_REQUEST": "propose_payment_plan",
        "PROMISE_TO_PAY": "record_promise",
        "ALREADY_PAID": "check_payment_status",
        "QUESTION": "escalate_question",
        "SUPPORT": "escalate_to_human",
        "NEGATIVE": "pause_communication",
        "STOP_REQUEST": "stop_recovery",
        "UNCLEAR": "clarify",
    }.get(intent, "clarify")


# ============================================================
# CONTEXT-AWARE QUICK REPLY GENERATOR
# ============================================================

def generate_contextual_quick_replies(
    *,
    case,
    intent: str,
    language: str = "en",
    split_count: int = 2,
    has_active_plan: bool = False,
    has_active_promise: bool = False,
    promise_date: str | None = None,
) -> list[dict]:
    """Generate dynamically contextual quick-reply chips.

    Instead of a static block of generic buttons, the chips change based on:
    - The detected intent (what the customer just said)
    - Whether a payment plan or promise is already active
    - The language (Hinglish vs English)
    - The remaining amount (to show concrete installment figures)
    """
    remaining = case.remaining_amount if case.remaining_amount > 0 else case.original_amount
    hinglish = language in ("hi", "hi-en")

    def _fmt(amount_paise: int) -> str:
        return format_amount(amount_paise)

    def _chip(chip_id: str, label: str) -> dict:
        return {"id": chip_id, "label": label}

    # --- Promise-to-Pay context ---
    if intent == "PROMISE_TO_PAY":
        if has_active_promise:
            chips = [
                _chip("pay_now", f"{_fmt(remaining)} Abhi Pay" if hinglish else f"Pay {_fmt(remaining)} Now"),
                _chip("send_remind_link", "Send Remind Link" if not hinglish else "Remind Link Bhejo"),
                _chip("support", "Talk to Support" if not hinglish else "Support Se Baat Karein"),
            ]
        else:
            chips = [
                _chip("pay_now", f"{_fmt(remaining)} Abhi Pay" if hinglish else f"Pay {_fmt(remaining)} Now"),
                _chip("promise", "Kal Pakka" if hinglish else "Confirm for Tomorrow"),
                _chip("split_2", f"{2} Parts ({_fmt(remaining // 2)}/part)" if hinglish else f"Split into 2 ({_fmt(remaining // 2)}/part)"),
                _chip("support", "Need Support" if hinglish else "Need Support"),
            ]

    # --- Affordability / installment context ---
    elif intent == "PAYMENT_PLAN_REQUEST":
        if has_active_plan:
            chips = [
                _chip("pay_now", f"Pay Current Installment" if not hinglish else "Current Kist Pay"),
                _chip("pay_full", f"Pay Full {_fmt(remaining)}" if not hinglish else f"Poora {_fmt(remaining)} Pay"),
                _chip("support", "Talk to Support" if not hinglish else "Support Se Baat Karein"),
            ]
        else:
            half = remaining // 2
            quarter = remaining // 4
            chips = [
                _chip("split_2", f"2 Parts ({_fmt(half)}/mo)" if not hinglish else f"2 Kishton ({_fmt(half)}/part)"),
                _chip("split_4", f"4 Parts ({_fmt(quarter)}/mo)" if not hinglish else f"4 Kishton ({_fmt(quarter)}/part)"),
                _chip("pay_now", f"Pay {_fmt(remaining)} Now" if not hinglish else f"{_fmt(remaining)} Abhi Pay"),
                _chip("support", "Talk to Support" if not hinglish else "Support Se Baat Karein"),
            ]

    # --- Payment link request context ---
    elif intent in ("PAYMENT_LINK_REQUEST", "PAYMENT_RETRY_REQUEST"):
        chips = [
            _chip("pay_now", f"Pay {_fmt(remaining)} Now" if not hinglish else f"{_fmt(remaining)} Abhi Pay"),
            _chip("split_2", f"Split into 2" if not hinglish else "2 Parts mein Baantein"),
            _chip("support", "Talk to Support" if not hinglish else "Support Se Baat Karein"),
        ]

    # --- Already paid context ---
    elif intent == "ALREADY_PAID":
        chips = [
            _chip("send_invoice", "Send Invoice" if not hinglish else "Invoice Bhejo"),
            _chip("support", "Talk to Support" if not hinglish else "Support Se Baat Karein"),
        ]

    # --- Dispute / disinterest context ---
    elif intent in ("STOP_REQUEST", "NEGATIVE"):
        chips = [
            _chip("support", "Speak to Specialist" if not hinglish else "Specialist Se Baat"),
        ]

    # --- Question / support context ---
    elif intent in ("QUESTION", "SUPPORT"):
        chips = [
            _chip("pay_now", f"Pay {_fmt(remaining)} Now" if not hinglish else f"{_fmt(remaining)} Abhi Pay"),
            _chip("support", "Talk to Human" if not hinglish else "Insaan Se Baat Karein"),
        ]

    # --- Default / unclear context ---
    else:
        chips = [
            _chip("pay_now", f"Pay {_fmt(remaining)} Now" if not hinglish else f"{_fmt(remaining)} Abhi Pay"),
            _chip("split_2", "Split into 2" if not hinglish else "2 Parts mein Baantein"),
            _chip("promise", "I'll Pay Tomorrow" if not hinglish else "Kal Pakka Karunga"),
            _chip("support", "Need Support" if not hinglish else "Madad Chahiye"),
        ]

    # Always append language chips
    chips.append(_chip("language_hi", "हिंदी / Hinglish"))
    chips.append(_chip("language_en", "English"))

    return chips


def build_reasoning_steps(
    *,
    case,
    intent: str,
    confidence: float,
    language: str,
    message_text: str,
    intent_source: str = "rule_engine",
) -> list[dict]:
    """Build the reasoning steps that the Agent Thought Stream displays.

    Returns a list of typed step dicts that can be broadcast via WebSocket
    and persisted to the audit trail.
    """
    from datetime import datetime, timezone

    steps = []
    now = datetime.now(timezone.utc)

    # Step 1: Intent Parsing
    steps.append({
        "step_id": f"reasoning_{now.timestamp():.0f}_intent",
        "stage": "INTENT_PARSING",
        "type": "intent_parsing",
        "label": f"Intent: {intent.replace('_', ' ').title()}",
        "detail": f"Detected: {intent}, Language: {language}, Source: {intent_source}",
        "confidence": confidence,
        "occurred_at": now.isoformat(),
        "extra": {
            "message": message_text[:200],
            "confidence": confidence,
            "source": intent_source,
        },
    })

    # Step 2: Policy Evaluation
    attempt_str = f"{case.attempt_count}/{case.max_attempts}"
    remaining = case.remaining_amount
    steps.append({
        "step_id": f"reasoning_{now.timestamp():.0f}_policy",
        "stage": "POLICY_EVALUATION",
        "type": "policy_evaluation",
        "label": f"Attempt {attempt_str} · Remaining {format_amount(remaining)}",
        "detail": (
            f"Active attempt {attempt_str} -> "
            f"{'Schedule soft reminder' if remaining > 0 else 'Case recovered, hard stop'}"
        ),
        "confidence": 0.95,
        "occurred_at": now.isoformat(),
        "extra": {
            "attempt_count": case.attempt_count,
            "max_attempts": case.max_attempts,
            "remaining_amount": remaining,
        },
    })

    # Step 3: Diagnostic Sync
    root_cause = None
    if case.extra_data:
        root_cause = case.extra_data.get("root_cause")
    status_label = case.status.value if hasattr(case.status, "value") else str(case.status)
    steps.append({
        "step_id": f"reasoning_{now.timestamp():.0f}_diagnostic",
        "stage": "DIAGNOSTIC_SYNC",
        "type": "diagnostic_sync",
        "label": f"State: {status_label.replace('_', ' ').title()}",
        "detail": (
            f"Updated state: {status_label}"
            + (f", Root cause: {root_cause.replace('_', ' ').title()}" if root_cause else "")
            + f", Remaining: {format_amount(remaining)}"
        ),
        "confidence": 0.98,
        "occurred_at": now.isoformat(),
        "extra": {
            "status": status_label,
            "root_cause": root_cause,
        },
    })

    return steps


def handle_incoming_message(
    *,
    db,
    case_id,
    message_text: str,
    language_pref: str | None = None,
    detected_intent: str | None = None,
    create_promise: bool = True,
    create_plan: bool = True,
    split_count: int = 2,
) -> dict:
    """Run one full autonomous agent turn for a customer message.

    Detects the customer's intent (or reuses a pre-detected one the caller
    already resolved), resolves the language (Hinglish/English), flexibly
    handles the key recovery intents:

    * **Immediate pay / link request** — a direct Razorpay payment link for the
      outstanding balance, rendered as a rich ``payment_card`` CTA.
    * **Split / installment request** — a 2-part and 4-part split breakdown with
      a per-installment ``payment_card`` (Part 1 due today) and split options.
    * **Promise-to-pay** — parses the promised date/time and, when
      ``create_promise`` is set, records a real ``ScheduledAction`` reminder.
    * **Stop / dispute / support / unclear** — appropriate deterministic copy.

    ``create_plan``/``create_promise`` gate the database side effects so a
    caller (e.g. the webhook receiver) that already persisted the promise/plan
    can build just the reply + action payload here without duplicating records.
    """
    from app.models.recovery_case import RecoveryCase, RecoveryStatus

    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise ValueError(f"Recovery case {case_id} not found")

    from app.models.customer import Customer

    customer = db.get(Customer, case.customer_id) if case.customer_id else None
    customer_name = customer.name if customer else None

    # --- Resolve intent (pre-detected wins) ---
    if not detected_intent:
        from app.schemas.intent import IntentDetectionRequest
        from app.services.intent_detector import detect_intent

        intent_response = detect_intent(
            IntentDetectionRequest(message=message_text, language=language_pref or "en")
        )
        intent = intent_response.result.intent.value
    else:
        intent = detected_intent

    # --- Resolve language (Hinglish / English) ---
    persisted_lang = (case.extra_data or {}).get("language", "en") if case.extra_data else "en"
    language = _resolve_language(language_pref, message_text, persisted_lang)

    # --- Persist language preference so future replies stay in it ---
    extra = dict(case.extra_data or {})
    if extra.get("language") != language:
        extra["language"] = language
        case.extra_data = extra
        db.commit()

    # Compute amount from the authoritative DB state — never trust frontend amounts.
    # Use remaining_amount directly: it is the single source of truth for what
    # the customer still owes.  Fall back to original_amount only when the DB
    # column is somehow unset (defensive).
    amount_paise = case.remaining_amount if case.remaining_amount > 0 else (case.original_amount or 0)
    invoice_id = invoice_id_for_case(str(case.id))
    url = payment_url_for_case(str(case.id))

    # --- Terminal-state guard ---
    # RECOVERED: only acknowledge with a thank-you, never spawn payment links.
    # STOPPED: allow re-engagement if the customer expresses payment intent;
    # otherwise acknowledge the stop.
    # LOST: only acknowledge.
    if case.status == RecoveryStatus.RECOVERED:
        reply_payload = build_reply(
            case_id=str(case.id),
            customer_name=customer_name,
            amount_paise=case.remaining_amount,
            intent="RECOVERED_CONFIRMATION",
            invoice_id=invoice_id,
            language=language,
            recovered=True,
            history=[],
        )
        return {
            "intent": "RECOVERED_CONFIRMATION",
            "language": language,
            "action": "none",
            "text": reply_payload["text"],
            "agent_payload": reply_payload,
            "pay_now_url": url,
            "split": None,
            "plan": None,
            "promise_scheduled": None,
        }
    elif case.status in (RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        # If the customer is expressing payment intent on a STOPPED case,
        # re-activate the case so the recovery workflow resumes.
        payment_intents = (
            "PAYMENT_LINK_REQUEST", "PAYMENT_RETRY_REQUEST",
            "PROMISE_TO_PAY", "PAYMENT_PLAN_REQUEST",
            "PAY_NOW", "SPLIT_EMI", "PAY_LATER",
        )
        if case.status == RecoveryStatus.STOPPED and intent in payment_intents:
            case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
            case.closed_at = None
            extra = dict(case.extra_data or {})
            extra["reactivated_from"] = "STOPPED"
            case.extra_data = extra
            db.commit()
            db.refresh(case)
            # Fall through to normal processing below.
        else:
            intent_key = "STOP_REQUEST"
            is_recovered = case.status != RecoveryStatus.LOST
            reply_payload = build_reply(
                case_id=str(case.id),
                customer_name=customer_name,
                amount_paise=case.remaining_amount,
                intent=intent_key,
                invoice_id=invoice_id,
                language=language,
                recovered=False,
                history=[],
            )
            return {
                "intent": intent_key,
                "language": language,
                "action": "none",
                "text": reply_payload["text"],
                "agent_payload": reply_payload,
                "pay_now_url": url,
                "split": None,
                "plan": None,
                "promise_scheduled": None,
            }

    # --- Side effects per intent ---
    split_details = None
    pay_today = None
    plan_payload = None
    promise_payload = None
    promise_at = None  # confirmed promise datetime for build_reply

    # Map Recovery Specialist intents to legacy processing paths
    _intent_for_plan = intent in ("PAYMENT_PLAN_REQUEST", "SPLIT_EMI")
    _intent_for_promise = intent in ("PROMISE_TO_PAY", "PAY_LATER")

    if _intent_for_plan:
        amounts = calculate_installments(amount_paise, split_count)
        if amounts:
            pay_today = amounts[0]
        split_details = split_plan_payload(amount_paise, count=split_count)
        if create_plan:
            # Build the plan metadata the payload carries; a caller on the real
            # webhook path already accepted a real Renewable plan upstream.
            plan_payload = {
                "split_count": split_count,
                "amounts": amounts,
                "amounts_formatted": split_summary(amount_paise, split_count)["amounts_formatted"],
                "pay_today": pay_today,
                "pay_today_formatted": format_amount(pay_today) if pay_today else None,
            }
    elif _intent_for_promise:
        when = _parse_promise_time(message_text)
        if create_promise:
            # Create a REAL Promise database record (not just a ScheduledAction).
            # This ensures the UI, scheduler, and hard-stop layer all see the
            # active promise and pause generic reminders accordingly.
            from app.services.promise import create_promise_for_case

            promise_result = create_promise_for_case(
                db,
                case.id,
                customer_message=message_text,
                promised_date=when,
            )

            # Also schedule the promise reminder at the promised time.
            promise_payload = _create_promise_reminder(
                db, case.id, when, "Promise reminder"
            )
            promise_payload["promise_id"] = promise_result.get("promise_id")
            promise_payload["promise_status"] = promise_result.get("status")
            promise_payload["case_status"] = promise_result.get("case_status")
        else:
            promise_payload = {
                "action_id": None,
                "scheduled_for": when.isoformat(),
                "label": "Promise reminder",
            }
        promise_at = when

    # --- Build the contextual reply + rich action payload ---
    failure_reason = (case.extra_data or {}).get("root_cause") if case.extra_data else None
    reply_payload = build_reply(
        case_id=str(case.id),
        customer_name=customer_name,
        amount_paise=amount_paise,
        intent=intent,
        invoice_id=invoice_id,
        language=language,
        split_details=split_details,
        split_count=split_count if _intent_for_plan else None,
        pay_today=pay_today if _intent_for_plan else None,
        history=[intent],
        failure_reason=failure_reason,
        attempt_count=case.attempt_count,
        customer_message=message_text,
        promise_at=promise_at,
    )

    # --- Embed invoice card when intent is INVOICE_REQUEST ---
    invoice_email_status = None
    invoice_email_id = None
    if intent == "INVOICE_REQUEST":
        try:
            from sqlalchemy import select as _sel
            from app.models.invoice import Invoice
            # Reuse existing invoice if one already exists for this case
            existing = db.execute(
                _sel(Invoice).where(Invoice.recovery_case_id == case.id)
            ).scalars().first()
            if existing:
                from app.services.invoice import generate_secure_url
                secure_url = generate_secure_url(existing.secure_token)
                pdf_url = f"/api/invoices/{existing.id}/pdf"
                reply_payload["invoice_card"] = {
                    "invoice_id": str(existing.id),
                    "invoice_number": existing.invoice_number,
                    "customer_name": customer_name,
                    "amount": existing.amount,
                    "amount_formatted": format_amount(existing.amount),
                    "status": existing.status or "Unpaid",
                    "secure_url": secure_url,
                    "pdf_url": pdf_url,
                }
            else:
                from app.services.invoice import create_recovery_invoice
                inv_result = create_recovery_invoice(db, case.id)
                if inv_result.get("status") == "created":
                    reply_payload["invoice_card"] = {
                        "invoice_id": inv_result.get("invoice_id"),
                        "invoice_number": inv_result.get("invoice_number"),
                        "customer_name": customer_name,
                        "amount": case.original_amount,
                        "amount_formatted": format_amount(case.original_amount),
                        "status": "Unpaid",
                        "secure_url": inv_result.get("secure_url"),
                        "pdf_url": inv_result.get("pdf_url"),
                    }

            # Auto-send the invoice email on request. Best-effort: a failure here
            # must not break the agent reply — the email dispatch card reflects the
            # real result so staff can retry manually if needed. Duplicate sends are
            # prevented by the email service's per-type dedup guard.
            from app.services.email import get_settings as _esettings
            if _esettings().email_api_key:
                from app.services.invoice import send_invoice_via_email
                inv_send = send_invoice_via_email(
                    db, case.id,
                    invoice_id=(
                        reply_payload["invoice_card"].get("invoice_id")
                        if reply_payload.get("invoice_card") else None
                    ),
                )
                invoice_email_status = inv_send.get("status")
                invoice_email_id = inv_send.get("email_id")
        except Exception:
            logger.debug("Failed to create invoice card payload for case %s", case.id)

    # --- Embed email dispatch card when intent is SUPPORT or INVOICE_REQUEST ---
    if intent in ("INVOICE_REQUEST", "SUPPORT"):
        try:
            from datetime import datetime as _dt_email, timezone as _tz_email
            from app.crud.customer import get_customer
            cust = get_customer(db, case.customer_id)
            if cust and cust.email:
                email_type = "invoice" if intent == "INVOICE_REQUEST" else "support"
                delivery = invoice_email_status or (
                    "sent" if intent == "INVOICE_REQUEST" else "queued"
                )
                reply_payload["email_dispatch"] = {
                    "recipient_email": cust.email,
                    "subject": f"Payment details for Invoice #{invoice_id}",
                    "status": delivery,
                    "delivery_status": delivery,
                    "email_id": invoice_email_id,
                    "sent_at": _dt_email.now(_tz_email.utc).isoformat(),
                    "email_type": email_type,
                }
        except Exception:
            logger.debug("Failed to create email dispatch payload for case %s", case.id)

    # --- Persist recovery intelligence to case extra_data for the UI ---
    sentiment = reply_payload.get("sentiment_assessment", "Neutral")
    recommended_ch = reply_payload.get("recommended_channel", "WhatsApp")
    extra_intel = dict(case.extra_data or {})
    extra_intel["sentiment"] = sentiment
    extra_intel["recommended_channel"] = recommended_ch
    case.extra_data = extra_intel
    db.commit()

    return {
        "intent": intent,
        "language": language,
        "action": _action_for_intent(intent),
        "text": reply_payload["text"],
        "agent_payload": reply_payload,
        "pay_now_url": url,
        "split": split_details,
        "plan": plan_payload,
        "promise_scheduled": promise_payload,
    }


def process_turn(
    *,
    db,
    case_id,
    message_text: str,
    language_pref: str | None = None,
    persist: bool = True,
    detected_intent: str | None = None,
    create_promise: bool = True,
    create_plan: bool = False,
) -> dict:
    """Streaming-facing wrapper around ``handle_incoming_message``.

    Runs the autonomous turn and, when ``persist`` is set (default), writes the
    outbound Agent bubble (with its action payload) to the thread and emits it
    over WebSocket so a live dashboard appends the agent reply immediately.
    Returns a dict the caller can persist/broadcast or forward to a client.
    """
    from datetime import datetime as _dt, timezone as _tz
    from sqlalchemy import select

    result = handle_incoming_message(
        db=db,
        case_id=case_id,
        message_text=message_text,
        language_pref=language_pref,
        detected_intent=detected_intent,
        create_promise=create_promise,
        create_plan=create_plan,
    )

    conversation_id = None
    if persist:
        from app.models.conversation import Conversation
        from app.models.recovery_case import RecoveryCase
        from app.services import agent_flow

        case = db.get(RecoveryCase, case_id)
        conversation = (
            db.execute(
                select(Conversation)
                .where(
                    Conversation.recovery_case_id == case_id,
                    Conversation.channel == "whatsapp",
                )
                .order_by(Conversation.created_at.desc())
            ).scalars().first()
        )
        if conversation:
            conversation_id = str(conversation.id)
        agent_flow.persist_agent_reply(db, case, result["text"], result["agent_payload"])

    return {
        **result,
        "reply_text": result["text"],
        "conversation_id": conversation_id,
        "processed_at": _dt.now(_tz.utc).isoformat(),
    }


def to_recovery_agent_response(result: dict) -> dict:
    """Convert a handle_incoming_message result to RecoveryAgentResponse format.

    Maps the internal agent result to the structured JSON output format
    specified by the AI Recovery Specialist prompt.

    Args:
        result: Output from handle_incoming_message or process_turn

    Returns:
        dict matching the RecoveryAgentResponse schema for frontend rendering
    """
    from app.schemas.recovery_agent import RecoveryAgentResponse, ActionPayload

    intent = result.get("intent", "UNCLEAR")
    text = result.get("text", "")
    agent_payload = result.get("agent_payload", {})
    payment_card = agent_payload.get("payment_card")
    split = result.get("split")
    pay_now_url = result.get("pay_now_url", "")
    invoice_id = agent_payload.get("invoice_card", {}).get("invoice_id") if agent_payload else None

    # Determine suggested replies from quick_replies
    quick_replies = agent_payload.get("quick_replies", []) if agent_payload else []
    suggested_replies = [qr.get("label", "") for qr in quick_replies if qr.get("label")]

    # Build action payload
    show_card = payment_card is not None and payment_card.get("amount", 0) > 0
    amount = payment_card.get("amount") if payment_card else None
    emi_split = split.get("count") if split else None

    action_payload = ActionPayload(
        show_payment_card=show_card,
        amount=amount,
        emi_split=emi_split,
        payment_link=pay_now_url,
        invoice_id=invoice_id,
        invoice_link=agent_payload.get("invoice_card", {}).get("secure_url") if agent_payload else None,
    )

    # Build thought process (brief 1-line reason)
    _thought_map = {
        "PAY_NOW": "Customer wants to pay immediately",
        "SPLIT_EMI": "Customer wants to split into installments",
        "PAY_LATER": "Customer wants to delay payment",
        "GREETING": "Customer sent a casual greeting",
        "SUPPORT": "Customer wants to talk to a human agent",
        "FALLBACK": "Message was uninterpretable",
        "PAYMENT_RETRY_REQUEST": "Customer wants to retry payment",
        "PAYMENT_LINK_REQUEST": "Customer is asking for a payment link",
        "INVOICE_REQUEST": "Customer wants an invoice",
        "PAYMENT_PLAN_REQUEST": "Customer wants to set up a payment plan",
        "PROMISE_TO_PAY": "Customer is promising to pay",
        "ALREADY_PAID": "Customer claims they already paid",
        "QUESTION": "Customer has a general question",
        "NEGATIVE": "Customer is refusing to pay or frustrated",
        "STOP_REQUEST": "Customer wants to stop messages",
        "UNCLEAR": "Message was unclear or ambiguous",
    }
    thought_process = _thought_map.get(intent, "Customer message processed")

    response = RecoveryAgentResponse(
        thought_process=thought_process,
        intent=intent,
        message=text,
        suggested_replies=suggested_replies,
        action_payload=action_payload,
    )

    return response.model_dump()

