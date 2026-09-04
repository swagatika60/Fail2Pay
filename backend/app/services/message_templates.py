"""WhatsApp Message Templates for Recovery Workflows.

Professional, non-threatening templates for each stage of the recovery process.
Every message is logged and tracked. No messages are sent repeatedly without variation.

Template stages (spec no-response cadence, absolute from T0):
1. initial_payment_failed — first contact after payment failure (T+0)
2. reminder_1 — gentle reminder after 2 hours
3. reminder_2 — follow-up after 4 hours
4. reminder_3 — follow-up after 8 hours
5. reminder_4 — follow-up after 16 hours
6. reminder_5 — follow-up after 24 hours
7. reminder_6 — follow-up after 36 hours
8. final_notice — final attempt at the 48-hour mark, then STOP

Rules:
- Messages must NEVER be threatening, misleading, or aggressive
- Each message includes a payment link for easy recovery
- Messages are personalized with customer name and amount
- No duplicate messages are sent without at least 2 hours gap
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MessageTemplate:
    """A message template with metadata."""

    stage: str
    channel: str  # "whatsapp", "email", "sms"
    subject: str | None = None  # for email
    body: str = ""
    language: str = "en"


# --- Amount formatting helper ---

def format_amount(amount_paise: int) -> str:
    """Format amount in paise to human-readable Indian Rupee format.

    Examples:
        149900 → "₹1,499"
        5000000 → "₹50,000"
        10000000 → "₹1,00,000"
    """
    rupees = amount_paise // 100
    # Indian number formatting (lakhs, crores)
    s = str(rupees)
    if len(s) <= 3:
        return f"₹{s}"
    lastThree = s[-3:]
    remaining = s[:-3]
    # Add commas every 2 digits for remaining (Indian style)
    formatted = ""
    while len(remaining) > 2:
        formatted = "," + remaining[-2:] + formatted
        remaining = remaining[:-2]
    formatted = remaining + formatted + "," + lastThree
    return f"₹{formatted}"


# --- Template definitions ---

TEMPLATES = {
    "initial_payment_failed": MessageTemplate(
        stage="initial_payment_failed",
        channel="whatsapp",
        body=(
            "Hi {customer_name},\n\n"
            "Your payment of {amount} could not be completed. "
            "This might be due to insufficient funds, an expired card, or a bank issue.\n\n"
            "You can retry your payment here: {payment_link}\n\n"
            "Would you like to try again, split the payment into installments, "
            "or set up a payment plan? Just reply here and we'll set it up.\n\n"
            "If you've already paid, please ignore this message.\n\n"
            "Need help? Reply to this message and we'll assist you."
        ),
    ),
    "reminder_1": MessageTemplate(
        stage="reminder_1",
        channel="whatsapp",
        body=(
            "Hi {customer_name},\n\n"
            "Just a gentle reminder — your payment of {amount} is still pending.\n\n"
            "You can complete your payment here: {payment_link}\n\n"
            "If you're facing any issues, reply to this message and we'll help you out."
        ),
    ),
    "reminder_2": MessageTemplate(
        stage="reminder_2",
        channel="whatsapp",
        body=(
            "Hi {customer_name},\n\n"
            "We noticed your payment of {amount} hasn't gone through yet. "
            "We understand things come up — no worries.\n\n"
            "You can retry here: {payment_link}\n\n"
            "If you need a payment plan or have questions, just reply to this message."
        ),
    ),
    "reminder_3": MessageTemplate(
        stage="reminder_3",
        channel="whatsapp",
        body=(
            "Hi {customer_name},\n\n"
            "Just checking in — your payment of {amount} is still pending.\n\n"
            "You can complete it here: {payment_link}\n\n"
            "Prefer to split it into installments or pay later? Reply here and we'll set it up."
        ),
    ),
    "reminder_4": MessageTemplate(
        stage="reminder_4",
        channel="whatsapp",
        body=(
            "Hi {customer_name},\n\n"
            "Your payment of {amount} is still outstanding. No pressure — "
            "we're here to help you sort it out.\n\n"
            "You can pay now: {payment_link}\n\n"
            "Or reply with a date that works for you, and we'll pause follow-ups until then."
        ),
    ),
    "reminder_5": MessageTemplate(
        stage="reminder_5",
        channel="whatsapp",
        body=(
            "Hi {customer_name},\n\n"
            "A friendly check-in: your payment of {amount} remains pending.\n\n"
            "Complete it here: {payment_link}\n\n"
            "If you'd like a payment plan or need support, just reply to this message."
        ),
    ),
    "reminder_6": MessageTemplate(
        stage="reminder_6",
        channel="whatsapp",
        body=(
            "Hi {customer_name},\n\n"
            "We still haven't received your payment of {amount}. "
            "We'd love to resolve this with you.\n\n"
            "Please complete your payment here: {payment_link}\n\n"
            "Or reply and we'll find a solution together."
        ),
    ),
    "final_notice": MessageTemplate(
        stage="final_notice",
        channel="whatsapp",
        body=(
            "Hi {customer_name},\n\n"
            "This is a final reminder regarding your pending payment of {amount}.\n\n"
            "Please complete your payment here to avoid any disruption: {payment_link}\n\n"
            "If you've already paid, please disregard this message. "
            "For assistance, reply to this message."
        ),
    ),
}


def get_template(stage: str, channel: str = "whatsapp") -> MessageTemplate | None:
    """Get a message template by stage and channel."""
    template = TEMPLATES.get(stage)
    if template and template.channel == channel:
        return template
    return None


def render_message(
    stage: str,
    customer_name: str,
    amount_paise: int,
    payment_link: str,
    channel: str = "whatsapp",
    language: str = "en",
    failure_reason: str | None = None,
) -> MessageTemplate | None:
    """Render a message template with customer-specific data.

    Args:
        stage: Template stage (e.g., "initial_payment_failed")
        customer_name: Customer's name for personalization
        amount_paise: Amount in paise
        payment_link: Link to the payment page
        channel: Communication channel
        language: Language code
        failure_reason: When provided, the first-contact template names the actual
            gateway reason instead of the generic possible-causes sentence.

    Returns:
        Rendered MessageTemplate or None if template not found
    """
    template = get_template(stage, channel)
    if not template:
        logger.warning("Template not found: stage=%s, channel=%s", stage, channel)
        return None

    formatted_amount = format_amount(amount_paise)

    rendered_body = template.body.format(
        customer_name=customer_name or "Customer",
        amount=formatted_amount,
        payment_link=payment_link,
    )

    reason = (failure_reason or "").strip()
    if reason and template.stage == "initial_payment_failed":
        # Name the real failure reason when the gateway told us (deterministic
        # template surgery — never invented copy).
        generic_cause = (
            "This might be due to insufficient funds, an expired card, or a bank issue."
        )
        rendered_body = rendered_body.replace(
            generic_cause,
            f"The payment attempt was declined — {reason}.",
        )

    return MessageTemplate(
        stage=template.stage,
        channel=template.channel,
        subject=template.subject,
        body=rendered_body,
        language=language,
    )


def get_template_for_attempt(attempt_number: int) -> str:
    """Get the appropriate template stage based on attempt number.

    Matches the spec no-response cadence (absolute from T0):
    1 → initial_payment_failed   (T+0)
    2 → reminder_1               (T+2h)
    3 → reminder_2               (T+4h)
    4 → reminder_3               (T+8h)
    5 → reminder_4               (T+16h)
    6 → reminder_5               (T+24h)
    7 → reminder_6               (T+36h)
    8+ → final_notice            (T+48h, then STOP)
    """
    if attempt_number <= 1:
        return "initial_payment_failed"
    if attempt_number == 2:
        return "reminder_1"
    if attempt_number == 3:
        return "reminder_2"
    if attempt_number == 4:
        return "reminder_3"
    if attempt_number == 5:
        return "reminder_4"
    if attempt_number == 6:
        return "reminder_5"
    if attempt_number == 7:
        return "reminder_6"
    return "final_notice"


def get_payment_link(base_url: str | None = None, case_id: str = "") -> str:
    """Generate a payment link for a recovery case.

    When *base_url* is not provided (or is a placeholder), the configured
    payment portal host is resolved from the environment so the generated
    link is always reachable.
    """
    if not base_url or "fail2pay.example.com" in base_url:
        from app.services.agent_engine import get_pay_host
        base_url = get_pay_host()
    return f"{base_url}/pay/{case_id}"
