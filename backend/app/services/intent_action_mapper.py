"""Intent-to-Action Mapper with Multilingual Support.

Maps detected customer intents to bounded, deterministic backend actions.
AI only classifies language — this mapper decides what the backend does.

Supports: English, Hindi, Hinglish, Odia
- Same intent taxonomy across languages
- Natural responses in customer's language (not word-for-word translation)
- Language never changes safety rules

Architecture:
  Customer message → AI classifies intent → Mapper decides action → Backend executes

Every action is:
- Safe: No arbitrary commands, no AI-generated code execution
- Bounded: Only predefined actions with predefined responses
- Audited: Every action is logged to the audit trail
- Policy-checked: Actions pass through the policy engine before execution
"""

import logging
from dataclasses import dataclass

from app.schemas.intent import CustomerIntent

logger = logging.getLogger(__name__)


@dataclass
class IntentAction:
    """A bounded action resulting from intent classification.

    This is what the backend executes. AI never creates or modifies this.
    """

    intent: CustomerIntent
    action_type: str  # what to do
    response_key: str  # key to look up response template in multilingual service
    requires_payment_link: bool = False  # whether to include payment link
    requires_invoice: bool = False  # whether to include invoice link
    update_case_status: str | None = None  # status transition to apply
    record_attempt_result: str | None = None  # result to record in RecoveryAttempt
    cancel_scheduled_actions: bool = False  # whether to cancel pending actions


# --- Intent → Action Mapping ---

# Every intent maps to exactly one bounded action.
# No intent can execute arbitrary commands.

INTENT_ACTIONS: dict[CustomerIntent, IntentAction] = {
    CustomerIntent.PAYMENT_LINK_REQUEST: IntentAction(
        intent=CustomerIntent.PAYMENT_LINK_REQUEST,
        action_type="send_payment_link",
        response_key="payment_link",
        requires_payment_link=True,
        record_attempt_result="payment_link_sent",
    ),
    CustomerIntent.INVOICE_REQUEST: IntentAction(
        intent=CustomerIntent.INVOICE_REQUEST,
        action_type="send_invoice",
        response_key="invoice",
        requires_invoice=True,
        record_attempt_result="invoice_sent",
    ),
    CustomerIntent.ALREADY_PAID: IntentAction(
        intent=CustomerIntent.ALREADY_PAID,
        action_type="check_payment_status",
        response_key="already_paid",
        record_attempt_result="customer_claimed_paid",
    ),
    CustomerIntent.PROMISE_TO_PAY: IntentAction(
        intent=CustomerIntent.PROMISE_TO_PAY,
        action_type="record_promise",
        response_key="promise_to_pay",
        requires_payment_link=True,
        update_case_status="PROMISED",
        record_attempt_result="promised",
    ),
    CustomerIntent.PAYMENT_PLAN_REQUEST: IntentAction(
        intent=CustomerIntent.PAYMENT_PLAN_REQUEST,
        action_type="propose_payment_plan",
        response_key="payment_plan",
        requires_payment_link=True,
        record_attempt_result="payment_plan_requested",
    ),
    CustomerIntent.QUESTION: IntentAction(
        intent=CustomerIntent.QUESTION,
        action_type="send_clarification",
        response_key="question",
        requires_payment_link=True,
        record_attempt_result="question_answered",
    ),
    CustomerIntent.NEGATIVE: IntentAction(
        intent=CustomerIntent.NEGATIVE,
        action_type="pause_communication",
        response_key="negative",
        record_attempt_result="negative_response",
    ),
    CustomerIntent.STOP_REQUEST: IntentAction(
        intent=CustomerIntent.STOP_REQUEST,
        action_type="stop_recovery",
        response_key="stop",
        update_case_status="STOPPED",
        cancel_scheduled_actions=True,
        record_attempt_result="customer_stopped",
    ),
    CustomerIntent.UNCLEAR: IntentAction(
        intent=CustomerIntent.UNCLEAR,
        action_type="send_clarification",
        response_key="unclear",
        requires_payment_link=True,
        record_attempt_result="clarification_sent",
    ),
    CustomerIntent.PAYMENT_RETRY_REQUEST: IntentAction(
        intent=CustomerIntent.PAYMENT_RETRY_REQUEST,
        action_type="send_payment_link",
        response_key="payment_retry",
        requires_payment_link=True,
        record_attempt_result="retry_link_sent",
    ),
}


def get_action_for_intent(intent: CustomerIntent) -> IntentAction:
    """Get the bounded action for a detected intent.

    Every intent has a predefined action. No intent can execute
    arbitrary commands or bypass the action mapping.

    Args:
        intent: The detected customer intent

    Returns:
        IntentAction with the action to execute and response template key
    """
    action = INTENT_ACTIONS.get(intent)
    if action is None:
        # Unknown intent — should never happen with bounded intents
        logger.error("No action mapped for intent: %s", intent)
        return INTENT_ACTIONS[CustomerIntent.UNCLEAR]
    return action


def render_response(
    action: IntentAction,
    customer_name: str = "Customer",
    amount_paise: int = 0,
    payment_link: str = "",
    invoice_link: str = "",
    language: str = "en",
) -> str:
    """Render the response message for a given action in the customer's language.

    Uses language-specific templates from the multilingual service.
    All values come from the database or are predefined templates.

    Args:
        action: The intent action with response key
        customer_name: Customer's name
        amount_paise: Amount in paise
        payment_link: Link to payment page
        invoice_link: Link to invoice
        language: Customer's language code

    Returns:
        Rendered response message in the customer's language
    """
    from app.services.multilingual import get_response_template

    # Get language-specific template
    template = get_response_template(action.response_key, language)

    # Format amount in Indian Rupee style
    rupees = amount_paise // 100
    formatted_amount = f"\u20b9{rupees:,}"

    try:
        return template.format(
            customer_name=customer_name or "Customer",
            amount=formatted_amount,
            payment_link=payment_link,
            invoice_link=invoice_link,
        )
    except KeyError as e:
        logger.error("Template formatting error: %s", e)
        return template
