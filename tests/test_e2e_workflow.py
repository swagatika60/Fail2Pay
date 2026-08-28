"""End-to-end recovery workflow tests.

Wires together the complete system exactly as it works in production:

    Razorpay webhook (payment.failed)
        → RevenueEvent
        → Revenue Risk Engine (deterministic risk_level / risk_reason)
        → merchant RecoverySetting (max_attempts, reminder sequence)
        → RecoveryCase → policy engine → deterministic workflow
        → WhatsApp outbound message → scheduled reminders
    Customer replies (WhatsApp inbound)
        → intent detection (AI w/ rule-based fallback)
        → bounded intent action → REAL resources (promise / payment plan / invoice)
    Payment arrives (payment.captured webhook)
        → Verified Payment row (revenue map ground truth) → RECOVERED → HARD STOP

Webhook service functions are called directly (not through the HTTP route) so
this module never touches the global ``app.dependency_overrides`` and stays
isolated from other test modules in the same process.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.webhook_handler import (
    process_payment_captured,
    process_payment_failed,
)

# --- SQLite in-memory DB (own engine — no global dependency overrides) ---
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    import app.models  # noqa: F401 — register all models

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# --- Model imports (used inside tests) ---

from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.payment import Payment
from app.models.payment_plan import PaymentPlan
from app.models.installment import Installment, InstallmentStatus
from app.models.audit_event import AuditEvent


# --- Helpers ---


def make_webhook_payload(
    event_type: str, payment_data: dict = None, event_id: str = "evt_e2e_default"
) -> dict:
    """Razorpay webhook payload helper (as parsed from the HTTP body)."""
    default_payment = {
        "id": "pay_e2e_fail",
        "order_id": "order_e2e_fail",
        "amount": 12000000,  # ₹1.2 lakh → MEDIUM risk per the risk engine
        "currency": "INR",
        "status": "failed" if "failed" in event_type else "captured",
        "method": "upi",
        "email": "test@example.com",
        "contact": "+911234567890",
        "customer_id": "cust_e2e_001",
        "failure_reason": "Payment failed by bank",
        "failure_code": "PAYMENT_FAILED",
    }
    if payment_data:
        default_payment.update(payment_data)

    return {
        "id": event_id,
        "event": event_type,
        "payload": {"payment": {"entity": default_payment}},
    }


def make_inbound_payload(phone: str, content: str, msg_id: str = None) -> dict:
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
                                    "timestamp": str(
                                        int(datetime.now(timezone.utc).timestamp())
                                    ),
                                }
                            ],
                            "statuses": [],
                        }
                    }
                ]
            }
        ]
    }


def post_failed_webhook(db, **overrides) -> dict:
    """Invoke payment.failed handling with overrides applied."""
    payload = make_webhook_payload(
        "payment.failed",
        {"id": "pay_e2e_fail", "order_id": "order_e2e_fail"} | overrides,
        event_id=overrides.pop("event_id", "evt_e2e_fail_001"),
    )
    return process_payment_failed(db, payload)


def post_captured_webhook(db, **overrides) -> dict:
    """Invoke payment.captured handling with overrides applied."""
    payload = make_webhook_payload(
        "payment.captured",
        {"id": "pay_e2e_cap", "order_id": "order_e2e_cap"} | overrides,
        event_id=overrides.pop("event_id", "evt_e2e_cap_001"),
    )
    return process_payment_captured(db, payload)


def create_conversation_for_case(db, case, phone: str):
    """Create a WhatsApp conversation + outbound message mapping the phone."""
    from app.models.conversation import Conversation, ConversationStatus
    from app.crud.conversation import create_conversation_message
    from app.schemas.conversation_message import ConversationMessageCreate

    conversation = Conversation(
        recovery_case_id=case.id,
        channel="whatsapp",
        status=ConversationStatus.ACTIVE,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    create_conversation_message(
        db,
        ConversationMessageCreate(
            conversation_id=conversation.id,
            direction="outbound",
            content=f"Payment reminder for {case.original_amount}",
            message_type="text",
            extra_data={"phone_number": phone},
        ),
    )
    return conversation


def run_inbound_message(db, phone, content, msg_id=None) -> dict:
    """Run an inbound WhatsApp message with mocked AI + outbound transport."""
    from app.services.whatsapp import process_inbound_message

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"messages": [{"id": "wamid_e2e_reply"}]}
    mock_response.text = '{"messages": [{"id": "wamid_e2e_reply"}]}'
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response

    # Provide fake WhatsApp credentials so _send_reply() passes the
    # credentials check and reaches the mocked httpx.Client below.
    fake_settings = MagicMock()
    fake_settings.ai_api_key = ""
    fake_settings.ai_confidence_threshold = 0.6
    fake_settings.whatsapp_access_token = "fake_token_e2e"
    fake_settings.whatsapp_phone_number_id = "fake_phone_id_e2e"

    with patch("app.services.intent_detector.get_settings", return_value=fake_settings), patch(
        "app.services.whatsapp.get_settings", return_value=fake_settings
    ), patch("app.services.whatsapp.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value = mock_client

        payload = make_inbound_payload(phone, content, msg_id)
        result = process_inbound_message(db, payload)

    assert result["messages_processed"] == 1
    return result["message_results"][0]


def get_pending_actions(db, case_id):
    from app.crud.scheduled_action import get_pending_actions_for_case

    return get_pending_actions_for_case(db, case_id)


def get_outbound_replies(db, conversation_id):
    from app.crud.conversation import get_messages_by_conversation

    messages = get_messages_by_conversation(db, conversation_id)
    return [
        m
        for m in messages
        if m.direction == "outbound" and m.extra_data and m.extra_data.get("is_reply")
    ]


def create_case_with_plan(db) -> dict:
    """Create a case with an ACTIVE multi-installment payment plan.

    Returns dict with scalar ids + installments (reads ids BEFORE any commit).
    """
    from app.models.customer import Customer
    from app.models.revenue_event import RevenueEvent
    from app.services.payment_plan import (
        accept_payment_plan,
        create_payment_plan_for_case,
    )

    customer = Customer(
        external_id="cust_e2e_plan",
        email="plan@example.com",
        phone="+919999999999",
        name="Plan Customer",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    revenue_event = RevenueEvent(
        customer_id=customer.id,
        event_type="payment_failed",
        amount=2500000,
        currency="INR",
        source="razorpay",
        status="failed",
        external_event_id="pay_e2e_plan_fail",
    )
    db.add(revenue_event)
    db.commit()
    db.refresh(revenue_event)

    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=revenue_event.id,
        risk_level="MEDIUM",
        risk_reason="Medium-value payment failure",
        status=RecoveryStatus.RECOVERY_IN_PROGRESS,
        original_amount=2500000,
        recovered_amount=0,
        remaining_amount=2500000,
        attempt_count=1,
        max_attempts=5,
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    plan_result = create_payment_plan_for_case(
        db, case.id, installment_amount=250000, frequency="weekly"
    )
    assert plan_result["status"] == "created"
    plan_id = plan_result["plan_id"]
    accept_payment_plan(db, case.id, uuid.UUID(plan_id))

    plan = db.query(PaymentPlan).filter(PaymentPlan.id == uuid.UUID(plan_id)).first()
    installments = (
        db.execute(
            select(Installment).where(Installment.payment_plan_id == plan.id)
        )
        .scalars()
        .all()
    )
    db.refresh(case)
    return {
        "customer_id": customer.id,
        "case_id": case.id,
        "plan_id": plan.id,
        "installments": installments,
        "revenue_event_id": revenue_event.id,
    }


def mock_send_ok(mock_send):
    mock_send.return_value = {
        "status": "sent",
        "message_id": f"wamid_{uuid.uuid4().hex[:8]}",
        "conversation_id": str(uuid.uuid4()),
    }


# --- Scenario 1: pays immediately ---


class TestPaysImmediately:
    @patch("app.services.whatsapp.send_text_message")
    def test_recovered_and_hard_stop_on_capture(self, mock_send):
        """Failed payment → recovery started → customer pays immediately."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()

        result = post_failed_webhook(db)
        assert result["status"] == "processed"
        assert result["case_id"]
        assert result["recovery_initiated"] is True
        case_id = result["case_id"]

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(case_id)
        ).first()
        assert case is not None
        # Risk engine wired: MEDIUM for ₹1.2 lakh, not the old hardcoded "high"
        assert case.risk_level == "MEDIUM"
        assert case.max_attempts == 5  # from merchant RecoverySetting
        assert case.attempt_count == 1
        assert len(get_pending_actions(db, case.id)) == 1

        # Risk engine decision logged to audit
        risk_audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "risk_assessed",
        ).all()
        assert len(risk_audits) == 1
        assert risk_audits[0].new_value["risk_level"] == "MEDIUM"
        case_id = case.id

        # --- Customer pays immediately ---
        captured = post_captured_webhook(db, event_id="evt_e2e_cap_001", id="pay_e2e_fail")
        assert captured["status"] == "processed"

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == case_id
        ).first()
        assert case.status == RecoveryStatus.RECOVERED
        assert case.remaining_amount == 0
        assert case.recovered_amount == 12000000

        # Verified Payment row (revenue map ground truth)
        payments = db.query(Payment).filter(
            Payment.recovery_case_id == case_id
        ).all()
        assert len(payments) == 1
        assert payments[0].status == "captured"
        assert payments[0].amount == 12000000
        assert payments[0].razorpay_payment_id == "pay_e2e_fail"

        # HARD STOP: all future scheduled actions cancelled
        assert get_pending_actions(db, case_id) == []
        db.close()


