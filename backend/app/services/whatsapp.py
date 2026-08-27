"""WhatsApp Cloud API Integration.

Handles:
1. Outbound message sending (with policy engine check)
2. Webhook verification (GET)
3. Inbound message processing (POST)
4. Message persistence
5. Delivery/error handling

Every outbound message must pass through the Recovery Policy Engine
before being sent. AI is never allowed to bypass policy restrictions.

Environment variables:
- WHATSAPP_ACCESS_TOKEN
- WHATSAPP_PHONE_NUMBER_ID
- WHATSAPP_VERIFY_TOKEN
"""

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.conversation import (
    create_conversation,
    create_conversation_message,
    get_active_conversations_by_case,
    get_conversation,
)
from app.models.conversation import Conversation, ConversationStatus
from app.schemas.conversation import ConversationCreate
from app.schemas.conversation_message import ConversationMessageCreate
from app.schemas.policy import PolicyInput
from app.services.policy_engine import evaluate_single_action

logger = logging.getLogger(__name__)

# WhatsApp Cloud API base URL
WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"


# --- Webhook Verification ---


def verify_webhook(mode: str, token: str, challenge: str) -> str | None:
    """Verify WhatsApp webhook subscription.

    When Meta sends a verification request, it includes:
    - mode: "subscribe"
    - token: the verify token you configured
    - challenge: a string to echo back

    Returns:
        The challenge string if verification succeeds, None otherwise.
    """
    settings = get_settings()
    expected_token = settings.whatsapp_verify_token

    if not expected_token:
        logger.warning("WhatsApp verify token not configured")
        return None

    if mode == "subscribe" and token == expected_token:
        logger.info("WhatsApp webhook verification successful")
        return challenge

    logger.warning(
        "WhatsApp webhook verification failed: mode=%s, token_match=%s",
        mode,
        token == expected_token,
    )
    return None


# --- Outbound Messaging ---


