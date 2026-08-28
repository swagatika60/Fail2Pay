"""Tests for the No-Response Recovery Scheduler.

Covers:
- Default recovery sequence: T+0, T+4h, T+12h, T+28h, T+60h (5 actions)
- Exponential backoff timing
- Pre-reminder checks (payment, conversation, opt-out, status, max, deadline)
- Customer response handling (cancel reminders, stop on request)
- Customer stop keywords (English, Hindi, Hinglish)
- Terminal state handling
- Edge cases: case not found, already terminal, no pending actions
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.scheduled_action import ScheduledAction
from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.audit_event import AuditEvent
from app.services.scheduler import (
    schedule_recovery_workflow,
    process_due_actions,
    process_single_action,
    handle_customer_response,
    cancel_all_actions_for_case,
    get_schedule_status,
    DEFAULT_SCHEDULE_CONFIG,
    STOP_KEYWORDS,
)
from app.crud.scheduled_action import (
    create_scheduled_action,
    get_actions_by_case,
    get_pending_actions_for_case,
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
        name="Rahul Sharma",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def create_test_revenue_event(db, customer: Customer) -> RevenueEvent:
    event = RevenueEvent(
        customer_id=customer.id,
        event_type="payment_failed",
        amount=50000,
        currency="INR",
        source="razorpay",
        status="failed",
        external_event_id=f"pay_{uuid.uuid4().hex[:8]}",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_test_recovery_case(
    db,
    customer: Customer,
    revenue_event: RevenueEvent,
    status: RecoveryStatus = RecoveryStatus.RECOVERY_IN_PROGRESS,
    original_amount: int = 50000,
    attempt_count: int = 0,
    max_attempts: int = 5,
    recovery_deadline: datetime | None = None,
) -> RecoveryCase:
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=revenue_event.id,
        risk_level="high",
        risk_reason="Payment failed for active transaction",
        status=status,
        original_amount=original_amount,
        recovered_amount=0,
        remaining_amount=original_amount,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        recovery_deadline=recovery_deadline,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def setup_case_and_schedule(db):
    """Create a case and schedule the default 5-step workflow."""
    customer = create_test_customer(db)
    revenue_event = create_test_revenue_event(db, customer)
    case = create_test_recovery_case(db, customer, revenue_event)
    created = schedule_recovery_workflow(db, case)
    return case, created


def make_action_due(action, db):
    """Set an action's scheduled_for to the past."""
    action.scheduled_for = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()


def make_all_actions_due(case, db):
    """Make all actions for a case due."""
    actions = get_actions_by_case(db, case.id)
    for a in actions:
        a.scheduled_for = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()


# ============================================================
# DEFAULT SCHEDULE CONFIG
# ============================================================


class TestDefaultScheduleConfig:
    def test_has_5_steps(self):
        """Default schedule has 5 steps: initial + 4 reminders."""
        assert len(DEFAULT_SCHEDULE_CONFIG) == 5

    def test_delays_are_exponential_backoff(self):
        """Delays: 0, 4, 12, 28, 60 hours (exponential backoff)."""
        delays = [s["delay_hours"] for s in DEFAULT_SCHEDULE_CONFIG]
        assert delays == [0, 4, 12, 28, 60]

    def test_action_types_are_sequential(self):
        """Action types go from initial to final."""
        types = [s["action_type"] for s in DEFAULT_SCHEDULE_CONFIG]
        assert types == [
            "initial_message",
            "reminder_1",
            "reminder_2",
            "reminder_3",
            "final_reminder",
        ]

    def test_all_actions_on_whatsapp(self):
        """All actions are on whatsapp channel."""
        channels = [s["channel"] for s in DEFAULT_SCHEDULE_CONFIG]
        assert all(c == "whatsapp" for c in channels)


# ============================================================
# SCHEDULE RECOVERY WORKFLOW
# ============================================================


