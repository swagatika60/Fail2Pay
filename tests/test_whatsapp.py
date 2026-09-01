"""Tests for WhatsApp Cloud API integration.

Covers:
- Webhook verification (GET)
- Inbound message processing (POST)
- Outbound message sending (with policy engine check)
- Message persistence
- Delivery/error handling
- Policy engine integration
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.conversation import Conversation, ConversationStatus
from app.models.conversation_message import ConversationMessage
from app.models.scheduled_action import ScheduledAction
from app.services.whatsapp import (
    verify_webhook,
    process_inbound_message,
    send_text_message,
    _find_conversation_by_phone,
)
from app.services import agent_engine

# --- SQLite in-memory DB for tests ---

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    """Create all tables before each test, drop after."""
    import app.models  # noqa: F401 — ensure all models are registered

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# --- Helpers ---


def create_test_customer(db) -> Customer:
    customer = Customer(
        external_id=f"cust_{uuid.uuid4().hex[:8]}",
        email="test@example.com",
        phone="+911234567890",
        name="Test Customer",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def create_test_revenue_event(db, customer: Customer) -> RevenueEvent:
    event = RevenueEvent(
        customer_id=customer.id,
        event_type="payment_failed",
        amount=5000000,
        currency="INR",
        source="razorpay",
        status="failed",
        external_event_id=f"pay_{uuid.uuid4().hex[:8]}",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_test_recovery_case(db, customer, revenue_event) -> RecoveryCase:
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=revenue_event.id,
        risk_level="high",
        risk_reason="Payment failed for active transaction",
        status=RecoveryStatus.RECOVERY_IN_PROGRESS,
        original_amount=5000000,
        recovered_amount=0,
        remaining_amount=5000000,
        attempt_count=0,
        max_attempts=5,
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


@pytest.fixture
def set_db_override():
    """Set the DB dependency override for tests using the TestClient."""
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


# --- Webhook Verification Tests ---


class TestWebhookVerification:
    def test_verify_success(self):
        """Valid mode, token, and challenge returns the challenge."""
        with patch("app.services.whatsapp.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_verify_token = "my_verify_token"
            result = verify_webhook("subscribe", "my_verify_token", "challenge_123")
            assert result == "challenge_123"

    def test_verify_wrong_token(self):
        """Wrong token returns None."""
        with patch("app.services.whatsapp.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_verify_token = "my_verify_token"
            result = verify_webhook("subscribe", "wrong_token", "challenge_123")
            assert result is None

    def test_verify_wrong_mode(self):
        """Wrong mode returns None."""
        with patch("app.services.whatsapp.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_verify_token = "my_verify_token"
            result = verify_webhook("unsubscribe", "my_verify_token", "challenge_123")
            assert result is None

    def test_verify_no_token_configured(self):
        """No token configured returns None."""
        with patch("app.services.whatsapp.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_verify_token = ""
            result = verify_webhook("subscribe", "", "challenge_123")
            assert result is None


class TestWebhookVerifyEndpoint:
    def test_get_returns_challenge(self, set_db_override):
        """GET /api/webhooks/whatsapp with valid params returns challenge."""
        with patch("app.services.whatsapp.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_verify_token = "test_token"
            response = client.get(
                "/api/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "test_token",
                    "hub.challenge": "test_challenge",
                },
            )
            assert response.status_code == 200
            assert response.text == "test_challenge"

    def test_get_returns_403_for_wrong_token(self, set_db_override):
        """GET returns 403 for wrong verify token."""
        with patch("app.services.whatsapp.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_verify_token = "test_token"
            response = client.get(
                "/api/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "wrong_token",
                    "hub.challenge": "test_challenge",
                },
            )
            assert response.status_code == 403

    def test_get_returns_400_for_missing_params(self, set_db_override):
        """GET returns 400 for missing query parameters."""
        response = client.get("/api/webhooks/whatsapp")
        assert response.status_code == 400


# --- Inbound Message Processing Tests ---


class TestInboundMessageProcessing:
    def test_process_inbound_text_message(self):
        """Inbound text message is saved to database."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)

        # Create outbound message to establish phone-to-conversation mapping
        from app.schemas.conversation_message import ConversationMessageCreate

        outbound = ConversationMessageCreate(
            conversation_id=conversation.id,
            direction="outbound",
            content="Please pay your outstanding amount",
            message_type="text",
            extra_data={
                "phone_number": "+919876543210",
                "external_message_id": "outbound_001",
                "delivery_status": "sent",
            },
        )
        from app.crud.conversation import create_conversation_message
        create_conversation_message(db, outbound)

        # Process inbound message
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "+919876543210",
                                        "id": "inbound_001",
                                        "type": "text",
                                        "text": {"body": "I will pay tomorrow"},
                                        "timestamp": "1234567890",
                                    }
                                ],
                                "statuses": [],
                            }
                        }
                    ]
                }
            ]
        }

        result = process_inbound_message(db, payload)

        assert result["messages_processed"] == 1
        assert result["status_updates_processed"] == 0

        # Verify message was saved
        from app.crud.conversation import get_messages_by_conversation
        messages = get_messages_by_conversation(db, conversation.id)
        inbound_msgs = [m for m in messages if m.direction == "inbound"]
        assert len(inbound_msgs) == 1
        assert inbound_msgs[0].content == "I will pay tomorrow"
        assert inbound_msgs[0].extra_data["external_message_id"] == "inbound_001"
        db.close()

    def test_process_inbound_promise_to_pay_creates_real_state(self):
        """Real-webhook PROMISE_TO_PAY drives the full event-driven recovery:
        persists a Promise, queues the promise reminder touchpoint, flips the
        case to PROMISED, and sends a contextual + persisted agent reply."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)

        from app.schemas.conversation_message import ConversationMessageCreate
        from app.crud.conversation import create_conversation_message

        create_conversation_message(
            db,
            ConversationMessageCreate(
                conversation_id=conversation.id,
                direction="outbound",
                content="Please pay your outstanding amount",
                message_type="text",
                extra_data={
                    "phone_number": "+919876543210",
                    "external_message_id": "outbound_041",
                    "delivery_status": "sent",
                },
            ),
        )

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "+919876543210",
                                        "id": "inbound_promise_041",
                                        "type": "text",
                                        "text": {
                                            "body": "Kal payment kar dunga",
                                            "language": {"code": "hi"},
                                        },
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

        result = process_inbound_message(db, payload)
        assert result["messages_processed"] == 1
        assert result["message_results"][0]["intent"] == "PROMISE_TO_PAY"

        db.expire_all()
        db.refresh(case)

        # 1) A real tagged Promise record is persisted and the case is PROMISED.
        from app.crud.promise import get_active_promise_for_case
        from app.models.recovery_case import RecoveryStatus
        promise = get_active_promise_for_case(db, case.id)
        assert promise is not None
        assert promise.status == "ACTIVE"
        assert case.status == RecoveryStatus.PROMISED

        # 2) A real promise-reminder touchpoint is queued for the scheduler.
        from app.models.scheduled_action import ScheduledAction
        from sqlalchemy import select
        queued = db.execute(
            select(ScheduledAction).where(ScheduledAction.recovery_case_id == case.id)
        ).scalars().all()
        assert len(queued) >= 1
        assert any(
            "promise" in (a.action_type or "").lower()
            or "promise" in str((a.extra_data or {}).get("reason", "")).lower()
            for a in queued
        )

        # 3) A contextual, persisted outbound agent reply was generated.
        from app.crud.conversation import get_messages_by_conversation
        messages = get_messages_by_conversation(db, conversation.id)
        outbound = [m for m in messages if m.direction == "outbound"]
        assert any("pay" in (m.content or "").lower() or "kal" in (m.content or "").lower() for m in outbound)
        db.close()

    def test_process_inbound_button_message(self):
        """Inbound button reply is saved correctly."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)

        from app.schemas.conversation_message import ConversationMessageCreate
        from app.crud.conversation import create_conversation_message

        create_conversation_message(
            db,
            ConversationMessageCreate(
                conversation_id=conversation.id,
                direction="outbound",
                content="Will you pay?",
                message_type="text",
                extra_data={"phone_number": "+919876543210"},
            ),
        )

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "+919876543210",
                                        "id": "btn_001",
                                        "type": "button",
                                        "button": {"text": "Yes, I will pay"},
                                        "timestamp": "1234567890",
                                    }
                                ],
                                "statuses": [],
                            }
                        }
                    ]
                }
            ]
        }

        result = process_inbound_message(db, payload)
        assert result["messages_processed"] == 1

        from app.crud.conversation import get_messages_by_conversation
        messages = get_messages_by_conversation(db, conversation.id)
        inbound = [m for m in messages if m.direction == "inbound"]
        assert len(inbound) == 1
        assert inbound[0].content == "Yes, I will pay"
        db.close()

    def test_process_status_update(self):
        """Delivery status update is persisted."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)

        from app.schemas.conversation_message import ConversationMessageCreate
        from app.crud.conversation import create_conversation_message

        msg = create_conversation_message(
            db,
            ConversationMessageCreate(
                conversation_id=conversation.id,
                direction="outbound",
                content="Payment reminder",
                message_type="text",
                extra_data={
                    "external_message_id": "outbound_msg_001",
                    "delivery_status": "sent",
                },
            ),
        )

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [],
                                "statuses": [
                                    {
                                        "id": "outbound_msg_001",
                                        "status": "delivered",
                                        "timestamp": "1234567890",
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

        result = process_inbound_message(db, payload)
        assert result["status_updates_processed"] == 1

        # Verify status was updated
        db.refresh(msg)
        assert msg.extra_data["delivery_status"] == "delivered"
        db.close()

    def test_process_empty_payload(self):
        """Empty webhook payload is processed without error."""
        db = TestSessionLocal()
        result = process_inbound_message(db, {"entry": []})
        assert result["messages_processed"] == 0
        assert result["status_updates_processed"] == 0
        db.close()

    def test_process_inbound_unknown_phone(self):
        """Inbound message from unknown phone is ignored."""
        db = TestSessionLocal()
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "+910000000000",
                                        "id": "unknown_001",
                                        "type": "text",
                                        "text": {"body": "Hello"},
                                        "timestamp": "1234567890",
                                    }
                                ],
                                "statuses": [],
                            }
                        }
                    ]
                }
            ]
        }

        result = process_inbound_message(db, payload)
        assert result["messages_processed"] == 1  # processed but ignored
        db.close()


class TestAutonomousAgentEngine:
    """The restored autonomous conversation engine (agent_engine.handle_incoming_message).

    Covers the key customer intents end to end: immediate pay, 2x split plan,
    promise-to-pay with a real ScheduledAction, and Hinglish language detection.
    """

    def _new_case(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        return db, case

    def test_immediate_pay_request_builds_pay_card(self):
        """Pay-now intent → rich payment card + dynamic payment link."""
        db, case = self._new_case()
        turn = agent_engine.handle_incoming_message(
            db=db,
            case_id=case.id,
            message_text="I'll pay right now, send the link",
            detected_intent="PAYMENT_LINK_REQUEST",
            create_plan=False,
            create_promise=False,
        )
        assert turn["intent"] == "PAYMENT_LINK_REQUEST"
        assert turn["action"] == "send_payment_link"
        payload = turn["agent_payload"]
        assert payload["payment_card"] is not None
        assert payload["payment_card"]["url"]
        assert "pay/" in turn["pay_now_url"]
        assert payload["text"]
        db.close()

    def test_split_request_builds_2x_breakdown(self):
        """Installment request → 2-part split with a real Part 1 amount."""
        db, case = self._new_case()
        turn = agent_engine.handle_incoming_message(
            db=db,
            case_id=case.id,
            message_text="Can I pay in installments?",
            detected_intent="PAYMENT_PLAN_REQUEST",
            create_plan=False,
            create_promise=False,
        )
        assert turn["split"] is not None
        assert len(turn["split"]["amounts"]) == 2
        payload = turn["agent_payload"]
        assert payload["payment_card"] is not None
        # Part 1 (due today) is a real, positive partial amount — never full, never 0.
        assert 0 < payload["payment_card"]["amount"] < case.remaining_amount
        db.close()

    def test_promise_to_pay_creates_scheduled_action(self):
        """Promise-to-pay → parses time + persists a ScheduledAction reminder."""
        db, case = self._new_case()
        turn = agent_engine.handle_incoming_message(
            db=db,
            case_id=case.id,
            message_text="I will pay tomorrow at 5 PM",
            detected_intent="PROMISE_TO_PAY",
            create_promise=True,
        )
        promise = turn["promise_scheduled"]
        assert promise is not None
        assert promise["action_id"] is not None
        row = db.query(ScheduledAction).filter(
            ScheduledAction.id == uuid.UUID(str(promise["action_id"]))
        ).first()
        assert row is not None
        assert row.action_type == "reminder"
        db.close()

    def test_promise_without_side_effect_is_non_persisting(self):
        """A caller that already recorded the promise skips duplicate ScheduledAction."""
        db, case = self._new_case()
        turn = agent_engine.handle_incoming_message(
            db=db,
            case_id=case.id,
            message_text="I will pay tomorrow at 5 PM",
            detected_intent="PROMISE_TO_PAY",
            create_promise=False,
        )
        assert turn["promise_scheduled"]["action_id"] is None
        assert db.query(ScheduledAction).count() == 0
        db.close()

    def test_process_turn_persists_and_returns_payload(self):
        """process_turn writes the agent reply bubble (with payload) to the thread."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)

        turn = agent_engine.process_turn(
            db=db,
            case_id=case.id,
            message_text="Can I pay in installments?",
            detected_intent="PAYMENT_PLAN_REQUEST",
            create_plan=False,
            persist=True,
        )
        assert turn["reply_text"]
        assert turn["conversation_id"] == str(conversation.id)

        from app.crud.conversation import get_messages_by_conversation

        outbound = [
            m
            for m in get_messages_by_conversation(db, conversation.id)
            if m.direction == "outbound"
        ]
        assert len(outbound) == 1
        assert outbound[0].extra_data.get("agent_payload")
        db.close()

    def test_hinglish_message_detected(self):
        """Hinglish customer tone → agent replies in Romanized Hinglish."""
        db, case = self._new_case()
        turn = agent_engine.handle_incoming_message(
            db=db,
            case_id=case.id,
            message_text="EMI option hai, mujhe chahiye bhaijaan",
            detected_intent="PAYMENT_PLAN_REQUEST",
            create_plan=False,
        )
        assert turn["language"] == "hi-en"
        assert "ji" in turn["text"]  # respectful Hinglish honorific
        db.close()


