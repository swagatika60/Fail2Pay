"""Tests for inbound WhatsApp conversation flow with intent detection.

Tests the complete flow:
  Customer message → save → classify intent → apply policy → execute action → send response → save response

Covers all 10 intents:
- PAYMENT_LINK_REQUEST → send payment link
- INVOICE_REQUEST → send invoice link
- ALREADY_PAID → check payment status
- PROMISE_TO_PAY → start promise workflow
- PAYMENT_PLAN_REQUEST → start payment-plan workflow
- QUESTION → generate bounded response
- STOP_REQUEST → immediately stop recovery
- NEGATIVE → pause communication
- UNCLEAR → send clarification
- PAYMENT_RETRY_REQUEST → send payment link

All AI and WhatsApp API calls are mocked.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.recovery_attempt import RecoveryAttempt
from app.models.conversation import Conversation, ConversationStatus
from app.models.conversation_message import ConversationMessage
from app.models.audit_event import AuditEvent
from app.models.scheduled_action import ScheduledAction
from app.services.whatsapp import process_inbound_message, _process_inbound_text
from app.services.intent_action_mapper import (
    get_action_for_intent,
    render_response,
    INTENT_ACTIONS,
)
from app.schemas.intent import CustomerIntent

# --- SQLite in-memory DB for tests ---

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    """Create all tables before each test, drop after."""
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# --- Helpers ---


def create_test_customer(db, phone="+919876543210", name="Rahul") -> Customer:
    customer = Customer(
        external_id=f"cust_{uuid.uuid4().hex[:8]}",
        email="rahul@example.com",
        phone=phone,
        name=name,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def create_test_revenue_event(db, customer, amount=149900) -> RevenueEvent:
    event = RevenueEvent(
        customer_id=customer.id,
        event_type="payment_failed",
        amount=amount,
        currency="INR",
        source="razorpay",
        status="failed",
        external_event_id=f"pay_{uuid.uuid4().hex[:8]}",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_test_recovery_case(db, customer, revenue_event, **overrides) -> RecoveryCase:
    defaults = {
        "risk_level": "high",
        "risk_reason": "Payment failed",
        "status": RecoveryStatus.RECOVERY_IN_PROGRESS,
        "original_amount": 149900,
        "recovered_amount": 0,
        "remaining_amount": 149900,
        "attempt_count": 1,
        "max_attempts": 5,
    }
    defaults.update(overrides)
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=revenue_event.id,
        **defaults,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def create_test_conversation(db, case) -> Conversation:
    conversation = Conversation(
        recovery_case_id=case.id,
        channel="whatsapp",
        status=ConversationStatus.ACTIVE,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def create_outbound_message(db, conversation, phone="+919876543210"):
    """Create an outbound message to establish phone-to-conversation mapping."""
    from app.crud.conversation import create_conversation_message
    from app.schemas.conversation_message import ConversationMessageCreate

    create_conversation_message(
        db,
        ConversationMessageCreate(
            conversation_id=conversation.id,
            direction="outbound",
            content="Your payment is pending",
            message_type="text",
            extra_data={"phone_number": phone},
        ),
    )


def make_inbound_payload(phone: str, content: str, msg_id: str = None) -> dict:
    """Create a WhatsApp inbound message payload."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "id": msg_id or f"msg_{uuid.uuid4().hex[:8]}",
                                    "type": "text",
                                    "text": {"body": content},
                                    "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                                }
                            ],
                            "statuses": [],
                        }
                    }
                ]
            }
        ]
    }


def mock_send_success():
    """Mock successful WhatsApp send."""
    return {
        "status": "sent",
        "message_id": f"wamid_{uuid.uuid4().hex[:8]}",
    }


# --- IntentActionMapper Tests ---