# --- Scenario 2: pays after a reminder ---


class TestPaysAfterReminder:
    @patch("app.services.whatsapp.send_text_message")
    def test_recovers_on_capture_after_one_reminder(self, mock_send):
        """Failed payment → reminder sent → customer pays → RECOVERED."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()

        result = post_failed_webhook(db, event_id="evt_e2e_fail_002")
        case_id = result["case_id"]
        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(case_id)
        ).first()

        # Fire the scheduled reminder now (would have run at T+delay)
        from app.services.orchestrator import process_scheduled_action

        pending = get_pending_actions(db, case.id)
        assert len(pending) == 1
        pending[0].scheduled_for = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

        reminder_result = process_scheduled_action(db, pending[0].id)
        assert reminder_result["status"] == "executed"
        db.refresh(case)
        assert case.attempt_count == 2

        # Customer pays after the reminder
        captured = post_captured_webhook(db, event_id="evt_e2e_cap_002", id="pay_e2e_fail")
        assert captured["status"] == "processed"

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(case_id)
        ).first()
        assert case.status == RecoveryStatus.RECOVERED
        assert case.remaining_amount == 0
        assert get_pending_actions(db, case.id) == []
        db.close()


# --- Scenario 3: requests invoice ---


class TestInvoiceRequest:
    @patch("app.services.whatsapp.send_text_message")
    def test_creates_real_invoice_and_sends_secure_link(self, mock_send):
        """INVOICE_REQUEST → real invoice row + secure URL in the reply."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()
        result = post_failed_webhook(db, event_id="evt_e2e_fail_003")

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(result["case_id"])
        ).first()
        conversation = create_conversation_for_case(db, case, "+911234567890")

        msg_result = run_inbound_message(
            db, "+911234567890", "Please send me the invoice please"
        )
        assert msg_result["intent"] == "INVOICE_REQUEST"
        assert msg_result["action_type"] == "send_invoice"
        assert msg_result["response_sent"] is True

        # A real Invoice was created with a secure token
        from app.models.invoice import Invoice

        invoices = db.query(Invoice).filter(
            Invoice.recovery_case_id == case.id
        ).all()
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.secure_token and invoice.issued_at

        # The reply carries the secure access link, not the placeholder
        outbound = get_outbound_replies(db, conversation.id)
        assert len(outbound) == 1
        assert invoice.secure_token in outbound[0].content
        assert "api/invoices/access/" in outbound[0].content
        db.close()