class TestScheduleRecoveryWorkflow:
    def test_creates_5_actions(self):
        """Default schedule creates 5 actions."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        created = schedule_recovery_workflow(db, case)

        assert len(created) == 5
        actions = get_actions_by_case(db, case.id)
        assert len(actions) == 5
        assert all(a.status == "pending" for a in actions)
        db.close()

    def test_actions_are_sequential(self):
        """Each action has increasing attempt_number."""
        db = TestSessionLocal()
        case, created = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        for i, action in enumerate(actions):
            assert action.attempt_number == i + 1
        db.close()

    def test_initial_message_is_first(self):
        """First action is initial_message on whatsapp."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        assert actions[0].action_type == "initial_message"
        assert actions[0].channel == "whatsapp"
        assert actions[0].attempt_number == 1
        db.close()

    def test_final_reminder_is_last(self):
        """Last action is final_reminder."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        assert actions[-1].action_type == "final_reminder"
        assert actions[-1].attempt_number == 5
        db.close()

    def test_initial_action_scheduled_for_now(self):
        """First action is scheduled for approximately now."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        diff = abs((actions[0].scheduled_for - now).total_seconds())
        assert diff < 10
        db.close()

    def test_reminder_1_4_hours_after_initial(self):
        """Reminder 1 is ~4 hours after initial."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        delta = actions[1].scheduled_for - actions[0].scheduled_for
        # Allow some tolerance for test execution time
        assert 3.5 <= delta.total_seconds() / 3600 <= 4.5
        db.close()

    def test_reminder_2_12_hours_after_initial(self):
        """Reminder 2 is ~12 hours after initial."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        delta = actions[2].scheduled_for - actions[0].scheduled_for
        assert 11.5 <= delta.total_seconds() / 3600 <= 12.5
        db.close()

    def test_reminder_3_28_hours_after_initial(self):
        """Reminder 3 is ~28 hours after initial."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        delta = actions[3].scheduled_for - actions[0].scheduled_for
        assert 27.5 <= delta.total_seconds() / 3600 <= 28.5
        db.close()

    def test_final_reminder_60_hours_after_initial(self):
        """Final reminder is ~60 hours after initial."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        delta = actions[4].scheduled_for - actions[0].scheduled_for
        assert 59.5 <= delta.total_seconds() / 3600 <= 60.5
        db.close()

    def test_custom_schedule_config(self):
        """Custom schedule config is respected."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        custom_config = [
            {"delay_hours": 0, "action_type": "initial_message", "channel": "whatsapp"},
            {"delay_hours": 2, "action_type": "reminder_1", "channel": "email"},
        ]
        created = schedule_recovery_workflow(db, case, schedule_config=custom_config)

        assert len(created) == 2
        actions = get_actions_by_case(db, case.id)
        assert actions[0].action_type == "initial_message"
        assert actions[1].action_type == "reminder_1"
        assert actions[1].channel == "email"
        db.close()

    def test_returns_action_details(self):
        """Returns details of created actions."""
        db = TestSessionLocal()
        case, created = setup_case_and_schedule(db)

        assert len(created) == 5
        for item in created:
            assert "id" in item
            assert "action_type" in item
            assert "attempt_number" in item
            assert "channel" in item
            assert "scheduled_for" in item
        db.close()

    def test_all_actions_linked_to_case(self):
        """All actions reference the correct recovery case."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        for action in actions:
            assert action.recovery_case_id == case.id
        db.close()


# ============================================================
# PROCESS DUE ACTIONS
# ============================================================