def send_text_message(
    db: Session,
    phone_number: str,
    message: str,
    recovery_case_id: uuid.UUID,
    language: str = "en",
) -> dict:
    """Send a WhatsApp text message, with policy engine check.

    This is the ONLY way to send WhatsApp messages. It:
    1. Checks the policy engine to ensure SEND_WHATSAPP is allowed
    2. Sends the message via WhatsApp Cloud API
    3. Persists the message in the database
    4. Returns the result

    Args:
        db: Database session
        phone_number: Recipient phone number (with country code)
        message: Text message content
        recovery_case_id: UUID of the recovery case
        language: Language code (default: "en")

    Returns:
        dict with status, message_id, and any error details
    """
    # --- Step 1: Policy Engine Check ---
    # Build policy input from the recovery case
    from app.crud.recovery_case import get_recovery_case

    case = get_recovery_case(db, recovery_case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    # Get customer preferences
    from app.crud.customer import get_customer

    customer = get_customer(db, case.customer_id)
    customer_prefs = None
    if customer:
        # Check if customer has opted out (stored in extra_data or similar)
        # For now, we check basic fields
        customer_prefs = {
            "opted_out": False,
            "opted_out_channels": [],
        }

    # Determine previous response from recovery history
    previous_response = None
    if case.recovery_attempts:
        last_attempt = case.recovery_attempts[-1]
        previous_response = last_attempt.result

    policy_input = PolicyInput(
        amount=case.original_amount,
        risk_level=case.risk_level.upper() if case.risk_level else "MEDIUM",
        attempt_count=case.attempt_count,
        max_attempts=case.max_attempts,
        customer_preferences=customer_prefs,
        previous_response=previous_response,
        payment_status="failed" if case.remaining_amount > 0 else "captured",
        case_status=case.status.value,
        has_phone=bool(phone_number),
        has_email=bool(customer and customer.email),
    )

    policy_result = evaluate_single_action(policy_input, "SEND_WHATSAPP")
    if not policy_result.allowed:
        logger.info(
            "WhatsApp message blocked by policy: %s",
            policy_result.reason,
        )
        return {
            "status": "blocked",
            "reason": policy_result.reason,
            "policy_action": policy_result.action,
        }

    # --- Step 2: Find or create conversation ---
    conversations = get_active_conversations_by_case(db, recovery_case_id)
    whatsapp_conversations = [c for c in conversations if c.channel == "whatsapp"]

    if whatsapp_conversations:
        conversation = whatsapp_conversations[0]
    else:
        conversation = create_conversation(
            db,
            data=ConversationCreate(
                recovery_case_id=recovery_case_id,
                channel="whatsapp",
            ),
        )

    # --- Step 3: Send via WhatsApp Cloud API ---
    settings = get_settings()
    access_token = settings.whatsapp_access_token
    phone_number_id = settings.whatsapp_phone_number_id

    if not access_token or not phone_number_id:
        logger.error("WhatsApp credentials not configured")
        return {
            "status": "error",
            "reason": "whatsapp_not_configured",
            "conversation_id": str(conversation.id),
        }

    api_url = f"{WHATSAPP_API_URL}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": message, "preview_url": False},
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(api_url, json=payload, headers=headers)

        if response.status_code == 200:
            resp_data = response.json()
            external_message_id = resp_data.get("messages", [{}])[0].get("id", "")

            # --- Step 4: Persist outbound message ---
            create_conversation_message(
                db,
                data=ConversationMessageCreate(
                    conversation_id=conversation.id,
                    direction="outbound",
                    content=message,
                    message_type="text",
                    extra_data={
                        "language": language,
                        "external_message_id": external_message_id,
                        "delivery_status": "sent",
                        "phone_number": phone_number,
                        "recovery_case_id": str(recovery_case_id),
                    },
                ),
            )

            # Note: attempt_count is incremented by record_attempt in the orchestrator
            # Do NOT increment here to avoid double-counting

            logger.info(
                "WhatsApp message sent: case=%s, message_id=%s",
                recovery_case_id,
                external_message_id,
            )

            return {
                "status": "sent",
                "message_id": external_message_id,
                "conversation_id": str(conversation.id),
            }
        else:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("error", {}).get("message", response.text)

            # Persist failed outbound message
            create_conversation_message(
                db,
                data=ConversationMessageCreate(
                    conversation_id=conversation.id,
                    direction="outbound",
                    content=message,
                    message_type="text",
                    extra_data={
                        "language": language,
                        "delivery_status": "failed",
                        "error_code": response.status_code,
                        "error_message": error_msg,
                        "phone_number": phone_number,
                        "recovery_case_id": str(recovery_case_id),
                    },
                ),
            )

            logger.error(
                "WhatsApp API error: status=%d, error=%s",
                response.status_code,
                error_msg,
            )

            return {
                "status": "error",
                "reason": f"api_error_{response.status_code}",
                "error": error_msg,
                "conversation_id": str(conversation.id),
            }

    except httpx.TimeoutException:
        logger.error("WhatsApp API timeout for case %s", recovery_case_id)
        return {
            "status": "error",
            "reason": "api_timeout",
            "conversation_id": str(conversation.id),
        }
    except httpx.RequestError as e:
        logger.error("WhatsApp API request error: %s", str(e))
        return {
            "status": "error",
            "reason": "api_request_error",
            "error": str(e),
            "conversation_id": str(conversation.id),
        }


# --- Inbound Message Processing ---


def process_inbound_message(
    db: Session, webhook_payload: dict
) -> dict:
    """Process an incoming WhatsApp webhook message.

    Handles:
    - Text messages from customers (with intent detection + action execution)
    - Delivery status updates
    - Read receipts

    Args:
        db: Database session
        webhook_payload: The full WhatsApp webhook payload

    Returns:
        dict with processing result
    """
    result = {
        "status": "processed",
        "messages_processed": 0,
        "status_updates_processed": 0,
        "message_results": [],
    }

    # WhatsApp webhook can contain multiple entries
    for entry in webhook_payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # Process incoming messages
            messages = value.get("messages", [])
            for msg in messages:
                msg_result = _process_inbound_text(db, msg, value)
                result["messages_processed"] += 1
                if msg_result:
                    result["message_results"].append(msg_result)

            # Process status updates
            statuses = value.get("statuses", [])
            for status in statuses:
                _process_status_update(db, status)
                result["status_updates_processed"] += 1

    return result


