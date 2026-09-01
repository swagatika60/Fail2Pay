"""Tests for the Recovery Workflow Orchestrator and Message Templates.

Covers:
- Full recovery flow: Payment failed → AT_RISK → WhatsApp → schedule
- Message template rendering and selection
- Policy engine integration (blocks when WhatsApp not allowed)
- RecoveryAttempt increments after sending
- Next action scheduling
- Audit trail for every step
- Edge cases: terminal states, no phone, max attempts
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.recovery_attempt import RecoveryAttempt
from app.models.audit_event import AuditEvent
from app.models.scheduled_action import ScheduledAction
from app.services.orchestrator import (
    initiate_recovery,
    process_scheduled_action,
    _evaluate_policy_for_case,
    _send_recovery_message,
    _schedule_next_action,
)
from app.services.message_templates import (
    format_amount,
    get_template,
    get_template_for_attempt,
    render_message,
    TEMPLATES,
)

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


def create_test_customer(db, phone="+919876543210", email="test@example.com") -> Customer:
    customer = Customer(
        external_id=f"cust_{uuid.uuid4().hex[:8]}",
        email=email,
        phone=phone,
        name="Rahul",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def create_test_revenue_event(db, customer) -> RevenueEvent:
    event = RevenueEvent(
        customer_id=customer.id,
        event_type="payment_failed",
        amount=149900,  # ₹1,499
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
        "risk_reason": "Payment failed for active transaction",
        "status": RecoveryStatus.AT_RISK,
        "original_amount": 149900,
        "recovered_amount": 0,
        "remaining_amount": 149900,
        "attempt_count": 0,
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


# --- Message Template Tests ---


class TestFormatAmount:
    def test_format_small_amount(self):
        assert format_amount(149900) == "₹1,499"

    def test_format_large_amount(self):
        assert format_amount(5000000) == "₹50,000"

    def test_format_very_large_amount(self):
        assert format_amount(10000000) == "₹1,00,000"

    def test_format_exact_hundred(self):
        assert format_amount(10000) == "₹100"

    def test_format_small_amount_no_comma(self):
        assert format_amount(9900) == "₹99"


class TestGetTemplate:
    def test_get_initial_template(self):
        template = get_template("initial_payment_failed", "whatsapp")
        assert template is not None
        assert template.stage == "initial_payment_failed"
        assert template.channel == "whatsapp"
        assert "payment" in template.body.lower()

    def test_get_reminder_1_template(self):
        template = get_template("reminder_1", "whatsapp")
        assert template is not None
        assert "reminder" in template.body.lower()

    def test_get_reminder_2_template(self):
        template = get_template("reminder_2", "whatsapp")
        assert template is not None
        assert "noticing" in template.body.lower() or "noticed" in template.body.lower()

    def test_get_final_notice_template(self):
        template = get_template("final_notice", "whatsapp")
        assert template is not None
        assert "final" in template.body.lower()

    def test_unknown_template_returns_none(self):
        template = get_template("unknown_stage", "whatsapp")
        assert template is None

    def test_wrong_channel_returns_none(self):
        template = get_template("initial_payment_failed", "email")
        assert template is None


class TestGetTemplateForAttempt:
    def test_attempt_1_is_initial(self):
        assert get_template_for_attempt(1) == "initial_payment_failed"

    def test_attempt_2_is_reminder_1(self):
        assert get_template_for_attempt(2) == "reminder_1"

    def test_attempt_3_is_reminder_2(self):
        assert get_template_for_attempt(3) == "reminder_2"

    def test_attempt_4_is_final_notice(self):
        assert get_template_for_attempt(4) == "final_notice"

    def test_attempt_5_is_final_notice(self):
        assert get_template_for_attempt(5) == "final_notice"


class TestRenderMessage:
    def test_render_initial_message(self):
        rendered = render_message(
            stage="initial_payment_failed",
            customer_name="Rahul",
            amount_paise=149900,
            payment_link="https://pay.example.com/123",
        )
        assert rendered is not None
        assert "Rahul" in rendered.body
        assert "₹1,499" in rendered.body
        assert "https://pay.example.com/123" in rendered.body
        assert rendered.language == "en"

    def test_render_with_default_name(self):
        rendered = render_message(
            stage="initial_payment_failed",
            customer_name=None,
            amount_paise=149900,
            payment_link="https://pay.example.com/123",
        )
        assert "Customer" in rendered.body

    def test_render_unknown_stage_returns_none(self):
        rendered = render_message(
            stage="unknown_stage",
            customer_name="Rahul",
            amount_paise=149900,
            payment_link="https://pay.example.com/123",
        )
        assert rendered is None

    def test_messages_are_professional(self):
        """All templates should be professional and non-threatening."""
        import re
        threatening_words = ["urgent", "legal", "court", "police", "arrest", "sue", "penalty"]
        for stage, template in TEMPLATES.items():
            for word in threatening_words:
                # Use word boundary to avoid false positives (e.g., "sue" in "issue")
                assert not re.search(r'\b' + word + r'\b', template.body.lower()), (
                    f"Template '{stage}' contains threatening word '{word}'"
                )

    def test_messages_include_payment_link_placeholder(self):
        """All templates should include a payment link placeholder."""
        for stage, template in TEMPLATES.items():
            assert "{payment_link}" in template.body, (
                f"Template '{stage}' missing payment_link placeholder"
            )

    def test_messages_include_amount_placeholder(self):
        """All templates should include an amount placeholder."""
        for stage, template in TEMPLATES.items():
            assert "{amount}" in template.body, (
                f"Template '{stage}' missing amount placeholder"
            )


# --- Orchestrator Tests ---


class TestInitiateRecovery:
    @patch("app.services.whatsapp.send_text_message")
    def test_full_flow_sends_message(self, mock_send):
        """Full flow: case → start → policy → send → record → schedule."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = initiate_recovery(db, case.id)

        assert result["status"] == "initiated"
        assert result["message_sent"] is True
        assert result["message_id"] == "wamid_001"
        assert "start_recovery" in [s["step"] for s in result["steps"]]
        assert "evaluate_policy" in [s["step"] for s in result["steps"]]
        assert "send_whatsapp" in [s["step"] for s in result["steps"]]
        assert "record_attempt" in [s["step"] for s in result["steps"]]
        assert "schedule_next" in [s["step"] for s in result["steps"]]
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_flow_increments_attempt_count(self, mock_send):
        """Attempt count should be incremented after sending."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, attempt_count=0)

        initiate_recovery(db, case.id)

        db.refresh(case)
        assert case.attempt_count >= 1
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_flow_creates_recovery_attempt(self, mock_send):
        """A RecoveryAttempt should be created."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        attempts = db.query(RecoveryAttempt).filter(
            RecoveryAttempt.recovery_case_id == case.id
        ).all()
        assert len(attempts) == 1
        assert attempts[0].channel == "whatsapp"
        assert attempts[0].result == "no_response"
        assert attempts[0].extra_data["message_id"] == "wamid_001"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_flow_creates_scheduled_action(self, mock_send):
        """A ScheduledAction should be created for the next reminder."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        actions = db.query(ScheduledAction).filter(
            ScheduledAction.recovery_case_id == case.id
        ).all()
        assert len(actions) == 1
        assert actions[0].status == "pending"
        assert actions[0].channel == "whatsapp"
        assert actions[0].action_type == "reminder_1"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_flow_creates_audit_event(self, mock_send):
        """An audit event should be created for the initiation."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id
        ).all()
        # At least 2: start_recovery + recovery_initiated
        assert len(audits) >= 2
        actions = {a.action for a in audits}
        assert "status_changed" in actions  # from start_recovery
        assert "recovery_initiated" in actions  # from orchestrator
        db.close()

    def test_initiate_recovery_case_not_found(self):
        """Returns error when case doesn't exist."""
        db = TestSessionLocal()
        result = initiate_recovery(db, uuid.uuid4())
        assert result["status"] == "error"
        assert result["error"] == "case_not_found"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_initiate_recovery_skips_terminal_case(self, mock_send):
        """Terminal cases are skipped."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            status=RecoveryStatus.RECOVERED,
        )

        result = initiate_recovery(db, case.id)
        assert result["status"] == "skipped"
        mock_send.assert_not_called()
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_initiate_recovery_blocked_by_policy(self, mock_send):
        """When policy denies WhatsApp, no message is sent."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        # Max attempts already reached
        case = create_test_recovery_case(
            db, customer, revenue_event,
            attempt_count=5, max_attempts=5,
        )

        result = initiate_recovery(db, case.id)
        assert result["status"] == "action_not_whatsapp"
        mock_send.assert_not_called()
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_initiate_recovery_no_phone(self, mock_send):
        """When customer has no phone, message is not sent."""
        db = TestSessionLocal()
        customer = create_test_customer(db, phone=None)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = initiate_recovery(db, case.id)
        assert result["status"] == "action_not_whatsapp"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_initiate_recovery_max_attempts(self, mock_send):
        """At max attempts, stop recovery is recommended."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            attempt_count=4, max_attempts=5,
        )

        result = initiate_recovery(db, case.id)
        # Should still send (attempt 4/5 is allowed)
        assert result["status"] == "initiated"
        db.close()


# --- Process Scheduled Action Tests ---


class TestProcessScheduledAction:
    @patch("app.services.whatsapp.send_text_message")
    def test_process_reminder_sends_message(self, mock_send):
        """Processing a due reminder action sends a message."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_002",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, attempt_count=1)

        # Create a scheduled action
        from app.crud.scheduled_action import create_scheduled_action
        from app.schemas.scheduled_action import ScheduledActionCreate

        action = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type="reminder_1",
                attempt_number=2,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        )

        result = process_scheduled_action(db, action.id)

        assert result["status"] == "executed"
        assert result["message_id"] == "wamid_002"
        assert result["attempt_number"] >= 2
        db.close()

    def test_process_action_case_not_found(self):
        """Returns error when action's case doesn't exist."""
        db = TestSessionLocal()
        from app.crud.scheduled_action import create_scheduled_action
        from app.schemas.scheduled_action import ScheduledActionCreate

        fake_case_id = uuid.uuid4()
        action = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=fake_case_id,
                action_type="reminder",
                attempt_number=1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc),
            ),
        )

        result = process_scheduled_action(db, action.id)
        assert result["status"] == "error"
        assert result["reason"] == "case_not_found"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_process_action_skips_terminal_case(self, mock_send):
        """Skips processing when case is terminal."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            status=RecoveryStatus.RECOVERED,
        )

        from app.crud.scheduled_action import create_scheduled_action
        from app.schemas.scheduled_action import ScheduledActionCreate

        action = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type="reminder",
                attempt_number=1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc),
            ),
        )

        result = process_scheduled_action(db, action.id)
        assert result["status"] == "skipped"
        assert "terminal" in result["reason"]
        mock_send.assert_not_called()
        db.close()


# --- Schedule Next Action Tests ---


class TestScheduleNextAction:
    @patch("app.services.whatsapp.send_text_message")
    def test_schedule_creates_action_with_delay(self, mock_send):
        """Scheduling creates a pending action with appropriate delay."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, attempt_count=1)

        result = _schedule_next_action(db, case)

        assert result["status"] == "scheduled"
        assert result["delay_hours"] == 8  # reminder_1 delay
        assert result["action_type"] == "reminder_1"  # next after attempt 1
        db.close()

    def test_schedule_no_more_actions_at_max(self):
        """No more actions scheduled when max attempts reached."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            attempt_count=5, max_attempts=5,
        )

        result = _schedule_next_action(db, case)
        assert result["status"] == "no_more_actions"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_schedule_cancels_previous_pending(self, mock_send):
        """Scheduling cancels any existing pending actions first."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, attempt_count=0)

        # Create a pending action
        from app.crud.scheduled_action import create_scheduled_action
        from app.schemas.scheduled_action import ScheduledActionCreate

        old_action = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type="reminder",
                attempt_number=1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=10),
            ),
        )

        # Schedule next action
        _schedule_next_action(db, case)

        # Old action should be cancelled
        from app.crud.scheduled_action import get_scheduled_action
        db.refresh(old_action)
        assert old_action.status == "cancelled"
        db.close()