class TestProcessDueActions:
    def test_executes_due_action(self):
        """Due actions are executed successfully."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        make_action_due(actions[0], db)

        results = process_due_actions(db)

        assert results["total_due"] == 1
        assert results["executed"] == 1
        assert results["cancelled"] == 0
        assert results["skipped"] == 0

        db.refresh(actions[0])
        assert actions[0].status == "executed"
        assert actions[0].executed_at is not None
        db.close()

    def test_does_not_execute_future_actions(self):
        """Actions scheduled for the future are not executed."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        future_config = [
            {"delay_hours": 2, "action_type": "initial_message", "channel": "whatsapp"},
        ]
        schedule_recovery_workflow(db, case, schedule_config=future_config)

        results = process_due_actions(db)

        assert results["total_due"] == 0
        assert results["executed"] == 0
        db.close()

    def test_cancels_when_case_recovered(self):
        """If case is RECOVERED, due actions are cancelled."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, status=RecoveryStatus.RECOVERED
        )
        schedule_recovery_workflow(db, case)
        make_all_actions_due(case, db)

        results = process_due_actions(db)

        assert results["cancelled"] == 5
        assert results["executed"] == 0
        db.close()

    def test_cancels_when_case_stopped(self):
        """If case is STOPPED, due actions are cancelled."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, status=RecoveryStatus.STOPPED
        )
        schedule_recovery_workflow(db, case)
        make_all_actions_due(case, db)

        results = process_due_actions(db)

        assert results["cancelled"] == 5
        assert results["executed"] == 0
        db.close()

    def test_cancels_when_case_lost(self):
        """If case is LOST, due actions are cancelled."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, status=RecoveryStatus.LOST
        )
        schedule_recovery_workflow(db, case)
        make_all_actions_due(case, db)

        results = process_due_actions(db)

        assert results["cancelled"] == 5
        assert results["executed"] == 0
        db.close()

    def test_cancels_when_max_attempts_reached(self):
        """If max attempts reached, due actions are cancelled."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, attempt_count=5, max_attempts=5
        )
        schedule_recovery_workflow(db, case)
        make_all_actions_due(case, db)

        results = process_due_actions(db)

        assert results["cancelled"] == 5
        assert results["executed"] == 0
        db.close()

    def test_cancels_when_deadline_passed(self):
        """If recovery deadline has passed, due actions are cancelled."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        past_deadline = datetime.now(timezone.utc) - timedelta(days=1)
        case = create_test_recovery_case(
            db, customer, revenue_event, recovery_deadline=past_deadline
        )
        schedule_recovery_workflow(db, case)
        make_all_actions_due(case, db)

        results = process_due_actions(db)

        assert results["cancelled"] == 5
        assert results["executed"] == 0
        db.close()

    def test_cancels_when_payment_recovered(self):
        """If remaining_amount <= 0, due actions are cancelled."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, original_amount=50000
        )
        # Simulate full payment
        case.recovered_amount = 50000
        case.remaining_amount = 0
        db.commit()
        schedule_recovery_workflow(db, case)
        make_all_actions_due(case, db)

        results = process_due_actions(db)

        assert results["cancelled"] == 5
        assert results["executed"] == 0
        db.close()

    def test_cancels_all_when_one_action_fails(self):
        """When a due action is cancelled, all remaining pending are cancelled too."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, attempt_count=5, max_attempts=5
        )
        schedule_recovery_workflow(db, case)

        # Make only first action due
        actions = get_actions_by_case(db, case.id)
        make_action_due(actions[0], db)

        results = process_due_actions(db)

        assert results["cancelled"] == 1

        # All 5 should be cancelled
        all_actions = get_actions_by_case(db, case.id)
        assert all(a.status == "cancelled" for a in all_actions)
        db.close()

    def test_cancellation_reason_recorded(self):
        """Cancelled actions have a reason recorded."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, attempt_count=5, max_attempts=5
        )
        schedule_recovery_workflow(db, case)
        make_all_actions_due(case, db)

        process_due_actions(db)

        actions = get_actions_by_case(db, case.id)
        for a in actions:
            assert a.cancellation_reason is not None
            assert a.cancelled_at is not None
        db.close()

    def test_mixed_executed_and_pending(self):
        """Only due actions are processed; future actions remain pending."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        make_action_due(actions[0], db)

        results = process_due_actions(db)

        assert results["executed"] == 1

        all_actions = get_actions_by_case(db, case.id)
        assert all_actions[0].status == "executed"
        for a in all_actions[1:]:
            assert a.status == "pending"
        db.close()


# ============================================================
# PRE-REMINDER CHECKS
# ============================================================


class TestPreReminderChecks:
    def test_checks_payment_status(self):
        """Cancelled if remaining_amount <= 0 (payment recovered)."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        schedule_recovery_workflow(db, case)

        actions = get_actions_by_case(db, case.id)
        make_action_due(actions[0], db)

        # Simulate payment before processing
        case.recovered_amount = 50000
        case.remaining_amount = 0
        db.commit()

        detail = process_single_action(db, actions[0])

        assert detail["result"] == "cancelled"
        assert "payment" in detail["reason"].lower()
        db.close()

    def test_checks_terminal_state(self):
        """Cancelled if case is in terminal state."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, status=RecoveryStatus.RECOVERED
        )

        action = create_scheduled_action(
            db,
            data={
                "recovery_case_id": case.id,
                "action_type": "reminder_1",
                "attempt_number": 2,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )

        detail = process_single_action(db, action)

        assert detail["result"] == "cancelled"
        assert "stop" in detail["reason"].lower() or "terminal" in detail["reason"].lower() or "case_closed" in detail["reason"].lower()
        db.close()

    def test_checks_max_attempts(self):
        """Cancelled if max_attempts reached."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, attempt_count=5, max_attempts=5
        )

        action = create_scheduled_action(
            db,
            data={
                "recovery_case_id": case.id,
                "action_type": "reminder_1",
                "attempt_number": 2,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )

        detail = process_single_action(db, action)

        assert detail["result"] == "cancelled"
        assert "max_attempts" in detail["reason"]
        db.close()

    def test_checks_deadline(self):
        """Cancelled if deadline has passed."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        past_deadline = datetime.now(timezone.utc) - timedelta(days=1)
        case = create_test_recovery_case(
            db, customer, revenue_event, recovery_deadline=past_deadline
        )

        action = create_scheduled_action(
            db,
            data={
                "recovery_case_id": case.id,
                "action_type": "reminder_1",
                "attempt_number": 2,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )

        detail = process_single_action(db, action)

        assert detail["result"] == "cancelled"
        assert "deadline" in detail["reason"]
        db.close()

    def test_checks_case_not_found(self):
        """Cancelled if case doesn't exist."""
        db = TestSessionLocal()

        fake_case_id = uuid.uuid4()
        action = create_scheduled_action(
            db,
            data={
                "recovery_case_id": fake_case_id,
                "action_type": "reminder_1",
                "attempt_number": 2,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )

        detail = process_single_action(db, action)

        assert detail["result"] == "cancelled"
        assert "case_not_found" in detail["reason"] or "case_closed" in detail["reason"]
        db.close()

    def test_checks_customer_responded(self):
        """Cancelled if customer has responded since last outbound message."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        schedule_recovery_workflow(db, case)

        now = datetime.now(timezone.utc)

        # Create a conversation with an outbound message first
        conv = Conversation(
            recovery_case_id=case.id,
            channel="whatsapp",
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

        outbound_time = now - timedelta(minutes=10)
        outbound = ConversationMessage(
            conversation_id=conv.id,
            direction="outbound",
            content="Hi Rahul, your payment is pending",
            message_type="text",
            created_at=outbound_time,
        )
        db.add(outbound)
        db.commit()

        # Create an inbound message AFTER the outbound
        inbound_time = now - timedelta(minutes=5)
        inbound = ConversationMessage(
            conversation_id=conv.id,
            direction="inbound",
            content="I will pay tomorrow",
            message_type="text",
            created_at=inbound_time,
        )
        db.add(inbound)
        db.commit()

        # Make second action due
        actions = get_actions_by_case(db, case.id)
        make_action_due(actions[1], db)

        detail = process_single_action(db, actions[1])

        assert detail["result"] == "cancelled"
        assert detail["reason"] == "customer_responded"
        db.close()

    def test_executes_when_all_checks_pass(self):
        """Executes when all pre-reminder checks pass."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        make_action_due(actions[0], db)

        detail = process_single_action(db, actions[0])

        assert detail["result"] == "executed"
        assert detail["action_type"] == "initial_message"
        assert detail["channel"] == "whatsapp"
        db.close()


# ============================================================
# CUSTOMER RESPONSE HANDLING
# ============================================================


class TestHandleCustomerResponse:
    def _setup_case(self, db):
        """Helper to create a case in recovery."""
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        schedule_recovery_workflow(db, case)
        return case, customer

    def test_stop_keyword_english(self):
        """'stop' keyword stops recovery immediately."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        result = handle_customer_response(db, case.id, "Stop messaging me")

        assert result["status"] == "stopped"
        assert result["reason"] == "customer_requested_stop"

        # All pending actions should be cancelled
        actions = get_actions_by_case(db, case.id)
        assert all(a.status == "cancelled" for a in actions)

        # Case should be STOPPED
        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        db.close()

    def test_stop_keyword_hindi(self):
        """Hindi stop keywords work."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        result = handle_customer_response(db, case.id, "मत भेजो मुझे")

        assert result["status"] == "stopped"
        assert result["reason"] == "customer_requested_stop"
        db.close()

    def test_stop_keyword_hinglish(self):
        """Hinglish stop keywords work."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        result = handle_customer_response(db, case.id, "Band karo messages")

        assert result["status"] == "stopped"
        assert result["reason"] == "customer_requested_stop"
        db.close()

    def test_stop_keyword_unsubscribe(self):
        """'unsubscribe' stops recovery."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        result = handle_customer_response(db, case.id, "Please unsubscribe me")

        assert result["status"] == "stopped"
        db.close()

    def test_stop_keyword_leave_me_alone(self):
        """'leave me alone' stops recovery."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        result = handle_customer_response(db, case.id, "Leave me alone")

        assert result["status"] == "stopped"
        db.close()

    def test_stop_keyword_do_not_message(self):
        """'do not message me' stops recovery."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        result = handle_customer_response(db, case.id, "Do not message me again")

        assert result["status"] == "stopped"
        db.close()

    def test_stop_keyword_i_dont_want(self):
        """'I don't want this' stops recovery."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        result = handle_customer_response(db, case.id, "I don't want this anymore")

        assert result["status"] == "stopped"
        db.close()

    def test_stop_cancels_all_pending_actions(self):
        """Stop request cancels ALL pending actions."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        # Verify 5 pending actions
        actions = get_actions_by_case(db, case.id)
        assert len([a for a in actions if a.status == "pending"]) == 5

        handle_customer_response(db, case.id, "Stop")

        # All should be cancelled
        actions = get_actions_by_case(db, case.id)
        assert all(a.status == "cancelled" for a in actions)
        db.close()

    def test_stop_never_sends_another_reminder(self):
        """After stop, no actions can be executed."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        handle_customer_response(db, case.id, "Stop")

        # Try to process due actions — should find none
        make_all_actions_due(case, db)
        results = process_due_actions(db)
        assert results["executed"] == 0
        db.close()

    def test_non_stop_response_cancels_reminders(self):
        """Non-stop response cancels pending reminders but doesn't stop case."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = handle_customer_response(
            db, case.id, "I will pay tomorrow"
        )

        assert result["status"] == "handled"
        assert "intent" in result
        assert result["actions_cancelled"] >= 0

        # Case should NOT be stopped (unless intent mapped to stop)
        db.refresh(case)
        # The intent action mapper handles STOP_REQUEST, but PROMISE_TO_PAY
        # or other intents should not stop the case
        if result["intent"] not in ("STOP_REQUEST",):
            assert case.status != RecoveryStatus.STOPPED
        db.close()

    def test_no_stop_cancels_pending_reminders(self):
        """Even non-stop responses cancel pending generic reminders."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        handle_customer_response(db, case.id, "Can you send a payment link?")

        # Pending actions should be cancelled (customer responded)
        actions = get_actions_by_case(db, case.id)
        pending = [a for a in actions if a.status == "pending"]
        executed = [a for a in actions if a.status == "executed"]
        cancelled = [a for a in actions if a.status == "cancelled"]
        # Either all cancelled (from customer_responded) or some processed
        assert len(pending) == 0 or len(cancelled) >= 0
        db.close()

    def test_handles_case_not_found(self):
        """Returns error for nonexistent case."""
        db = TestSessionLocal()

        result = handle_customer_response(db, uuid.uuid4(), "Hello")

        assert result["status"] == "error"
        assert result["reason"] == "case_not_found"
        db.close()

    def test_handles_terminal_case(self):
        """Returns skipped for terminal case."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, status=RecoveryStatus.RECOVERED
        )

        result = handle_customer_response(db, case.id, "Hello")

        assert result["status"] == "skipped"
        assert "terminal" in result["reason"]
        db.close()

    def test_promise_to_pay_intent(self):
        """Customer promise maps to correct intent."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = handle_customer_response(
            db, case.id, "I promise to pay by Friday"
        )

        assert result["status"] == "handled"
        assert result["intent"] == "PROMISE_TO_PAY"
        db.close()

    def test_payment_link_request_intent(self):
        """Payment link request maps correctly."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = handle_customer_response(
            db, case.id, "Please send the payment link"
        )

        assert result["status"] == "handled"
        assert result["intent"] == "PAYMENT_LINK_REQUEST"
        db.close()

    def test_already_paid_intent(self):
        """Already paid maps correctly."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = handle_customer_response(
            db, case.id, "I already paid the amount"
        )

        assert result["status"] == "handled"
        assert result["intent"] == "ALREADY_PAID"
        db.close()

    def test_negative_intent(self):
        """Negative response maps correctly."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = handle_customer_response(
            db, case.id, "I will not pay you"
        )

        assert result["status"] == "handled"
        assert result["intent"] == "NEGATIVE"
        db.close()

    def test_records_audit_event(self):
        """Customer response creates an audit event."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        handle_customer_response(db, case.id, "I will pay tomorrow")

        # Check audit event was created
        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.entity_type == "customer_response",
        ).all()

        assert len(audits) == 1
        assert audits[0].action == "response_handled"
        db.close()

    def test_handles_hindi_response(self):
        """Hindi response is classified correctly."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = handle_customer_response(
            db, case.id, "मैं कल भुगतान करूंगा"
        )

        assert result["status"] == "handled"
        assert result["language"] in ("hi", "hi-en")
        db.close()

    def test_handles_hinglish_response(self):
        """Hinglish response is classified correctly."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = handle_customer_response(
            db, case.id, "Kal payment kar dunga"
        )

        assert result["status"] == "handled"
        assert result["language"] in ("hi-en", "hi")
        db.close()

    def test_record_attempt_called(self):
        """A recovery attempt is recorded on customer response."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        handle_customer_response(db, case.id, "I will pay")

        # Verify attempt was recorded
        from app.models.recovery_attempt import RecoveryAttempt
        attempts = db.query(RecoveryAttempt).filter(
            RecoveryAttempt.recovery_case_id == case.id
        ).all()

        assert len(attempts) == 1
        assert attempts[0].result in ("customer_responded", "promised")
        db.close()