class TestIntentActionMapper:
    """Test the intent-to-action mapping."""

    def test_all_intents_have_actions(self):
        """Every CustomerIntent has a mapped action."""
        for intent in CustomerIntent:
            action = get_action_for_intent(intent)
            assert action is not None
            assert action.intent == intent

    def test_payment_link_request_action(self):
        """PAYMENT_LINK_REQUEST sends payment link."""
        action = get_action_for_intent(CustomerIntent.PAYMENT_LINK_REQUEST)
        assert action.action_type == "send_payment_link"
        assert action.requires_payment_link is True
        assert action.record_attempt_result == "payment_link_sent"

    def test_invoice_request_action(self):
        """INVOICE_REQUEST sends invoice."""
        action = get_action_for_intent(CustomerIntent.INVOICE_REQUEST)
        assert action.action_type == "send_invoice"
        assert action.requires_invoice is True

    def test_already_paid_action(self):
        """ALREADY_PAID checks payment status."""
        action = get_action_for_intent(CustomerIntent.ALREADY_PAID)
        assert action.action_type == "check_payment_status"

    def test_promise_to_pay_action(self):
        """PROMISE_TO_PAY records promise and updates status."""
        action = get_action_for_intent(CustomerIntent.PROMISE_TO_PAY)
        assert action.action_type == "record_promise"
        assert action.update_case_status == "PROMISED"
        assert action.record_attempt_result == "promised"

    def test_payment_plan_request_action(self):
        """PAYMENT_PLAN_REQUEST proposes plan."""
        action = get_action_for_intent(CustomerIntent.PAYMENT_PLAN_REQUEST)
        assert action.action_type == "propose_payment_plan"

    def test_question_action(self):
        """QUESTION sends clarification."""
        action = get_action_for_intent(CustomerIntent.QUESTION)
        assert action.action_type == "send_clarification"
        assert action.requires_payment_link is True

    def test_negative_action(self):
        """NEGATIVE pauses communication."""
        action = get_action_for_intent(CustomerIntent.NEGATIVE)
        assert action.action_type == "pause_communication"

    def test_stop_request_action(self):
        """STOP_REQUEST stops recovery and cancels actions."""
        action = get_action_for_intent(CustomerIntent.STOP_REQUEST)
        assert action.action_type == "stop_recovery"
        assert action.update_case_status == "STOPPED"
        assert action.cancel_scheduled_actions is True

    def test_unclear_action(self):
        """UNCLEAR sends safe clarification."""
        action = get_action_for_intent(CustomerIntent.UNCLEAR)
        assert action.action_type == "send_clarification"
        assert action.requires_payment_link is True

    def test_payment_retry_action(self):
        """PAYMENT_RETRY_REQUEST sends payment link."""
        action = get_action_for_intent(CustomerIntent.PAYMENT_RETRY_REQUEST)
        assert action.action_type == "send_payment_link"
        assert action.requires_payment_link is True

    def test_render_response_includes_amount(self):
        """Rendered response includes the payment amount."""
        action = get_action_for_intent(CustomerIntent.PAYMENT_LINK_REQUEST)
        rendered = render_response(
            action=action,
            customer_name="Rahul",
            amount_paise=149900,
            payment_link="https://pay.example.com/123",
        )
        assert "₹1,499" in rendered
        assert "https://pay.example.com/123" in rendered

    def test_render_response_no_threatening_language(self):
        """All rendered responses are professional and non-threatening."""
        import re
        threatening = [
            "urgent", "legal", "court", "police", "arrest", "sue",
            "penalty", "default", "consequences", "seize", "threaten",
        ]
        for intent, action in INTENT_ACTIONS.items():
            rendered = render_response(
                action=action,
                customer_name="Rahul",
                amount_paise=149900,
                payment_link="https://pay.example.com/123",
            )
            for word in threatening:
                assert not re.search(r"\b" + word + r"\b", rendered.lower()), (
                    f"Intent {intent.value} response contains threatening word: {word}"
                )


# --- Full Conversation Flow Tests ---