# --- Scenario 4: requests payment link ---


class TestPaymentLinkRequest:
    @patch("app.services.whatsapp.send_text_message")
    def test_sends_payment_link_in_reply(self, mock_send):
        """PAYMENT_LINK_REQUEST → payment link in the reply."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()
        result = post_failed_webhook(db, event_id="evt_e2e_fail_004")

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(result["case_id"])
        ).first()
        conversation = create_conversation_for_case(db, case, "+911234567890")

        msg_result = run_inbound_message(db, "+911234567890", "Send me the payment link")
        assert msg_result["intent"] == "PAYMENT_LINK_REQUEST"
        assert msg_result["action_type"] == "send_payment_link"
        assert msg_result["response_sent"] is True

        outbound = get_outbound_replies(db, conversation.id)
        assert len(outbound) == 1
        assert "/pay/" in outbound[0].content
        assert str(case.id) in outbound[0].content
        db.close()


# --- Scenario 5: promises to pay ---


class TestPromiseToPay:
    @patch("app.services.whatsapp.send_text_message")
    def test_creates_promise_record_and_promised_status(self, mock_send):
        """PROMISE_TO_PAY → real Promise record created."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()
        result = post_failed_webhook(db, event_id="evt_e2e_fail_005")

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(result["case_id"])
        ).first()
        create_conversation_for_case(db, case, "+911234567890")

        msg_result = run_inbound_message(db, "+911234567890", "I'll pay tomorrow, I promise")
        assert msg_result["intent"] == "PROMISE_TO_PAY"
        assert msg_result["action_type"] == "record_promise"
        assert msg_result["response_sent"] is True

        # A real Promise row exists
        from app.models.promise import Promise

        promises = db.query(Promise).filter(
            Promise.recovery_case_id == case.id
        ).all()
        assert len(promises) == 1
        assert promises[0].amount_promised == 12000000

        db.refresh(case)
        assert case.status == RecoveryStatus.PROMISED
        db.close()