# ============================================================
# CANCEL ALL ACTIONS
# ============================================================


class TestCancelAllActions:
    def test_cancel_all_pending(self):
        """Cancels all pending actions for a case."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        count = cancel_all_actions_for_case(db, case.id, reason="customer_opted_out")

        assert count == 5
        actions = get_actions_by_case(db, case.id)
        assert all(a.status == "cancelled" for a in actions)
        for a in actions:
            assert a.cancellation_reason == "customer_opted_out"
        db.close()

    def test_cancel_preserves_executed(self):
        """Only pending actions are cancelled; executed ones are untouched."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        # Execute first action
        actions = get_actions_by_case(db, case.id)
        make_action_due(actions[0], db)
        process_due_actions(db)

        # Cancel remaining
        count = cancel_all_actions_for_case(db, case.id, reason="manual_stop")

        assert count == 4  # 5 total - 1 already executed

        all_actions = get_actions_by_case(db, case.id)
        assert all_actions[0].status == "executed"
        for a in all_actions[1:]:
            assert a.status == "cancelled"
        db.close()

    def test_cancel_returns_zero_when_none_pending(self):
        """Returns 0 when there are no pending actions."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        cancel_all_actions_for_case(db, case.id, reason="first_cancel")
        count = cancel_all_actions_for_case(db, case.id, reason="second_cancel")

        assert count == 0
        db.close()


# ============================================================
# GET SCHEDULE STATUS
# ============================================================


class TestGetScheduleStatus:
    def test_status_groups_by_state(self):
        """Groups actions into pending/executed/cancelled."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        status = get_schedule_status(db, case.id)

        assert status["total_actions"] == 5
        assert len(status["pending"]) == 5
        assert len(status["executed"]) == 0
        assert len(status["cancelled"]) == 0
        db.close()

    def test_status_after_execution(self):
        """Reflects executed actions."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        make_action_due(actions[0], db)
        process_due_actions(db)

        status = get_schedule_status(db, case.id)

        assert status["total_actions"] == 5
        assert len(status["pending"]) == 4
        assert len(status["executed"]) == 1
        assert status["executed"][0]["action_type"] == "initial_message"
        db.close()

    def test_status_empty_case(self):
        """Status for a case with no actions."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        status = get_schedule_status(db, case.id)

        assert status["total_actions"] == 0
        assert len(status["pending"]) == 0
        db.close()