# --- Full Lifecycle Tests ---


class TestFullLifecycle:
    @patch("app.services.whatsapp.send_text_message")
    def test_multi_attempt_lifecycle(self, mock_send):
        """Test full lifecycle: initiate → reminder → reminder → final."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # First attempt
        result1 = initiate_recovery(db, case.id)
        assert result1["status"] == "initiated"
        assert result1["template_stage"] == "initial_payment_failed"

        # Simulate reminder_1 being processed
        from app.crud.scheduled_action import get_actions_by_case
        actions = get_actions_by_case(db, case.id)
        pending = [a for a in actions if a.status == "pending"]
        assert len(pending) == 1

        # Process the scheduled action
        result2 = process_scheduled_action(db, pending[0].id)
        assert result2["status"] == "executed"
        assert result2["template_stage"] == "reminder_1"

        # Verify attempt count
        db.refresh(case)
        assert case.attempt_count == 2

        # Verify we have 2 recovery attempts
        attempts = db.query(RecoveryAttempt).filter(
            RecoveryAttempt.recovery_case_id == case.id
        ).all()
        assert len(attempts) == 2
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_no_duplicate_messages(self, mock_send):
        """Ensure no duplicate messages are sent for the same stage."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # Initiate
        initiate_recovery(db, case.id)

        # Get the pending action
        from app.crud.scheduled_action import get_actions_by_case
        actions = get_actions_by_case(db, case.id)
        pending = [a for a in actions if a.status == "pending"]

        # Process it
        process_scheduled_action(db, pending[0].id)

        # Verify the first action is now executed (not pending)
        actions2 = get_actions_by_case(db, case.id)
        pending2 = [a for a in actions2 if a.status == "pending"]
        executed = [a for a in actions2 if a.status == "executed"]
        assert len(executed) == 1
        assert executed[0].action_type == "reminder_1"
        # Next action (reminder_2) is now scheduled automatically
        assert len(pending2) == 1
        assert pending2[0].action_type == "reminder_2"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_professional_messages_sent(self, mock_send):
        """Verify that professional (non-threatening) messages are sent."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "wamid_001",
            "conversation_id": str(uuid.uuid4()),
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        # Check the message that was sent
        call_args = mock_send.call_args
        message = call_args.kwargs.get("message") or call_args[1].get("message")
        assert "Rahul" in message
        assert "₹1,499" in message
        assert "http" in message  # Payment link uses configured portal URL
        # Should NOT contain threatening words
        import re
        threatening = ["urgent", "legal", "court", "police", "arrest", "sue"]
        for word in threatening:
            assert not re.search(r'\b' + word + r'\b', message.lower())
        db.close()