def _process_inbound_text(
    db: Session, message: dict, value: dict
) -> dict:
    """Process a single inbound text message with intent detection and action execution.

    Flow:
    1. Save inbound message
    2. Classify intent (AI or rule-based)
    3. Apply policy
    4. Execute bounded action
    5. Send response
    6. Save response
    7. Update conversation state

    Returns:
        dict with processing result including intent and action taken
    """
    from_phone = message.get("from", "")
    message_id = message.get("id", "")
    message_type = message.get("type", "")

    result = {
        "from_phone": from_phone,
        "message_id": message_id,
        "intent": None,
        "action_taken": None,
        "response_sent": False,
    }

    # Extract text content
    content = ""
    if message_type == "text":
        content = message.get("text", {}).get("body", "")
    elif message_type == "button":
        content = message.get("button", {}).get("text", "")
    elif message_type == "interactive":
        # Handle interactive list replies
        interactive = message.get("interactive", {})
        if interactive.get("type") == "list_reply":
            content = interactive.get("list_reply", {}).get("title", "")
        elif interactive.get("type") == "button_reply":
            content = interactive.get("button_reply", {}).get("title", "")

    if not content:
        logger.warning("Empty inbound message from %s", from_phone)
        return result

    # Find the conversation by phone number
    conversation = _find_conversation_by_phone(db, from_phone)
    if not conversation:
        logger.warning(
            "No active conversation found for phone %s — message ignored",
            from_phone,
        )
        return result

    # --- Step 1: Save inbound message ---
    create_conversation_message(
        db,
        data=ConversationMessageCreate(
            conversation_id=conversation.id,
            direction="inbound",
            content=content,
            message_type=message_type,
            extra_data={
                "external_message_id": message_id,
                "from_phone": from_phone,
                "timestamp": message.get("timestamp", ""),
                "language": message.get("text", {}).get("language", {}).get("code", "en"),
            },
        ),
    )

    logger.info(
        "Inbound message saved: conversation=%s, from=%s, type=%s",
        conversation.id,
        from_phone,
        message_type,
    )

    # --- Step 2: Classify intent ---
    from app.schemas.intent import IntentDetectionRequest
    from app.services.intent_detector import detect_intent

    # Build conversation history for context
    from app.crud.conversation import get_messages_by_conversation
    history_msgs = get_messages_by_conversation(db, conversation.id)
    history = [
        {"role": "customer" if m.direction == "inbound" else "agent", "content": m.content}
        for m in history_msgs[-5:]  # Last 5 messages for context
    ]

    intent_request = IntentDetectionRequest(
        message=content,
        language=message.get("text", {}).get("language", {}).get("code", "en"),
        conversation_history=history,
    )
    intent_response = detect_intent(intent_request)
    detected_intent = intent_response.result.intent
    result["intent"] = detected_intent.value
    result["intent_source"] = intent_response.source

    logger.info(
        "Intent detected: %s (confidence=%.2f, source=%s)",
        detected_intent.value,
        intent_response.result.confidence,
        intent_response.source,
    )

    # --- Step 3: Get action for intent ---
    from app.services.intent_action_mapper import get_action_for_intent, render_response
    action = get_action_for_intent(detected_intent)
    result["action_type"] = action.action_type

    # --- Step 4: Get case context for policy check and rendering ---
    from app.crud.recovery_case import get_recovery_case
    case = get_recovery_case(db, conversation.recovery_case_id)
    if not case:
        logger.error("Recovery case not found for conversation %s", conversation.id)
        return result

    from app.crud.customer import get_customer
    customer = get_customer(db, case.customer_id)
    from app.config import get_settings
    settings = get_settings()
    payment_link_base = getattr(settings, "payment_link_base_url", "https://fail2pay.example.com")
    payment_link = f"{payment_link_base}/pay/{case.id}"
    invoice_link = f"{payment_link_base}/invoice/{case.id}"

    # --- Step 5: Check policy ---
    customer_prefs = {"opted_out": False, "opted_out_channels": []}
    previous_response = None
    if case.recovery_attempts:
        last_attempt = case.recovery_attempts[-1]
        previous_response = last_attempt.result

    policy_input = PolicyInput(
        amount=case.original_amount,
        risk_level=case.risk_level.upper() if case.risk_level else "MEDIUM",
        attempt_count=case.attempt_count,
        max_attempts=case.max_attempts,
        customer_preferences=customer_prefs,
        previous_response=previous_response,
        payment_status="failed" if case.remaining_amount > 0 else "captured",
        case_status=case.status.value,
        has_phone=bool(from_phone),
        has_email=bool(customer and customer.email),
    )

    # Check if the action is allowed by policy
    policy_result = evaluate_single_action(policy_input, "SEND_WHATSAPP")
    if not policy_result.allowed:
        logger.info("Action blocked by policy: %s", policy_result.reason)
        result["action_taken"] = "blocked_by_policy"
        result["policy_reason"] = policy_result.reason
        return result

    # --- Step 6: Execute bounded action ---
    _execute_intent_action(
        db=db,
        case=case,
        action=action,
        conversation=conversation,
        customer=customer,
        from_phone=from_phone,
        payment_link=payment_link,
        invoice_link=invoice_link,
    )
    result["action_taken"] = action.action_type

    # --- Step 7: Update case status if needed ---
    if action.update_case_status:
        from app.models.recovery_case import RecoveryStatus
        new_status = RecoveryStatus(action.update_case_status)
        case.status = new_status
        if action.update_case_status == "STOPPED":
            from datetime import datetime, timezone
            case.closed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(case)
        logger.info("Case %s status updated to %s", case.id, action.update_case_status)

    # --- Step 8: Cancel scheduled actions if needed ---
    if action.cancel_scheduled_actions:
        from app.crud.scheduled_action import cancel_pending_actions_for_case
        cancelled = cancel_pending_actions_for_case(db, case.id, reason="customer_requested_stop")
        logger.info("Cancelled %d scheduled actions for case %s", cancelled, case.id)

    # --- Step 9: Send response ---
    response_message = render_response(
        action=action,
        customer_name=customer.name if customer else "Customer",
        amount_paise=case.original_amount,
        payment_link=payment_link,
        invoice_link=invoice_link,
    )

    send_result = _send_reply(
        db=db,
        phone_number=from_phone,
        message=response_message,
        conversation=conversation,
        recovery_case_id=case.id,
    )
    result["response_sent"] = send_result.get("status") == "sent"
    result["response_message_id"] = send_result.get("message_id")

    # --- Step 10: Record attempt ---
    if action.record_attempt_result:
        from app.services.workflow_engine import record_attempt
        record_attempt(
            db=db,
            case_id=case.id,
            channel="whatsapp",
            result=action.record_attempt_result,
            extra_data={
                "detected_intent": detected_intent.value,
                "intent_source": intent_response.source,
                "message_id": message_id,
                "response_message_id": send_result.get("message_id"),
            },
        )

    # --- Step 11: Audit the interaction ---
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="customer_intent",
            entity_id=case.id,
            action="intent_classified",
            new_value={
                "intent": detected_intent.value,
                "confidence": intent_response.result.confidence,
                "source": intent_response.source,
                "action_taken": action.action_type,
                "response_sent": result["response_sent"],
            },
            extra_data={
                "customer_message": content[:500],
                "from_phone": from_phone,
            },
        ),
    )

    logger.info(
        "Inbound processed: case=%s, intent=%s, action=%s, response=%s",
        case.id,
        detected_intent.value,
        action.action_type,
        "sent" if result["response_sent"] else "failed",
    )

    return result


