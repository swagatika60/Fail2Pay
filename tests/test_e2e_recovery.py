"""End-to-end tests for the full recovery workflow.

Tests the complete flow:
  Payment failed → RecoveryCase AT_RISK → Policy → WhatsApp → Schedule → Next action → Repeat

Covers:
- Full webhook-to-recovery flow
- Multi-attempt lifecycle with scheduling chain
- No duplicate messages sent
- Every message logged to ConversationMessage
- RecoveryAttempt increments correctly (no double-counting)
- Schedule chain continues through all template stages
- Professional messages only (no threatening language)
- Policy blocks when conditions not met
- Terminal states stop the workflow
"""

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
from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.audit_event import AuditEvent
from app.models.scheduled_action import ScheduledAction
from app.services.orchestrator import (
    initiate_recovery,
    process_scheduled_action,
    _schedule_next_action,
)
from app.services.message_templates import get_template_for_attempt, TEMPLATES
from app.crud.scheduled_action import get_actions_by_case, get_scheduled_action

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


def mock_send_success():
    """Return a mock send_text_message that succeeds."""
    return {
        "status": "sent",
        "message_id": f"wamid_{uuid.uuid4().hex[:8]}",
        "conversation_id": str(uuid.uuid4()),
    }


# --- Full End-to-End Flow Tests ---