# --- Scenario 6: requests weekly payments ---


class TestPaymentPlanRequest:
    @patch("app.services.whatsapp.send_text_message")
    def test_creates_and_accepts_weekly_plan(self, mock_send):
        """PAYMENT_PLAN_REQUEST → active weekly plan with real installments."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()
        result = post_failed_webhook(db, event_id="evt_e2e_fail_006")

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(result["case_id"])
        ).first()
        create_conversation_for_case(db, case, "+911234567890")

        msg_result = run_inbound_message(
            db, "+911234567890", "I want to pay in installments"
        )
        assert msg_result["intent"] == "PAYMENT_PLAN_REQUEST"
        assert msg_result["action_type"] == "propose_payment_plan"
        assert msg_result["response_sent"] is True

        # A real plan was created AND accepted (ACTIVE)
        plans = db.query(PaymentPlan).filter(
            PaymentPlan.recovery_case_id == case.id
        ).all()
        assert len(plans) == 1
        plan = plans[0]
        assert plan.status == "ACTIVE"
        assert plan.frequency == "weekly"

        # Installments recorded against the plan
        installments = db.execute(
            select(Installment).where(Installment.payment_plan_id == plan.id)
        ).scalars().all()
        assert len(installments) == plan.number_of_installments
        assert 2 <= len(installments) <= 12
        assert installments[0].installment_number == 1

        db.refresh(case)
        assert case.status == RecoveryStatus.PROMISED

        # Acceptance logged to the audit trail
        accepted = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "payment_plan_accepted",
        ).all()
        assert len(accepted) == 1
        db.close()


# --- Scenario 7: never responds → hard stop ---


class TestNoResponse:
    @patch("app.services.whatsapp.send_text_message")
    def test_stop_sending_after_max_attempts(self, mock_send):
        """No response → deterministic hard stop once max attempts are spent."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()
        result = post_failed_webhook(db, event_id="evt_e2e_fail_007")

        from app.services.orchestrator import process_scheduled_action

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(result["case_id"])
        ).first()
        max_attempts = case.max_attempts

        # Send every reminder until there is nothing left to schedule
        last_next_action = None
        for _ in range(max_attempts - case.attempt_count):
            pending = get_pending_actions(db, case.id)
            assert pending, "a reminder should be scheduled while attempts remain"
            first = pending[0]
            first.scheduled_for = datetime.now(timezone.utc) - timedelta(hours=1)
            db.commit()
            outcome = process_scheduled_action(db, first.id)
            assert outcome["status"] == "executed"
            last_next_action = outcome.get("next_action")

        db.refresh(case)
        assert case.attempt_count == max_attempts
        # No more messages will ever be sent
        assert get_pending_actions(db, case.id) == []
        assert last_next_action is not None
        assert last_next_action["status"] == "no_more_actions"
        db.close()


# --- Scenario 8: says stop ---