class TestWebhookPostEndpoint:
    def test_post_processes_inbound(self, set_db_override):
        """POST /api/webhooks/whatsapp processes inbound messages."""
        response = client.post(
            "/api/webhooks/whatsapp",
            json={"entry": []},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["result"]["messages_processed"] == 0

    def test_post_returns_400_for_invalid_json(self, set_db_override):
        """POST returns 400 for invalid JSON."""
        response = client.post(
            "/api/webhooks/whatsapp",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400


# --- Outbound Message Tests ---


class TestSendTextMessage:
    @patch("app.services.whatsapp.httpx.Client")
    def test_send_message_success(self, mock_client_cls):
        """Successful message send persists message and increments attempt count."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messages": [{"id": "wamid_outbound_001"}]
        }
        mock_response.text = json.dumps(mock_response.json.return_value)

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        with patch("app.services.whatsapp.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_access_token = "test_token"
            mock_settings.return_value.whatsapp_phone_number_id = "123456"

            result = send_text_message(
                db,
                phone_number="+919876543210",
                message="Please pay ₹50,000",
                recovery_case_id=case.id,
            )

        assert result["status"] == "sent"
        assert result["message_id"] == "wamid_outbound_001"
        assert "conversation_id" in result

        # Verify message was persisted
        from app.crud.conversation import get_messages_by_conversation, get_conversations_by_case
        conversations = get_conversations_by_case(db, case.id)
        assert len(conversations) == 1

        messages = get_messages_by_conversation(db, conversations[0].id)
        outbound = [m for m in messages if m.direction == "outbound"]
        assert len(outbound) == 1
        assert outbound[0].content == "Please pay ₹50,000"
        assert outbound[0].extra_data["delivery_status"] == "sent"

        # Verify attempt count NOT incremented by send_text_message
        # (orchestrator's record_attempt handles incrementing)
        db.refresh(case)
        assert case.attempt_count == 0
        db.close()

    @patch("app.services.whatsapp.httpx.Client")
    def test_send_message_api_error(self, mock_client_cls):
        """API error response is handled gracefully."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": {"message": "Invalid phone number"}
        }
        mock_response.text = json.dumps(mock_response.json.return_value)

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        with patch("app.services.whatsapp.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_access_token = "test_token"
            mock_settings.return_value.whatsapp_phone_number_id = "123456"

            result = send_text_message(
                db,
                phone_number="+910000000000",
                message="Test",
                recovery_case_id=case.id,
            )

        assert result["status"] == "error"
        assert "api_error" in result["reason"]
        db.close()

    @patch("app.services.whatsapp.httpx.Client")
    def test_send_message_timeout(self, mock_client_cls):
        """Timeout is handled gracefully."""
        import httpx

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        with patch("app.services.whatsapp.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_access_token = "test_token"
            mock_settings.return_value.whatsapp_phone_number_id = "123456"

            result = send_text_message(
                db,
                phone_number="+919876543210",
                message="Test",
                recovery_case_id=case.id,
            )

        assert result["status"] == "error"
        assert result["reason"] == "api_timeout"
        db.close()

    def test_send_message_blocked_by_policy(self):
        """Message is blocked when policy engine denies SEND_WHATSAPP."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            # Max attempts already reached
        )
        case.attempt_count = 5
        case.max_attempts = 5
        db.commit()

        result = send_text_message(
            db,
            phone_number="+919876543210",
            message="Test",
            recovery_case_id=case.id,
        )

        assert result["status"] == "blocked"
        assert "maximum" in result["reason"].lower() or "maximum" in result.get("stop_condition", "").lower()
        db.close()

    def test_send_message_case_not_found(self):
        """Returns error when case doesn't exist."""
        db = TestSessionLocal()
        result = send_text_message(
            db,
            phone_number="+919876543210",
            message="Test",
            recovery_case_id=uuid.uuid4(),
        )
        # Hard stop intercepts before the case-not-found check
        assert result["status"] in ("error", "blocked")
        assert "case_not_found" in result.get("reason", "").lower() or "not found" in result.get("reason", "").lower()
        db.close()

    @patch("app.services.whatsapp.get_settings")
    def test_send_message_not_configured(self, mock_settings):
        """Returns error when WhatsApp credentials are not configured."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        mock_settings.return_value.whatsapp_access_token = ""
        mock_settings.return_value.whatsapp_phone_number_id = ""

        result = send_text_message(
            db,
            phone_number="+919876543210",
            message="Test",
            recovery_case_id=case.id,
        )

        assert result["status"] == "error"
        assert result["reason"] == "whatsapp_not_configured"
        db.close()


# --- Conversation Lookup Tests ---


class TestFindConversationByPhone:
    def test_find_existing_conversation(self):
        """Finds conversation by phone number in outbound messages."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)

        from app.schemas.conversation_message import ConversationMessageCreate
        from app.crud.conversation import create_conversation_message

        create_conversation_message(
            db,
            ConversationMessageCreate(
                conversation_id=conversation.id,
                direction="outbound",
                content="Test",
                message_type="text",
                extra_data={"phone_number": "+919876543210"},
            ),
        )

        found = _find_conversation_by_phone(db, "+919876543210")
        assert found is not None
        assert found.id == conversation.id
        db.close()

    def test_no_conversation_for_unknown_phone(self):
        """Returns None for unknown phone number."""
        db = TestSessionLocal()
        found = _find_conversation_by_phone(db, "+910000000000")
        assert found is None
        db.close()


# --- Message Persistence Tests ---


class TestMessagePersistence:
    def test_message_has_required_fields(self):
        """Persisted message contains all required fields."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)

        from app.schemas.conversation_message import ConversationMessageCreate
        from app.crud.conversation import create_conversation_message

        msg = create_conversation_message(
            db,
            ConversationMessageCreate(
                conversation_id=conversation.id,
                direction="outbound",
                content="Payment reminder",
                message_type="text",
                extra_data={
                    "language": "en",
                    "external_message_id": "wamid_001",
                    "delivery_status": "sent",
                },
            ),
        )

        assert msg.conversation_id == conversation.id
        assert msg.direction == "outbound"
        assert msg.content == "Payment reminder"
        assert msg.message_type == "text"
        assert msg.extra_data["language"] == "en"
        assert msg.extra_data["external_message_id"] == "wamid_001"
        assert msg.extra_data["delivery_status"] == "sent"
        assert msg.created_at is not None
        db.close()

    def test_inbound_and_outbound_messages_coexist(self):
        """Both inbound and outbound messages are stored in the same conversation."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        conversation = create_test_conversation(db, case)

        from app.schemas.conversation_message import ConversationMessageCreate
        from app.crud.conversation import create_conversation_message, get_messages_by_conversation

        # Outbound
        create_conversation_message(
            db,
            ConversationMessageCreate(
                conversation_id=conversation.id,
                direction="outbound",
                content="Please pay",
                message_type="text",
            ),
        )

        # Inbound
        create_conversation_message(
            db,
            ConversationMessageCreate(
                conversation_id=conversation.id,
                direction="inbound",
                content="I will pay tomorrow",
                message_type="text",
            ),
        )

        messages = get_messages_by_conversation(db, conversation.id)
        assert len(messages) == 2
        directions = {m.direction for m in messages}
        assert directions == {"outbound", "inbound"}
        db.close()