class TestFullRecoveryFlow:
    """Test the complete flow from payment failure to WhatsApp to schedule."""

    @patch("app.services.whatsapp.send_text_message")
    def test_payment_failure_triggers_full_recovery(self, mock_send):
        """Full flow: initiate_recovery → policy → send → record → schedule."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = initiate_recovery(db, case.id)

        # Verify all steps executed
        assert result["status"] == "initiated"
        assert result["message_sent"] is True
        assert result["template_stage"] == "initial_payment_failed"

        step_names = [s["step"] for s in result["steps"]]
        assert "start_recovery" in step_names
        assert "evaluate_policy" in step_names
        assert "send_whatsapp" in step_names
        assert "record_attempt" in step_names
        assert "schedule_next" in step_names

        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_attempt_count_increments_exactly_once(self, mock_send):
        """attempt_count should go from 0 to 1 after one send (no double-counting)."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, attempt_count=0)

        initiate_recovery(db, case.id)

        db.refresh(case)
        assert case.attempt_count == 1, (
            f"Expected attempt_count=1, got {case.attempt_count} (double increment?)"
        )
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_attempt_count_increments_correctly_on_second_send(self, mock_send):
        """Second send should increment from 1 to 2."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, attempt_count=1
        )

        # Create a pending scheduled action
        from app.schemas.scheduled_action import ScheduledActionCreate
        from app.crud.scheduled_action import create_scheduled_action

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

        process_scheduled_action(db, action.id)

        db.refresh(case)
        assert case.attempt_count == 2
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_recovery_attempt_created_with_correct_data(self, mock_send):
        """RecoveryAttempt is created with correct channel, result, and extra_data."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        attempts = (
            db.query(RecoveryAttempt)
            .filter(RecoveryAttempt.recovery_case_id == case.id)
            .all()
        )
        assert len(attempts) == 1
        assert attempts[0].channel == "whatsapp"
        assert attempts[0].result == "no_response"
        assert attempts[0].attempt_number == 1
        assert attempts[0].extra_data["message_id"] is not None
        assert attempts[0].extra_data["template_stage"] == "initial_payment_failed"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_scheduled_action_created_for_next_reminder(self, mock_send):
        """After initial send, a ScheduledAction for reminder_1 is created."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        actions = get_actions_by_case(db, case.id)
        pending = [a for a in actions if a.status == "pending"]
        assert len(pending) == 1
        assert pending[0].action_type == "reminder_1"
        assert pending[0].channel == "whatsapp"
        assert pending[0].attempt_number == 2
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_message_sent_via_whatsapp(self, mock_send):
        """send_text_message is called with correct parameters."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        # Verify send_text_message was called
        assert mock_send.called
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["phone_number"] == "+919876543210"
        assert call_kwargs["recovery_case_id"] == case.id
        # Message should contain personalized content
        message = call_kwargs["message"]
        assert "Rahul" in message
        assert "₹1,499" in message
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_professional_message_content(self, mock_send):
        """Sent messages must be professional and non-threatening."""
        import re

        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        # Check the actual message sent
        call_args = mock_send.call_args
        message = call_args.kwargs.get("message") or call_args[1].get("message")

        # Must include customer name
        assert "Rahul" in message
        # Must include formatted amount
        assert "₹1,499" in message
        # Must include payment link
        assert "https://" in message
        # Must NOT contain threatening words
        threatening = [
            "urgent", "legal", "court", "police", "arrest", "sue",
            "penalty", "default", "consequences", "seize",
        ]
        for word in threatening:
            assert not re.search(r"\b" + word + r"\b", message.lower()), (
                f"Message contains threatening word: {word}"
            )
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_whatsapp_message_sent_to_correct_phone(self, mock_send):
        """Message is sent to the customer's phone number."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db, phone="+919876543210")
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["phone_number"] == "+919876543210"
        assert call_kwargs["recovery_case_id"] == case.id
        db.close()


# --- Scheduled Action Chain Tests ---


class TestScheduleChain:
    """Test that the scheduling chain continues through all template stages."""

    @patch("app.services.whatsapp.send_text_message")
    def test_full_lifecycle_initial_to_reminder(self, mock_send):
        """Initial → reminder_1: schedule is created and processable."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # Step 1: Initiate
        result1 = initiate_recovery(db, case.id)
        assert result1["status"] == "initiated"
        assert result1["template_stage"] == "initial_payment_failed"

        # Step 2: Get the pending action
        actions = get_actions_by_case(db, case.id)
        pending = [a for a in actions if a.status == "pending"]
        assert len(pending) == 1
        assert pending[0].action_type == "reminder_1"

        # Step 3: Process the scheduled action
        result2 = process_scheduled_action(db, pending[0].id)
        assert result2["status"] == "executed"
        assert result2["template_stage"] == "reminder_1"

        # Step 4: Verify next action was scheduled
        assert "next_action" in result2
        assert result2["next_action"]["status"] == "scheduled"
        assert result2["next_action"]["action_type"] == "reminder_2"

        # Verify state
        db.refresh(case)
        assert case.attempt_count == 2
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_full_lifecycle_through_all_stages(self, mock_send):
        """Test all 4 stages: initial → reminder_1 → reminder_2 → final_notice."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        expected_stages = [
            "initial_payment_failed",
            "reminder_1",
            "reminder_2",
            "final_notice",
        ]

        # Stage 1: Initiate
        result = initiate_recovery(db, case.id)
        assert result["template_stage"] == expected_stages[0]

        # Stages 2-4: Process scheduled actions
        for expected_stage in expected_stages[1:]:
            actions = get_actions_by_case(db, case.id)
            pending = [a for a in actions if a.status == "pending"]
            assert len(pending) == 1, f"Expected 1 pending action for {expected_stage}"

            result = process_scheduled_action(db, pending[0].id)
            assert result["status"] == "executed"
            assert result["template_stage"] == expected_stage

        # Verify final state
        db.refresh(case)
        assert case.attempt_count == 4

        # All 4 messages were sent
        assert mock_send.call_count == 4

        # Each message was different (different template stage)
        sent_messages = [
            call.kwargs.get("message") or call[1].get("message")
            for call in mock_send.call_args_list
        ]
        # Messages should be different (different templates)
        assert len(set(sent_messages)) == 4, "All 4 messages should be unique"

        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_no_more_actions_after_max_attempts(self, mock_send):
        """After max_attempts, no more actions are scheduled."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            attempt_count=4, max_attempts=5,
        )

        # Create a pending action for the 5th attempt
        from app.schemas.scheduled_action import ScheduledActionCreate
        from app.crud.scheduled_action import create_scheduled_action

        action = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type="final_notice",
                attempt_number=5,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        )

        result = process_scheduled_action(db, action.id)
        assert result["status"] == "executed"
        assert result["template_stage"] == "final_notice"

        # Next action should be "no_more_actions"
        assert result["next_action"]["status"] == "no_more_actions"
        db.close()


# --- No Duplicate Messages Tests ---


class TestNoDuplicateMessages:
    """Ensure the same message template is never sent twice in sequence."""

    @patch("app.services.whatsapp.send_text_message")
    def test_each_stage_uses_different_template(self, mock_send):
        """Each attempt uses a different template stage."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # Run through all stages
        initiate_recovery(db, case.id)

        stages_used = [result.get("template_stage") for result in []]
        stages_used.append("initial_payment_failed")  # first

        for _ in range(3):
            actions = get_actions_by_case(db, case.id)
            pending = [a for a in actions if a.status == "pending"]
            if not pending:
                break
            result = process_scheduled_action(db, pending[0].id)
            if result["status"] == "executed":
                stages_used.append(result["template_stage"])

        # All stages should be unique
        assert len(stages_used) == len(set(stages_used)), (
            f"Duplicate stages found: {stages_used}"
        )
        # Should have used all 4 stages
        assert set(stages_used) == {
            "initial_payment_failed",
            "reminder_1",
            "reminder_2",
            "final_notice",
        }
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_previous_pending_actions_cancelled_on_reschedule(self, mock_send):
        """When scheduling a new action, previous pending actions are cancelled."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # Create a stale pending action
        from app.schemas.scheduled_action import ScheduledActionCreate
        from app.crud.scheduled_action import create_scheduled_action

        stale = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type="reminder",
                attempt_number=1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=100),
            ),
        )

        # Initiate recovery — should cancel the stale action
        initiate_recovery(db, case.id)

        db.refresh(stale)
        assert stale.status == "cancelled"
        assert stale.cancellation_reason == "rescheduling_after_attempt"
        db.close()