def _execute_intent_action(
    db: Session,
    case,
    action,
    conversation,
    customer,
    from_phone: str,
    payment_link: str,
    invoice_link: str,
) -> None:
    """Execute a bounded intent action.

    This function only does what the action_type specifies.
    No arbitrary commands, no AI-generated code execution.
    """
    # All actions are handled by the response template + state updates
    # This function handles any additional logic needed per action type

    if action.action_type == "check_payment_status":
        # For ALREADY_PAID: we could check Razorpay here
        # For now, just log — the response template handles the message
        logger.info(
            "Customer claims payment made for case %s — flagged for review",
            case.id,
        )

    elif action.action_type == "record_promise":
        # For PROMISE_TO_PAY: already handled by update_case_status
        logger.info(
            "Customer promised to pay for case %s — status updated to PROMISED",
            case.id,
        )

    elif action.action_type == "propose_payment_plan":
        # For PAYMENT_PLAN_REQUEST: log for follow-up
        logger.info(
            "Customer requested payment plan for case %s — flagged for plan proposal",
            case.id,
        )

    elif action.action_type == "stop_recovery":
        # For STOP_REQUEST: already handled by update_case_status + cancel_scheduled_actions
        logger.info(
            "Customer requested stop for case %s — recovery stopped",
            case.id,
        )

    elif action.action_type == "pause_communication":
        # For NEGATIVE: pause but don't stop — merchant can resume
        logger.info(
            "Customer negative response for case %s — communication paused",
            case.id,
        )