class TestPaymentLinkRequestFlow:
    """PAYMENT_LINK_REQUEST → send payment link."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_sends_payment_link(self, mock_intent_settings, mock_client_cls):
        """Customer asks for link → payment link is sent."""
        # Mock intent detector to use rule-based (no AI)
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        # Mock WhatsApp API
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_reply_001"}]}
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        with patch("app.services.whatsapp.get_settings") as mock_wa_settings:
            mock_wa_settings.return_value.whatsapp_access_token = "test_token"
            mock_wa_settings.return_value.whatsapp_phone_number_id = "123456"

            payload = make_inbound_payload(customer.phone, "Send me the payment link")
            result = process_inbound_message(db, payload)

        assert result["messages_processed"] == 1
        msg_result = result["message_results"][0]
        assert msg_result["intent"] == "PAYMENT_LINK_REQUEST"
        assert msg_result["action_type"] == "send_payment_link"
        assert msg_result["response_sent"] is True

        # Verify outbound reply was saved
        from app.crud.conversation import get_messages_by_conversation
        messages = get_messages_by_conversation(db, conversation.id)
        outbound = [m for m in messages if m.direction == "outbound" and m.extra_data and m.extra_data.get("is_reply")]
        assert len(outbound) == 1
        assert "pay/" in outbound[0].content  # Payment link in response
        db.close()


class TestPromiseToPayFlow:
    """PROMISE_TO_PAY → record promise, update status."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_records_promise_and_updates_status(self, mock_intent_settings, mock_client_cls):
        """Customer promises to pay → case status becomes PROMISED."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_reply_002"}]}
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        with patch("app.services.whatsapp.get_settings") as mock_wa_settings:
            mock_wa_settings.return_value.whatsapp_access_token = "test_token"
            mock_wa_settings.return_value.whatsapp_phone_number_id = "123456"

            payload = make_inbound_payload(customer.phone, "I'll pay tomorrow, I promise")
            result = process_inbound_message(db, payload)

        msg_result = result["message_results"][0]
        assert msg_result["intent"] == "PROMISE_TO_PAY"
        assert msg_result["action_type"] == "record_promise"

        # Verify case status updated to PROMISED
        db.refresh(case)
        assert case.status == RecoveryStatus.PROMISED
        db.close()


class TestStopRequestFlow:
    """STOP_REQUEST → stop recovery, cancel scheduled actions."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_stops_recovery_and_cancels_actions(self, mock_intent_settings, mock_client_cls):
        """Customer says stop → recovery stopped, pending actions cancelled."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_reply_003"}]}
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        # Create a pending scheduled action
        from app.schemas.scheduled_action import ScheduledActionCreate
        from app.crud.scheduled_action import create_scheduled_action
        scheduled = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type="reminder",
                attempt_number=2,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=4),
            ),
        )

        with patch("app.services.whatsapp.get_settings") as mock_wa_settings:
            mock_wa_settings.return_value.whatsapp_access_token = "test_token"
            mock_wa_settings.return_value.whatsapp_phone_number_id = "123456"

            payload = make_inbound_payload(customer.phone, "STOP contacting me")
            result = process_inbound_message(db, payload)

        msg_result = result["message_results"][0]
        assert msg_result["intent"] == "STOP_REQUEST"
        assert msg_result["action_type"] == "stop_recovery"

        # Verify case stopped
        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        assert case.closed_at is not None

        # Verify scheduled actions cancelled
        db.refresh(scheduled)
        assert scheduled.status == "cancelled"
        assert scheduled.cancellation_reason == "customer_requested_stop"
        db.close()


class TestAlreadyPaidFlow:
    """ALREADY_PAID → check payment status."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_checks_payment_status(self, mock_intent_settings, mock_client_cls):
        """Customer claims paid → response sent acknowledging."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_reply_004"}]}
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        with patch("app.services.whatsapp.get_settings") as mock_wa_settings:
            mock_wa_settings.return_value.whatsapp_access_token = "test_token"
            mock_wa_settings.return_value.whatsapp_phone_number_id = "123456"

            payload = make_inbound_payload(customer.phone, "I already paid yesterday")
            result = process_inbound_message(db, payload)

        msg_result = result["message_results"][0]
        assert msg_result["intent"] == "ALREADY_PAID"
        assert msg_result["action_type"] == "check_payment_status"
        assert msg_result["response_sent"] is True

        # Verify case status NOT changed (just flagged)
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERY_IN_PROGRESS
        db.close()


class TestQuestionFlow:
    """QUESTION → send bounded clarification."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_sends_clarification(self, mock_intent_settings, mock_client_cls):
        """Customer asks question → bounded response with payment info."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_reply_005"}]}
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        with patch("app.services.whatsapp.get_settings") as mock_wa_settings:
            mock_wa_settings.return_value.whatsapp_access_token = "test_token"
            mock_wa_settings.return_value.whatsapp_phone_number_id = "123456"

            payload = make_inbound_payload(customer.phone, "Why was I charged?")
            result = process_inbound_message(db, payload)

        msg_result = result["message_results"][0]
        assert msg_result["intent"] == "QUESTION"

        # Verify response is a contextual clarification with billing escalation
        from app.crud.conversation import get_messages_by_conversation
        messages = get_messages_by_conversation(db, conversation.id)
        reply = [m for m in messages if m.direction == "outbound" and m.extra_data and m.extra_data.get("is_reply")]
        assert len(reply) == 1
        # QUESTION intent now uses the contextual agent engine, which sends a
        # billing-desk escalation message (no payment card / amount shown).
        assert "billing" in reply[0].content.lower() or "follow-up" in reply[0].content.lower()
        db.close()


class TestNegativeFlow:
    """NEGATIVE → pause communication."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_pauses_communication(self, mock_intent_settings, mock_client_cls):
        """Customer is negative → empathetic response, communication paused."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_reply_006"}]}
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        with patch("app.services.whatsapp.get_settings") as mock_wa_settings:
            mock_wa_settings.return_value.whatsapp_access_token = "test_token"
            mock_wa_settings.return_value.whatsapp_phone_number_id = "123456"

            payload = make_inbound_payload(customer.phone, "I'm not paying, this is a scam")
            result = process_inbound_message(db, payload)

        msg_result = result["message_results"][0]
        assert msg_result["intent"] == "NEGATIVE"
        assert msg_result["action_type"] == "pause_communication"

        # Case status NOT changed (paused, not stopped)
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERY_IN_PROGRESS
        db.close()


class TestUnclearFlow:
    """UNCLEAR → send safe clarification."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_sends_clarification(self, mock_intent_settings, mock_client_cls):
        """Unclear message → safe clarification with options."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_reply_007"}]}
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        with patch("app.services.whatsapp.get_settings") as mock_wa_settings:
            mock_wa_settings.return_value.whatsapp_access_token = "test_token"
            mock_wa_settings.return_value.whatsapp_phone_number_id = "123456"

            payload = make_inbound_payload(customer.phone, "asdfghjkl")
            result = process_inbound_message(db, payload)

        msg_result = result["message_results"][0]
        assert msg_result["intent"] == "UNCLEAR"
        assert msg_result["action_type"] == "send_clarification"
        assert msg_result["response_sent"] is True
        db.close()


class TestPaymentPlanFlow:
    """PAYMENT_PLAN_REQUEST → propose payment plan."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_proposes_payment_plan(self, mock_intent_settings, mock_client_cls):
        """Customer requests plan → plan proposal response."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_reply_008"}]}
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        with patch("app.services.whatsapp.get_settings") as mock_wa_settings:
            mock_wa_settings.return_value.whatsapp_access_token = "test_token"
            mock_wa_settings.return_value.whatsapp_phone_number_id = "123456"

            payload = make_inbound_payload(customer.phone, "Can I pay in installments?")
            result = process_inbound_message(db, payload)

        msg_result = result["message_results"][0]
        assert msg_result["intent"] == "PAYMENT_PLAN_REQUEST"
        assert msg_result["action_type"] == "propose_payment_plan"
        assert msg_result["response_sent"] is True
        db.close()


class TestAuditTrail:
    """Every conversation interaction is audited."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_intent_classified_audited(self, mock_intent_settings, mock_client_cls):
        """Intent classification is logged to audit trail."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_reply_009"}]}
        mock_response.text = json.dumps(mock_response.json.return_value)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        with patch("app.services.whatsapp.get_settings") as mock_wa_settings:
            mock_wa_settings.return_value.whatsapp_access_token = "test_token"
            mock_wa_settings.return_value.whatsapp_phone_number_id = "123456"

            payload = make_inbound_payload(customer.phone, "I'll pay tomorrow")
            process_inbound_message(db, payload)

        # Verify audit event
        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "intent_classified",
        ).all()
        assert len(audits) == 1
        assert audits[0].new_value["intent"] == "PROMISE_TO_PAY"
        assert audits[0].new_value["action_taken"] == "record_promise"
        assert audits[0].new_value["response_sent"] is True
        db.close()


class TestNoThreateningResponses:
    """All responses must be professional and non-threatening."""

    @patch("app.services.whatsapp.httpx.Client")
    @patch("app.services.intent_detector.get_settings")
    def test_all_intent_responses_professional(self, mock_intent_settings, mock_client_cls):
        """Every intent produces a professional response."""
        import re

        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        threatening = [
            "urgent", "legal", "court", "police", "arrest", "sue",
            "penalty", "default", "consequences", "seize",
        ]

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        for intent in CustomerIntent:
            action = get_action_for_intent(intent)
            rendered = render_response(
                action=action,
                customer_name="Rahul",
                amount_paise=149900,
                payment_link="https://pay.example.com/123",
            )
            for word in threatening:
                assert not re.search(r"\b" + word + r"\b", rendered.lower()), (
                    f"Intent {intent.value} contains threatening word: {word}"
                )

        db.close()


class TestEdgeCases:
    """Edge cases in the conversation flow."""

    @patch("app.services.intent_detector.get_settings")
    def test_no_conversation_for_unknown_phone(self, mock_intent_settings):
        """Inbound from unknown phone is ignored gracefully."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        db = TestSessionLocal()
        payload = make_inbound_payload("+910000000000", "Hello")
        result = process_inbound_message(db, payload)
        assert result["messages_processed"] == 1
        assert result["message_results"][0]["intent"] is None
        db.close()

    @patch("app.services.intent_detector.get_settings")
    def test_empty_message_handled(self, mock_intent_settings):
        """Empty message is processed without error."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": customer.phone,
                            "id": "empty_001",
                            "type": "text",
                            "text": {"body": ""},
                            "timestamp": "1234567890",
                        }],
                        "statuses": [],
                    }
                }]
            }]
        }
        result = process_inbound_message(db, payload)
        assert result["messages_processed"] == 1
        db.close()

    @patch("app.services.intent_detector.get_settings")
    def test_button_message_classified(self, mock_intent_settings):
        """Button reply messages are classified correctly."""
        mock_intent_settings.return_value.ai_api_key = ""
        mock_intent_settings.return_value.ai_confidence_threshold = 0.6

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)
        create_outbound_message(db, conversation, customer.phone)

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": customer.phone,
                            "id": "btn_001",
                            "type": "button",
                            "button": {"text": "Stop messages"},
                            "timestamp": "1234567890",
                        }],
                        "statuses": [],
                    }
                }]
            }]
        }
        result = process_inbound_message(db, payload)
        msg_result = result["message_results"][0]
        assert msg_result["intent"] == "STOP_REQUEST"
        db.close()