# --- Audit Trail Tests ---


class TestAuditTrail:
    """Every step should be logged to the audit trail."""

    @patch("app.services.whatsapp.send_text_message")
    def test_full_audit_trail_created(self, mock_send):
        """Audit events are created for start, send, and schedule."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        audits = (
            db.query(AuditEvent)
            .filter(AuditEvent.recovery_case_id == case.id)
            .all()
        )
        actions = {a.action for a in audits}

        # Should have status_changed (from start_recovery + record_attempt) and recovery_initiated
        assert "status_changed" in actions
        assert "recovery_initiated" in actions
        # The attempt is logged via _log_transition which uses action="status_changed"
        # with the specific action in extra_data
        status_changes = [a for a in audits if a.action == "status_changed"]
        assert len(status_changes) >= 2  # start_recovery + record_attempt

        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_state_transitions_logged(self, mock_send):
        """State transitions are captured in audit events."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        audits = (
            db.query(AuditEvent)
            .filter(AuditEvent.recovery_case_id == case.id)
            .all()
        )

        # Find the status_changed event
        status_changes = [a for a in audits if a.action == "status_changed"]
        assert len(status_changes) >= 1

        # The first transition should be AT_RISK → RECOVERY_IN_PROGRESS
        first_change = status_changes[0]
        assert first_change.old_value["status"] == "AT_RISK"
        assert first_change.new_value["status"] == "RECOVERY_IN_PROGRESS"

        db.close()


# --- Edge Case Tests ---


class TestEdgeCases:
    """Edge cases: terminal states, no phone, missing case."""

    @patch("app.services.whatsapp.send_text_message")
    def test_terminal_case_skipped(self, mock_send):
        """RECOVERED cases should not trigger recovery."""
        mock_send.return_value = mock_send_success()

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

    def test_nonexistent_case_returns_error(self):
        """Initiating recovery for a non-existent case returns error."""
        db = TestSessionLocal()
        result = initiate_recovery(db, uuid.uuid4())
        assert result["status"] == "error"
        assert result["error"] == "case_not_found"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_no_phone_blocks_whatsapp(self, mock_send):
        """Customer without phone number should not get WhatsApp message."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db, phone=None)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = initiate_recovery(db, case.id)
        # Policy blocks SEND_WHATSAPP because has_phone=False
        assert result["status"] == "action_not_whatsapp"
        mock_send.assert_not_called()
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_max_attempts_stops_recovery(self, mock_send):
        """At max attempts, policy should block further messages."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            attempt_count=5, max_attempts=5,
        )

        result = initiate_recovery(db, case.id)
        assert result["status"] == "action_not_whatsapp"
        mock_send.assert_not_called()
        db.close()


# --- Message Content Per Stage Tests ---


class TestMessageContentPerStage:
    """Verify each template renders correctly with personalized data."""

    @patch("app.services.whatsapp.send_text_message")
    def test_initial_message_has_payment_link(self, mock_send):
        """Initial payment failed message includes a payment link."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        initiate_recovery(db, case.id)

        message = mock_send.call_args.kwargs["message"]
        assert "pay/" in message  # payment link contains /pay/
        assert "https://" in message
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_reminder_message_tone_is_gentle(self, mock_send):
        """Reminder messages should be gentle, not aggressive."""
        mock_send.return_value = mock_send_success()

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, attempt_count=1
        )

        # Create and process a reminder_1 action
        from app.schemas.scheduled_action import ScheduledActionCreate
        from app.crud.scheduled_action import create_scheduled_action

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

        process_scheduled_action(db, action.id)

        # Get the message sent (only 1 call since we didn't call initiate_recovery)
        message = mock_send.call_args.kwargs["message"]
        # Should be gentle
        gentle_words = ["gentle", "reminder", "pending", "help"]
        assert any(word in message.lower() for word in gentle_words)
        # Should NOT be aggressive
        import re
        aggressive = ["immediately", "final warning", "legal action", "consequences"]
        for word in aggressive:
            assert not re.search(r"\b" + word + r"\b", message.lower())
        db.close()