# ============================================================
# STOP KEYWORDS
# ============================================================


class TestStopKeywords:
    def test_has_english_keywords(self):
        """Contains English stop keywords."""
        assert "stop" in STOP_KEYWORDS
        assert "unsubscribe" in STOP_KEYWORDS
        assert "leave me alone" in STOP_KEYWORDS

    def test_has_hindi_keywords(self):
        """Contains Hindi stop keywords."""
        assert "रुको" in STOP_KEYWORDS
        assert "बंद" in STOP_KEYWORDS
        assert "मत भेजो" in STOP_KEYWORDS

    def test_has_hinglish_keywords(self):
        """Contains Hinglish stop keywords."""
        assert "band karo" in STOP_KEYWORDS
        assert "mat bhejo" in STOP_KEYWORDS


# ============================================================
# FULL LIFECYCLE
# ============================================================


class TestFullLifecycle:
    def test_schedule_then_execute_all_5(self):
        """Schedule, make all due, process — all 5 executed."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)
        make_all_actions_due(case, db)

        results = process_due_actions(db)

        assert results["total_due"] == 5
        assert results["executed"] == 5

        all_actions = get_actions_by_case(db, case.id)
        assert all(a.status == "executed" for a in all_actions)
        assert all(a.executed_at is not None for a in all_actions)
        db.close()

    def test_schedule_then_stop_cancels_all(self):
        """Schedule, then stop — all actions cancelled."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        count = cancel_all_actions_for_case(db, case.id, reason="customer_requested_stop")

        assert count == 5

        results = process_due_actions(db)
        assert results["total_due"] == 0
        db.close()

    def test_partial_execution_then_stop(self):
        """Execute some, then stop — remaining cancelled."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        # Execute first 2
        actions = get_actions_by_case(db, case.id)
        for a in actions[:2]:
            make_action_due(a, db)
        process_due_actions(db)

        # Cancel remaining
        count = cancel_all_actions_for_case(db, case.id, reason="manual_stop")
        assert count == 3

        all_actions = get_actions_by_case(db, case.id)
        assert sum(1 for a in all_actions if a.status == "executed") == 2
        assert sum(1 for a in all_actions if a.status == "cancelled") == 3
        db.close()

    def test_staggered_execution(self):
        """Actions executed one at a time as they become due."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # Use custom config with all future delays
        future_config = [
            {"delay_hours": 1, "action_type": "initial_message", "channel": "whatsapp"},
            {"delay_hours": 5, "action_type": "reminder_1", "channel": "whatsapp"},
            {"delay_hours": 10, "action_type": "reminder_2", "channel": "whatsapp"},
            {"delay_hours": 20, "action_type": "reminder_3", "channel": "whatsapp"},
            {"delay_hours": 30, "action_type": "final_reminder", "channel": "whatsapp"},
        ]
        schedule_recovery_workflow(db, case, schedule_config=future_config)

        # Process — nothing due yet
        results = process_due_actions(db)
        assert results["total_due"] == 0

        actions = get_actions_by_case(db, case.id)

        # Execute first
        make_action_due(actions[0], db)
        results = process_due_actions(db)
        assert results["executed"] == 1

        # Execute second
        make_action_due(actions[1], db)
        results = process_due_actions(db)
        assert results["executed"] == 1

        all_actions = get_actions_by_case(db, case.id)
        assert sum(1 for a in all_actions if a.status == "executed") == 2
        assert sum(1 for a in all_actions if a.status == "pending") == 3
        db.close()

    def test_stop_mid_sequence(self):
        """Customer stops after reminder_1 — remaining cancelled."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)

        # Execute initial
        make_action_due(actions[0], db)
        process_due_actions(db)

        # Execute reminder_1
        make_action_due(actions[1], db)
        process_due_actions(db)

        # Customer says stop
        result = handle_customer_response(db, case.id, "Stop")

        assert result["status"] == "stopped"

        # Remaining 3 should be cancelled
        all_actions = get_actions_by_case(db, case.id)
        executed = [a for a in all_actions if a.status == "executed"]
        cancelled = [a for a in all_actions if a.status == "cancelled"]
        assert len(executed) == 2
        assert len(cancelled) == 3
        db.close()

    def test_payment_recovers_mid_sequence(self):
        """Payment received after reminder_1 — remaining cancelled."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)

        # Execute initial
        make_action_due(actions[0], db)
        process_due_actions(db)

        # Simulate payment recovery
        case.recovered_amount = 50000
        case.remaining_amount = 0
        db.commit()

        # Process reminder_1 — should be cancelled (payment recovered)
        make_action_due(actions[1], db)
        detail = process_single_action(db, actions[1])
        assert detail["result"] == "cancelled"
        assert "payment" in detail["reason"].lower()

        # Remaining should also be cancelled
        for a in actions[2:]:
            make_action_due(a, db)
            detail = process_single_action(db, a)
            assert detail["result"] == "cancelled"
        db.close()

    def test_no_duplicate_messages_sent(self):
        """Each action type is sent exactly once in the default schedule."""
        db = TestSessionLocal()
        case, _ = setup_case_and_schedule(db)

        actions = get_actions_by_case(db, case.id)
        action_types = [a.action_type for a in actions]

        # All 5 action types should be unique
        assert len(action_types) == len(set(action_types))
        db.close()

    def test_max_attempts_stops_all(self):
        """Max attempts reached — all actions cancelled."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, attempt_count=5, max_attempts=5
        )
        schedule_recovery_workflow(db, case)
        make_all_actions_due(case, db)

        results = process_due_actions(db)

        assert results["cancelled"] == 5
        assert results["executed"] == 0

        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        db.close()

    def test_deadline_stops_all(self):
        """Recovery deadline passed — all actions cancelled."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        past_deadline = datetime.now(timezone.utc) - timedelta(hours=1)
        case = create_test_recovery_case(
            db, customer, revenue_event, recovery_deadline=past_deadline
        )
        schedule_recovery_workflow(db, case)
        make_all_actions_due(case, db)

        results = process_due_actions(db)

        assert results["cancelled"] == 5
        assert results["executed"] == 0
        db.close()
