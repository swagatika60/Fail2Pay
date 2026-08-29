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
import os

logger = logging.getLogger(__name__)

# Default base URL for the clickable dynamic payment page. This is the
# production domain; for local development it can be overridden to a reachable
# host (e.g. http://localhost:5173/pay) via FAIL2PAY_PAY_HOST or the
# PAYMENT_LINK_BASE_URL setting. See get_pay_host().
PAY_HOST = os.environ.get("FAIL2PAY_PAY_HOST", "https://pay.fail2pay.com")

# Gateway label shown on the payment card.
GATEWAY_LABEL = "Razorpay"

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


def format_amount(amount_paise: int) -> str:
    """Format paise as Indian rupee (e.g. 1999000 -> ₹19,999)."""
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


def payment_url_for_case(case_id: str) -> str:
    """Clickable dynamic payment URL for a recovery case.

    The host is environment-aware: FAIL2PAY_PAY_HOST env takes precedence,
    then the configured payment_link_base_url setting, then the production
    default. This keeps local development on a reachable host instead of the
    hardcoded production domain.
    """
    return f"{get_pay_host()}/inv/{case_id}"


def get_pay_host() -> str:
    """Resolve the payment link base host for the current environment.

    Precedence: FAIL2PAY_PAY_HOST env > configured ``payment_link_base_url``
    (when it is an explicit, non-placeholder HTTP URL) > production default.
    """
    env_host = os.environ.get("FAIL2PAY_PAY_HOST", "").strip()
    if env_host:
        return env_host.rstrip("/")
    try:
        from app.config import get_settings

        configured = get_settings().payment_link_base_url.strip()
        if configured.startswith(("http://", "https://")) and "fail2pay.example.com" not in configured:
            return configured.rstrip("/")
    except Exception:
        pass
    return PAY_HOST.rstrip("/")


def calculate_installments(total_amount: int, count: int = 2) -> list[int]:
    """Split ``total_amount`` (paise) into ``count`` installments.

    Uses integer division (``total_amount // count``) for the base amount and
    distributes the exact remainder (``total_amount % count``) across the
    *initial* tranches (one extra paisa per tranche). Guarantees the sum of the
    returned amounts equals the total — no rupees/paise lost or invented.

    Mirrors the frontend ``calculateInstallments`` helper so both the API and
    the UI agree on the exact breakdown.
    """
    if count <= 0:
        raise ValueError("count must be a positive integer")
    base = total_amount // count
    remainder = total_amount % count
    # Spread the remainder over the FIRST `remainder` tranches.
    return [base + 1 if i < remainder else base for i in range(count)]