class TestStopRequest:
    @patch("app.services.whatsapp.send_text_message")
    def test_stops_case_and_cancels_future_actions(self, mock_send):
        """STOP_REQUEST → STOPPED + every pending action cancelled."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()
        result = post_failed_webhook(db, event_id="evt_e2e_fail_008")

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(result["case_id"])
        ).first()
        assert len(get_pending_actions(db, case.id)) == 1
        create_conversation_for_case(db, case, "+911234567890")

        msg_result = run_inbound_message(db, "+911234567890", "Please stop messaging me")
        assert msg_result["intent"] == "STOP_REQUEST"
        assert msg_result["action_type"] == "stop_recovery"
        assert msg_result["response_sent"] is True

        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        assert case.closed_at is not None
        assert get_pending_actions(db, case.id) == []

        # The customer stop was audited (attempt recording is skipped on terminal)
        stops = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "intent_classified",
        ).all()
        assert any(
            ev.new_value.get("action_taken") == "stop_recovery"
            and ev.new_value.get("intent") == "STOP_REQUEST"
            for ev in stops
        )
        db.close()


# --- Scenario 9: negative response ---


class TestNegativeResponse:
    @patch("app.services.whatsapp.send_text_message")
    def test_pauses_but_does_not_stop(self, mock_send):
        """NEGATIVE → communication paused, case not stopped."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()
        result = post_failed_webhook(db, event_id="evt_e2e_fail_009")

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(result["case_id"])
        ).first()
        conversation = create_conversation_for_case(db, case, "+911234567890")

        msg_result = run_inbound_message(db, "+911234567890", "I will not pay")
        assert msg_result["intent"] == "NEGATIVE"
        assert msg_result["action_type"] == "pause_communication"
        assert msg_result["response_sent"] is True

        db.refresh(case)
        assert case.status != RecoveryStatus.STOPPED
        assert len(get_outbound_replies(db, conversation.id)) == 1

        from app.models.recovery_attempt import RecoveryAttempt

        attempts = db.query(RecoveryAttempt).filter(
            RecoveryAttempt.recovery_case_id == case.id
        ).all()
        assert any(a.result == "negative_response" for a in attempts)
        db.close()


# --- Scenario 10: WhatsApp API down ---


class TestWhatsAppFailure:
    @patch("app.services.whatsapp.send_text_message")
    def test_case_tracked_but_no_messages_scheduled(self, mock_send):
        """WhatsApp API failure → case exists, nothing scheduled."""
        mock_send.return_value = {
            "status": "error",
            "reason": "whatsapp_api_error",
            "error": "Authentication Error",
        }

        db = TestSessionLocal()
        result = post_failed_webhook(db, event_id="evt_e2e_fail_010")
        assert result["status"] == "processed"
        assert result["recovery_initiated"] is False

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(result["case_id"])
        ).first()
        assert case is not None
        assert get_pending_actions(db, case.id) == []
        db.close()


# --- Scenario 11: AI down → rule-based fallback ---


