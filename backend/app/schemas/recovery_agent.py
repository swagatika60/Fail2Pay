"""Schemas for the AI Recovery Specialist structured JSON output.

The Recovery Specialist returns a structured JSON response for real-time
frontend rendering, including intent classification, message text,
suggested replies, and action payload.
"""

from pydantic import BaseModel, Field


class ActionPayload(BaseModel):
    """Action payload for frontend rendering.

    Describes presentational actions (buttons, payment URLs, EMI details).
    NEVER records money — only verified captured payments count as recovered revenue.
    """

    show_payment_card: bool = Field(default=False, description="Whether to show the payment card widget")
    amount: int | None = Field(default=None, description="Amount in paise for the payment card")
    emi_split: int | None = Field(default=None, description="Number of EMI installments if split requested")
    payment_link: str | None = Field(default=None, description="Direct payment URL")
    invoice_id: str | None = Field(default=None, description="Invoice identifier")
    invoice_link: str | None = Field(default=None, description="Secure invoice URL")


class RecoveryAgentResponse(BaseModel):
    """Structured response from the AI Recovery Specialist.

    This is the JSON format returned by the agent for real-time frontend
    rendering. The frontend uses this to render messages, quick reply buttons,
    payment cards, and other interactive widgets.

    Example:
        {
            "thought_process": "Customer wants to pay immediately",
            "intent": "PAY_NOW",
            "message": "Here is your direct link to settle the balance of ₹7,500: https://...",
            "suggested_replies": ["Pay Now ₹7,500", "Split in 2 EMIs", "Talk to Support"],
            "action_payload": {
                "show_payment_card": true,
                "amount": 750000,
                "payment_link": "http://localhost:5173/pay/{case_id}"
            }
        }
    """

    thought_process: str = Field(
        ...,
        description="Brief 1-line reason for routing decision",
        max_length=200,
    )
    intent: str = Field(
        ...,
        description="Detected intent: PAY_NOW | SPLIT_EMI | PAY_LATER | GREETING | SUPPORT | FALLBACK | ...",
    )
    message: str = Field(
        ...,
        description="User-facing message text",
        max_length=2000,
    )
    suggested_replies: list[str] = Field(
        default_factory=list,
        description="List of suggested quick reply labels",
    )
    action_payload: ActionPayload = Field(
        default_factory=ActionPayload,
        description="Action payload for frontend rendering",
    )

    model_config = {"json_schema_extra": {"examples": [
        {
            "thought_process": "Customer wants to pay immediately",
            "intent": "PAY_NOW",
            "message": "Hello Kavitaji! Here is your direct link to settle the balance of ₹7,500: https://pay.fail2pay.com/pay/abc123",
            "suggested_replies": ["Pay Now ₹7,500", "Split in 2 EMIs", "Talk to Support"],
            "action_payload": {
                "show_payment_card": True,
                "amount": 750000,
                "payment_link": "https://pay.fail2pay.com/pay/abc123",
            },
        },
        {
            "thought_process": "Customer wants to split into installments",
            "intent": "SPLIT_EMI",
            "message": "Split Kavitaji: ₹3,750 today and ₹3,750 after 15 days. Activate: https://pay.fail2pay.com/pay/abc123",
            "suggested_replies": ["Activate EMI Plan", "Pay Now ₹3,750", "Talk to Support"],
            "action_payload": {
                "show_payment_card": True,
                "amount": 750000,
                "emi_split": 2,
                "payment_link": "https://pay.fail2pay.com/pay/abc123",
            },
        },
    ]}}