def _send_reply(
    db: Session,
    phone_number: str,
    message: str,
    conversation,
    recovery_case_id,
) -> dict:
    """Send a reply message and persist it.

    This is a simplified version of send_text_message for inbound replies.
    It skips the full policy check (already done) and sends directly.
    """
    settings = get_settings()
    access_token = settings.whatsapp_access_token
    phone_number_id = settings.whatsapp_phone_number_id

    if not access_token or not phone_number_id:
        logger.error("WhatsApp credentials not configured")
        return {"status": "error", "reason": "whatsapp_not_configured"}

    api_url = f"{WHATSAPP_API_URL}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": message, "preview_url": False},
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(api_url, json=payload, headers=headers)

        if response.status_code == 200:
            resp_data = response.json()
            external_message_id = resp_data.get("messages", [{}])[0].get("id", "")

            # Persist outbound reply
            create_conversation_message(
                db,
                data=ConversationMessageCreate(
                    conversation_id=conversation.id,
                    direction="outbound",
                    content=message,
                    message_type="text",
                    extra_data={
                        "external_message_id": external_message_id,
                        "delivery_status": "sent",
                        "phone_number": phone_number,
                        "recovery_case_id": str(recovery_case_id),
                        "is_reply": True,
                    },
                ),
            )

            logger.info("Reply sent: case=%s, message_id=%s", recovery_case_id, external_message_id)
            return {"status": "sent", "message_id": external_message_id}
        else:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("error", {}).get("message", response.text)
            logger.error("Reply failed: status=%d, error=%s", response.status_code, error_msg)
            return {"status": "error", "reason": f"api_error_{response.status_code}"}

    except httpx.TimeoutException:
        logger.error("Reply timeout for case %s", recovery_case_id)
        return {"status": "error", "reason": "api_timeout"}
    except httpx.RequestError as e:
        logger.error("Reply request error: %s", str(e))
        return {"status": "error", "reason": "api_request_error"}


def _process_status_update(db: Session, status: dict) -> None:
    """Process a delivery/read status update."""
    from sqlalchemy import select, func
    from app.models.conversation_message import ConversationMessage

    message_id = status.get("id", "")
    status_type = status.get("status", "")  # sent, delivered, read, etc.

    # Find the outbound message by external_message_id using JSON extract
    # Works with both PostgreSQL and SQLite
    message = db.execute(
        select(ConversationMessage).where(
            func.json_extract(ConversationMessage.extra_data, '$.external_message_id') == message_id
        )
    ).scalar_one_or_none()

    if message and message.extra_data:
        # Update delivery status in extra_data
        extra = dict(message.extra_data)
        extra["delivery_status"] = status_type
        extra["status_timestamp"] = status.get("timestamp", "")
        message.extra_data = extra
        db.commit()

        logger.info(
            "Status update: message=%s, status=%s",
            message_id,
            status_type,
        )


def _find_conversation_by_phone(
    db: Session, phone_number: str
) -> Conversation | None:
    """Find an active WhatsApp conversation by phone number.

    Searches through all active conversations and matches by phone number
    stored in the last outbound message's extra_data.
    Uses func.json_extract for SQLite compatibility.
    """
    from sqlalchemy import select, func
    from app.models.conversation_message import ConversationMessage

    # Find conversations with outbound messages to this phone
    messages = db.execute(
        select(ConversationMessage)
        .join(Conversation)
        .where(
            Conversation.channel == "whatsapp",
            Conversation.status == ConversationStatus.ACTIVE,
            ConversationMessage.direction == "outbound",
            func.json_extract(ConversationMessage.extra_data, '$.phone_number') == phone_number,
        )
        .order_by(ConversationMessage.created_at.desc())
        .limit(1)
    ).scalars().all()

    if messages:
        return messages[0].conversation

    return None