class TestAiFailure:
    @patch("app.services.whatsapp.send_text_message")
    def test_intent_still_detected_via_rules(self, mock_send):
        """AI unavailable → deterministic rule-based intent classification."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()
        result = post_failed_webhook(db, event_id="evt_e2e_fail_011")

        case = db.query(RecoveryCase).filter(
            RecoveryCase.id == uuid.UUID(result["case_id"])
        ).first()
        create_conversation_for_case(db, case, "+911234567890")

        from app.services.whatsapp import process_inbound_message

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid_e2e_ai_fail"}]}
        mock_response.text = '{"messages": [{"id": "wamid_e2e_ai_fail"}]}'
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response

        fake_wa_settings = MagicMock()
        fake_wa_settings.ai_api_key = "sk-dead-key"
        fake_wa_settings.ai_confidence_threshold = 0.6
        fake_wa_settings.whatsapp_access_token = "fake_token_e2e"
        fake_wa_settings.whatsapp_phone_number_id = "fake_phone_id_e2e"

        with patch(
            "app.services.intent_detector.OpenAIProvider",
            side_effect=Exception("AI is down"),
        ), patch("app.services.intent_detector.get_settings", return_value=fake_wa_settings), patch(
            "app.services.whatsapp.get_settings", return_value=fake_wa_settings
        ), patch(
            "app.services.whatsapp.httpx.Client"
        ) as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value = mock_client

            payload = make_inbound_payload("+911234567890", "I'll pay tomorrow")
            ai_fail_result = process_inbound_message(db, payload)

        msg_result = ai_fail_result["message_results"][0]
        assert msg_result["intent"] == "PROMISE_TO_PAY"
        assert msg_result["intent_source"] == "rule_based_fallback"
        assert msg_result["response_sent"] is True
        db.close()


# --- Scenario 12: duplicate Razorpay webhooks ---


class TestDuplicateWebhook:
    @patch("app.services.whatsapp.send_text_message")
    def test_duplicate_events_are_skipped(self, mock_send):
        """Same event_id twice → second processed as duplicate skip."""
        mock_send_ok(mock_send)
        db = TestSessionLocal()

        first = post_failed_webhook(db, event_id="evt_e2e_dup_001")
        assert first["status"] == "processed"
        second = post_failed_webhook(db, event_id="evt_e2e_dup_001")
        assert second["status"] == "skipped"
        assert second["reason"] == "duplicate_webhook"

        cases = db.query(RecoveryCase).all()
        assert len(cases) == 1  # no second case for same event

        captured = post_captured_webhook(db, event_id="evt_e2e_dup_002", id="pay_e2e_fail")
        assert captured["status"] == "processed"
        dup_captured = post_captured_webhook(
            db, event_id="evt_e2e_dup_002", id="pay_e2e_fail"
        )
        assert dup_captured["status"] == "skipped"
        assert dup_captured["reason"] == "duplicate_webhook"

        from app.models.webhook_event import WebhookEvent

        stored = db.query(WebhookEvent).count()
        assert stored == 2
        db.close()


# --- Scenario 13: installment payment succeeds ---


class TestInstallmentCaptured:
    @patch("app.services.whatsapp.send_text_message")
    def test_installment_paid_and_verified_payment_recorded(self, mock_send):
        """payment.captured for an installment → installment PAID + Payment row."""
        db = TestSessionLocal()

        setup = create_case_with_plan(db)
        case_id = setup["case_id"]
        plan_id = setup["plan_id"]
        installment_id = setup["installments"][0].id
        setup["installments"][0].razorpay_payment_id = "pay_e2e_inst_001"
        db.commit()

        captured = post_captured_webhook(
            db,
            event_id="evt_e2e_inst_cap_001",
            id="pay_e2e_inst_001",
            order_id="order_e2e_inst_001",
            amount=250000,
            contact="+919999999999",
            customer_id="cust_e2e_plan",
        )
        assert captured["status"] == "processed"
        assert captured["installment_payment"] is True

        installment = db.query(Installment).filter(
            Installment.id == installment_id
        ).first()
        assert installment.status == InstallmentStatus.PAID.value

        plan = db.query(PaymentPlan).filter(PaymentPlan.id == plan_id).first()
        assert plan.installments_paid == 1
        assert plan.status == "ACTIVE"

        # Verified money recorded for the revenue map
        payments = db.query(Payment).filter(
            Payment.recovery_case_id == case_id
        ).all()
        assert len(payments) == 1
        assert payments[0].razorpay_payment_id == "pay_e2e_inst_001"
        assert payments[0].status == "captured"
        assert payments[0].amount == 250000
        db.close()


# --- Scenario 14: installment payment fails ---


class TestInstallmentFailed:
    @patch("app.services.whatsapp.send_text_message")
    def test_installment_failed_no_new_case(self, mock_send):
        """payment.failed for an installment → installment FAILED, no new case."""
        db = TestSessionLocal()

        setup = create_case_with_plan(db)
        case_id = setup["case_id"]
        plan_id = setup["plan_id"]
        second_id = setup["installments"][1].id
        setup["installments"][1].razorpay_order_id = "order_e2e_inst_002"
        db.commit()

        failed = post_failed_webhook(
            db,
            event_id="evt_e2e_inst_fail_001",
            id="pay_e2e_inst_002",
            order_id="order_e2e_inst_002",
            amount=250000,
            contact="+919999999999",
            customer_id="cust_e2e_plan",
            failure_reason="Insufficient funds",
        )
        assert failed["status"] == "processed"
        assert failed["installment_failure"] is True

        second = db.query(Installment).filter(
            Installment.id == second_id
        ).first()
        assert second.status == InstallmentStatus.FAILED.value

        plan = db.query(PaymentPlan).filter(PaymentPlan.id == plan_id).first()
        assert plan.installments_failed == 1

        # No NEW recovery case was spawned for the failed installment
        cases = db.query(RecoveryCase).all()
        assert len(cases) == 1
        assert cases[0].id == case_id
        db.close()