def split_summary(total_amount: int, count: int = 2) -> dict:
    """Human copy for an N-installment split offer (N >= 2)."""
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

    return {
        "count": count,
        "amounts": amounts,
        "amounts_formatted": [format_amount(a) for a in amounts],
        "label": label,
        "later_hint": later_hint,
        "total": total_amount,
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

    if hinglish:
        greeting = "Namaste"
        text = (
            f"{greeting} {name}{ji}! Aapka Invoice #{inv} ka bhugtan "
            f"{amount} {reason_hin} ki wajah se fail hua. Chinta mat karein \u2014 "
            f"aapka order aapke liye temporarily hold hai.\n\n"
            f"Aap ise securely complete kar sakte hain link se:\n"
            f"\U0001f449 {url}\n\n"
            f"Madad chahiye? Neeche se apna preferred option chunein."
        )
        pay_now = f"Abhi Pay Karein {amount}"
        split2 = "2 Kishton mein baantein"
        split4 = "4 Kishton mein baantein"
        support = "Support Se Baat Karein"
    else:
        greeting = "Hello"
        text = (
            f"{greeting} {name}{ji}! We noticed your payment of {amount} for "
            f"Invoice #{inv} failed due to {reason}. Don\u2019t worry \u2014 your order is "
            f"temporarily held for you.\n\n"
            f"You can complete it securely using the link below:\n"
            f"\U0001f449 {url}\n\n"
            f"Need help? Reply with your preferred option below."
        )
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
    """
    name = _first_name(customer_name)
    ji = _honorific(customer_name)
    amount = format_amount(amount_paise)
    inv = invoice_id or invoice_id_for_case(case_id)
    url = payment_url_for_case(case_id)
    hinglish = language in ("hi", "hi-en")
    history = history or []

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
        return {
            "payload_type": "whatsapp",
            "text": text,
            "language_options": [
                {"code": "en", "label": "English"},
                {"code": "hi", "label": "\u0939\u093f\u0902\u0926\u0940 / Hinglish"},
            ],
            "quick_replies": [],
            "split_options": _split_options(),
            "payment_card": None,
        }


    if hinglish:
        # Romanized Hinglish copy per intent.
        if intent == "PAYMENT_PLAN_REQUEST":
            if split_details and (split_count or split_details.get("count")):
                breakdown = _split_breakdown(split_details)
                if emi_active:
                    text = (
                        f"Bilkul {name}{ji}! Hum aapka amount split kar diya hai: "
                        f"{breakdown}.\n\nAapki pehli kist {due_amount} aaj ki hai. "
                        f"Isse yahan se settle karein:\n{url}\n\n"
                        f"Baaki {amount} aapke plan par bana rahega."
                    )
                    quick_replies = [
                        {"id": "pay_now", "label": _pay_now_label()},
                        {"id": "pay_full", "label": _pay_full_label()},
                        {"id": "support", "label": _talk_support_label()},
                    ]
                else:
                    text = (
                        f"Bilkul {name}{ji}! Hum aapka amount split kar sakte hain: "
                        f"{breakdown}. Neeche link se aap EMI plan activate kar "
                        f"sakte hain:\n{url}"
                    )
                    quick_replies = [
                        {"id": "activate_plan", "label": _activate_plan_label()},
                        {"id": "pay_now", "label": _pay_now_label()},
                        {"id": "support", "label": _talk_support_label()},
                    ]
            else:
                text = (
                    f"Koi baat nahi {name}{ji}! Main aapke invoice #{inv} ke "
                    f"liye EMI options check karta hoon. Hum isse aaram se "
                    f"split kar sakte hain. Chalein shuru karein: {url}"
                )
                quick_replies = [
                    {"id": "activate_plan", "label": _activate_plan_label()},
                    {"id": "pay_now", "label": _pay_now_label()},
                    {"id": "support", "label": _talk_support_label()},
                ]
        elif intent == "PROMISE_TO_PAY":
            text = (
                f"Bilkul {name}{ji}! Reminder pause kar diya hai aur kal 11:00 "
                f"baje reminder bhejenge. Aapka payment link active rahega:\n{url}"
            )
            quick_replies = [
                {"id": "pay_now", "label": _pay_now_label()},
                {"id": "split_2", "label": _split_label(2)},
                {"id": "support", "label": _talk_support_label()},
            ]
        elif intent == "QUESTION":
            text = (
                f"Mujhe afsos hai {name}{ji}. Main automated follow-up pause "
                f"kar deta hoon aur hamari billing team aapse connect hogi. "
                f"Revised breakdown email se jaayega." + (
                    f"\n\n{escalate_note}" if escalate_note else ""
                )
            )
            quick_replies = [{"id": "support", "label": _talk_support_label()}]
        elif intent == "STOP_REQUEST":
            text = (
                f"Samajh gaya {name}{ji}. Maine is matter par saari recovery "
                f"communication band kar di hai. Aage koi follow-up nahi "
                f"aayega. Agar galati se hua ho toh support se sampark karein."
            )
            quick_replies = []
        elif intent in ("PAYMENT_LINK_REQUEST", "PAYMENT_RETRY_REQUEST", "UNCLEAR"):
            text = f"{_link_line()}\n\n{due_amount} ka bhugtan kabhi bhi karein, Invoice #{inv} ke liye."
            quick_replies = [
                {"id": "pay_now", "label": _pay_now_label()},
                {"id": "split_2", "label": _split_label(2)},
                {"id": "support", "label": _talk_support_label()},
            ]
        elif intent == "SUPPORT":
            text = (
                f"Bilkul {name}{ji}! Main abhi hamari human support team ko "
                f"connect kar raha hoon — koi 2-3 minute mein issi chat mein "
                f"aayega ya yahin reply karega.\n\n"
                f"Tab tak aap chahe toh {due_amount} ka bhugtan abhi link se "
                f"kar sakte hain."
            )
            quick_replies = [
                {"id": "pay_now", "label": _pay_now_label()},
                {"id": "split_2", "label": _split_label(2)},
            ]
        else:
            text = (
                f"Shukriya {name}{ji}! Invoice #{inv} ke liye aap aaj "
                f"{due_amount} ka bhugtan yahan se complete kar sakte hain: {url}"
            )
            quick_replies = [
                {"id": "pay_now", "label": _pay_now_label()},
                {"id": "split_2", "label": _split_label(2)},
                {"id": "support", "label": _talk_support_label()},
            ]
    else:
        # English copy, still dynamic per history to avoid duplicate loops.
        ack = (
            "Thanks for reaching out"
            if intent_repeats == 0
            else "Got it"
            if intent_repeats == 1
            else "Noted"
        )
        repeat_prompt = "I see you're still trying to sort this out —" if intent_repeats > 1 else ""
        if intent == "PAYMENT_PLAN_REQUEST":
            if split_details:
                label = split_details.get("label")
                if not label:
                    today = split_details.get("pay_today")
                    later = split_details.get("pay_later")
                    hint = split_details.get("later_hint", "after 15 days")
                    label = f"2 installments of {today} today and {later} {hint}"
                if emi_active:
                    text = (
                        f"Absolutely, {name}{ji}! We've split this into {label}.\n\n"
                        f"Your first installment of {due_amount} is due today. You "
                        f"can settle it right here:\n{url}\n\n"
                        f"The remaining balance of {amount} stays on your plan."
                    )
                    quick_replies = [
                        {"id": "pay_now", "label": _pay_now_label()},
                        {"id": "pay_full", "label": _pay_full_label()},
                        {"id": "support", "label": "Talk to Support"},
                    ]
                else:
                    text = (
                        f"Absolutely, {name}{ji}! We can split this into {label}.\n\n"
                        f"Here is the link to activate your EMI plan:\n{url}"
                    )
                    quick_replies = [
                        {"id": "activate_plan", "label": "Activate EMI Plan"},
                        {"id": "pay_now", "label": _pay_now_label()},
                        {"id": "support", "label": "Talk to Support"},
                    ]
            else:
                text = (
                    f"Of course, {name}{ji}! Let me check what EMI options we "
                    f"can offer for your invoice #{inv}. We can split it into "
                    f"2 or 4 installments.\n\nYou can also start right away here: {url}"
                )
                quick_replies = _split_replies() + [
                    {"id": "pay_now", "label": f"Pay Now {amount}"},
                    {"id": "support", "label": "Talk to Support"},
                ]
        elif intent == "PROMISE_TO_PAY":
            text = (
                f"{ack}, {name}{ji}! I've paused reminders and scheduled a "
                f"reminder for tomorrow at 11:00 AM. Your payment link for "
                f"{due_amount} will remain active:\n{url}"
            )
            quick_replies = [
                {"id": "pay_now", "label": _pay_now_label()},
                {"id": "split_2", "label": "Split in 2 EMIs"},
                {"id": "split_4", "label": "Split in 4 EMIs"},
                {"id": "support", "label": "Talk to Support"},
            ]
        elif intent == "QUESTION":
            apology = (
                "Sorry for the inconvenience"
                if intent_repeats == 0
                else "I hear you"
                if intent_repeats == 1
                else "Understood"
            )
            text = (
                f"{apology}, {name}{ji}. {repeat_prompt} I've paused "
                f"automated follow-ups and connected our billing desk. Someone "
                f"will reach out here or by email within a few hours — no need "
                f"to repeat yourself." + (
                    f"\n\n{escalate_note}" if escalate_note else ""
                )
            )
            quick_replies = [{"id": "support", "label": "Talk to Support"}]
        elif intent == "STOP_REQUEST":
            text = (
                f"Understood, {name}{ji}. I have stopped all recovery "
                f"communication on this matter. You won't receive any further "
                f"follow-ups. If this was a mistake, please reach out to support."
            )
            quick_replies = []
        elif intent in ("PAYMENT_LINK_REQUEST", "PAYMENT_RETRY_REQUEST", "UNCLEAR"):
            text = (
                f"{_link_line()}\n\n"
                f"Tap it anytime to complete your payment of {due_amount} for Invoice #{inv}."
            )
            quick_replies = [
                {"id": "pay_now", "label": _pay_now_label()},
                {"id": "split_2", "label": "Split in 2 EMIs"},
                {"id": "split_4", "label": "Split in 4 EMIs"},
                {"id": "support", "label": "Talk to Support"},
            ]
        elif intent == "SUPPORT":
            text = (
                f"Of course, {name}{ji}! I'm looping in our human support team "
                f"right now — someone will join this chat within 2-3 minutes "
                f"or reply here directly. You can also keep a support ticket "
                f"handy if you prefer.\n\n"
                f"Meanwhile, if you'd like to pay the balance of {due_amount} "
                f"now, the link stays live below."
            )
            quick_replies = [
                {"id": "pay_now", "label": _pay_now_label()},
                {"id": "split_2", "label": "Split in 2 EMIs"},
            ]
        else:
            text = (
                f"Thanks for reaching out, {name}{ji}! For invoice #{inv} you "
                f"can complete your payment of {due_amount} here: {url}"
            )
            quick_replies = [
                {"id": "pay_now", "label": _pay_now_label()},
                {"id": "split_2", "label": "Split in 2 EMIs"},
                {"id": "split_4", "label": "Split in 4 EMIs"},
                {"id": "support", "label": "Talk to Support"},
            ]

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

    return {
        "payload_type": "whatsapp",
        "text": text,
        "language_options": [
            {"code": "en", "label": "English"},
            {"code": "hi", "label": "\u0939\u093f\u0902\u0926\u0940 / Hinglish"},
        ],
        "quick_replies": quick_replies,
        "split_options": _split_options(),
        "payment_card": payment_card if quick_replies else None,
    }


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

