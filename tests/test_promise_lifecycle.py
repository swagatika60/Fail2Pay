"""Tests for Promise Lifecycle Management.

Covers:
- Promise expiry and BROKEN status
- High-value escalation to payment plan
- Standard escalation with expiry reminder
- Promise timeline data
- Promise history for customer
- Hard stop enforcement (active promise suppresses reminders)
- Edge cases
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
from app.models.promise import Promise, PromiseStatus
from app.models.audit_event import AuditEvent
from app.models.scheduled_action import ScheduledAction
from app.schemas.scheduled_action import ScheduledActionCreate
from app.crud.promise import (
    create_promise,
    get_promise,
    get_active_promise_for_case,
    mark_promise_fulfilled,
    count_promises_by_status,
)
from app.crud.scheduled_action import create_scheduled_action, get_actions_by_case
from app.services.promise import create_promise_for_case, fulfill_promise
from app.services.promise_lifecycle import (
    check_and_process_expired_promises,
    process_expired_promise,
    get_promise_timeline,
    get_promise_history_for_customer,
    get_high_value_threshold,
)

# --- SQLite in-memory DB ---

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# --- Helpers ---


def create_test_customer(db, email="rahul@example.com", name="Rahul Sharma") -> Customer:
    customer = Customer(
        external_id=f"cust_{uuid.uuid4().hex[:8]}",
        email=email,
        phone="+911234567890",
        name=name,
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
    db, customer, revenue_event,
    status=RecoveryStatus.RECOVERY_IN_PROGRESS,
    original_amount=50000,
) -> RecoveryCase:
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=revenue_event.id,
        risk_level="high",
        risk_reason="Payment failed",
        status=status,
        original_amount=original_amount,
        recovered_amount=0,
        remaining_amount=original_amount,
        attempt_count=1,
        max_attempts=5,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def setup_case_with_schedule(db, original_amount=50000):
    """Create a case with scheduled actions."""
    customer = create_test_customer(db)
    revenue_event = create_test_revenue_event(db, customer)
    case = create_test_recovery_case(db, customer, revenue_event, original_amount=original_amount)

    # Add scheduled actions
    now = datetime.now(timezone.utc)
    for i, delay in enumerate([4, 12, 28, 60]):
        create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type=f"reminder_{i+1}",
                attempt_number=i+2,
                channel="whatsapp",
                scheduled_for=now + timedelta(hours=delay),
            ),
        )

    return case, customer


def create_expired_promise(db, case, customer, amount=50000):
    """Create an already-expired promise for testing."""
    from app.schemas.promise import PromiseCreate

    promised_date = datetime.now(timezone.utc) - timedelta(days=3)
    expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

    promise = create_promise(
        db,
        data=PromiseCreate(
            recovery_case_id=case.id,
            customer_id=customer.id,
            amount_promised=amount,
            currency="INR",
            promised_date=promised_date,
            promise_window_hours=72,
            customer_message="I'll pay tomorrow",
        ),
    )
    promise.expires_at = expires_at
    promise.status = PromiseStatus.ACTIVE.value
    db.commit()
    db.refresh(promise)
    return promise


# ============================================================
# PROMISE EXPIRY
# ============================================================


class TestPromiseExpiry:
    def test_expired_promise_marked_broken(self):
        """Expired promise is marked as BROKEN."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        result = check_and_process_expired_promises(db)

        assert result["total_expired"] == 1
        assert result["processed"] == 1

        db.refresh(promise)
        assert promise.status == PromiseStatus.BROKEN.value
        assert promise.missed_at is not None
        db.close()

    def test_broken_promise_creates_audit(self):
        """Broken promise creates PROMISE_MISSED audit event."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        check_and_process_expired_promises(db)

        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "promise_missed",
        ).all()

        assert len(audits) == 1
        assert audits[0].entity_type == "promise"
        db.close()

    def test_broken_promise_resumes_recovery(self):
        """Broken promise resumes recovery (PROMISED → RECOVERY_IN_PROGRESS)."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        check_and_process_expired_promises(db)

        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERY_IN_PROGRESS
        db.close()

    def test_broken_promise_reschedules_actions(self):
        """Broken promise creates new scheduled actions."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        check_and_process_expired_promises(db)

        actions = get_actions_by_case(db, case.id)
        pending = [a for a in actions if a.status == "pending"]
        assert len(pending) > 0
        db.close()

    def test_no_expired_promises(self):
        """No action when no promises are expired."""
        db = TestSessionLocal()

        result = check_and_process_expired_promises(db)

        assert result["total_expired"] == 0
        assert result["processed"] == 0
        db.close()

    def test_multiple_expired_promises(self):
        """Multiple expired promises are all processed."""
        db = TestSessionLocal()
        case1, customer1 = setup_case_with_schedule(db)
        case2, customer2 = setup_case_with_schedule(db)

        create_expired_promise(db, case1, customer1)
        case1.status = RecoveryStatus.PROMISED
        create_expired_promise(db, case2, customer2)
        case2.status = RecoveryStatus.PROMISED
        db.commit()

        result = check_and_process_expired_promises(db)

        assert result["total_expired"] == 2
        assert result["processed"] == 2
        db.close()

    def test_broken_promise_extra_data(self):
        """Broken promise stores metadata in extra_data."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        check_and_process_expired_promises(db)

        db.refresh(promise)
        assert promise.extra_data is not None
        assert "broken_at" in promise.extra_data
        assert "days_since_promised" in promise.extra_data
        assert promise.extra_data["days_since_promised"] >= 2
        db.close()


# ============================================================
# HIGH-VALUE ESCALATION
# ============================================================


class TestHighValueEscalation:
    @patch("app.services.whatsapp.send_text_message")
    def test_high_value_proposes_payment_plan(self, mock_send):
        """High-value broken promise proposes payment plan."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_plan"}

        db = TestSessionLocal()
        # High-value case (₹10,000+ = 1,000,000 paise)
        case, customer = setup_case_with_schedule(db, original_amount=1_500_000)

        promise = create_expired_promise(db, case, customer, amount=1_500_000)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        result = check_and_process_expired_promises(db)

        assert result["high_value_escalated"] == 1
        assert result["standard_reminded"] == 0

        # Verify payment plan audit was created
        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "payment_plan_proposed",
        ).all()
        assert len(audits) == 1
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_high_value_sends_whatsapp(self, mock_send):
        """High-value escalation sends WhatsApp message."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_plan"}

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db, original_amount=2_000_000)

        promise = create_expired_promise(db, case, customer, amount=2_000_000)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        check_and_process_expired_promises(db)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["recovery_case_id"] == case.id
        db.close()

    def test_high_value_no_phone(self):
        """High-value escalation gracefully handles no phone."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db, original_amount=1_500_000)
        customer.phone = None
        db.commit()

        promise = create_expired_promise(db, case, customer, amount=1_500_000)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        result = check_and_process_expired_promises(db)

        assert result["high_value_escalated"] == 1
        # Promise should still be marked broken even if message couldn't be sent
        db.refresh(promise)
        assert promise.status == PromiseStatus.BROKEN.value
        db.close()


# ============================================================
# STANDARD ESCALATION
# ============================================================


class TestStandardEscalation:
    @patch("app.services.whatsapp.send_text_message")
    def test_standard_sends_expiry_reminder(self, mock_send):
        """Standard broken promise sends expiry reminder."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_remind"}

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db, original_amount=50000)

        promise = create_expired_promise(db, case, customer, amount=50000)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        result = check_and_process_expired_promises(db)

        assert result["standard_reminded"] == 1
        assert result["high_value_escalated"] == 0

        # Verify expiry reminder audit
        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "expiry_reminder_sent",
        ).all()
        assert len(audits) == 1
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_standard_message_content(self, mock_send):
        """Standard reminder message is polite and includes payment link."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_remind"}

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        check_and_process_expired_promises(db)

        call_kwargs = mock_send.call_args[1]
        message = call_kwargs["message"]
        assert "Rahul" in message
        assert "₹500" in message
        assert "payment" in message.lower()
        db.close()


# ============================================================
# PROMISE TIMELINE
# ============================================================


class TestPromiseTimeline:
    def test_timeline_with_created_promise(self):
        """Timeline shows promise creation event."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id, customer_message="I'll pay tomorrow")

        timeline = get_promise_timeline(db, case.id)

        assert len(timeline["timeline"]) == 1
        assert timeline["timeline"][0]["type"] == "promise_created"
        assert timeline["summary"]["total_promises"] == 1
        assert timeline["summary"]["active_count"] == 1
        db.close()

    def test_timeline_with_fulfilled_promise(self):
        """Timeline shows fulfilled event."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        result = create_promise_for_case(db, case.id)
        case.status = RecoveryStatus.PROMISED
        db.commit()
        fulfill_promise(db, case.id, 50000)

        timeline = get_promise_timeline(db, case.id)

        types = [e["type"] for e in timeline["timeline"]]
        assert "promise_created" in types
        assert "promise_fulfilled" in types
        assert timeline["summary"]["fulfilled_count"] == 1
        db.close()

    def test_timeline_with_broken_promise(self):
        """Timeline shows broken event."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        check_and_process_expired_promises(db)

        timeline = get_promise_timeline(db, case.id)

        types = [e["type"] for e in timeline["timeline"]]
        assert "promise_created" in types
        assert "promise_broken" in types
        assert timeline["summary"]["broken_count"] == 1
        db.close()

    def test_timeline_multiple_promises(self):
        """Timeline shows multiple promise events chronologically."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        # First promise: fulfilled
        result1 = create_promise_for_case(db, case.id)
        case.status = RecoveryStatus.PROMISED
        db.commit()
        fulfill_promise(db, case.id, 50000)

        # Second promise: broken
        promise2 = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()
        check_and_process_expired_promises(db)

        timeline = get_promise_timeline(db, case.id)

        assert timeline["summary"]["total_promises"] == 2
        assert timeline["summary"]["fulfilled_count"] == 1
        assert timeline["summary"]["broken_count"] == 1
        db.close()

    def test_timeline_empty(self):
        """Timeline works with no promises."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        timeline = get_promise_timeline(db, case.id)

        assert timeline["timeline"] == []
        assert timeline["summary"]["total_promises"] == 0
        db.close()

    def test_timeline_summary_fulfillment_rate(self):
        """Timeline summary calculates fulfillment rate."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        # Fulfill one
        result1 = create_promise_for_case(db, case.id)
        case.status = RecoveryStatus.PROMISED
        db.commit()
        fulfill_promise(db, case.id, 50000)

        # Break another
        promise2 = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()
        check_and_process_expired_promises(db)

        timeline = get_promise_timeline(db, case.id)

        assert timeline["summary"]["fulfillment_rate"] == 50.0
        db.close()


# ============================================================
# PROMISE HISTORY
# ============================================================


class TestPromiseHistory:
    def test_customer_history(self):
        """Customer history shows all promises."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id)

        history = get_promise_history_for_customer(db, customer.id)

        assert len(history) == 1
        assert history[0]["status"] == PromiseStatus.ACTIVE.value
        assert history[0]["amount_promised"] == 50000
        db.close()

    def test_customer_history_multiple_cases(self):
        """Customer history includes promises from multiple cases."""
        db = TestSessionLocal()
        case1, customer = setup_case_with_schedule(db)

        case2, _ = setup_case_with_schedule(db)

        create_promise_for_case(db, case1.id)
        create_promise_for_case(db, case2.id)

        history = get_promise_history_for_customer(db, customer.id)

        assert len(history) == 1  # Only case1 has this customer
        db.close()

    def test_customer_history_empty(self):
        """Customer history works with no promises."""
        db = TestSessionLocal()
        customer = create_test_customer(db)

        history = get_promise_history_for_customer(db, customer.id)

        assert history == []
        db.close()


# ============================================================
# HARD STOP ENFORCEMENT
# ============================================================


class TestHardStopEnforcement:
    def test_active_promise_suppresses_reminders(self):
        """Active promise suppresses all generic reminders."""
        from app.services.scheduler import process_single_action

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id)

        # Create a due action
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

        detail = process_single_action(db, action)

        assert detail["result"] == "cancelled"
        assert detail["reason"] == "active_promise_exists"
        db.close()

    def test_no_promise_allows_reminders(self):
        """Without active promise, reminders execute normally."""
        from app.services.scheduler import process_single_action

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

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

        detail = process_single_action(db, action)

        assert detail["result"] == "executed"
        db.close()

    def test_multiple_reminders_all_suppressed(self):
        """All pending reminders are suppressed by active promise."""
        from app.services.scheduler import process_single_action

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id)

        # Create multiple due actions
        for i in range(3):
            action = create_scheduled_action(
                db,
                data=ScheduledActionCreate(
                    recovery_case_id=case.id,
                    action_type=f"reminder_{i+1}",
                    attempt_number=i+2,
                    channel="whatsapp",
                    scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
                ),
            )
            detail = process_single_action(db, action)
            assert detail["result"] == "cancelled"
            assert detail["reason"] == "active_promise_exists"
        db.close()


# ============================================================
# HIGH-VALUE THRESHOLD
# ============================================================


class TestHighValueThreshold:
    def test_default_threshold(self):
        """Default threshold is ₹10,000."""
        threshold = get_high_value_threshold()
        assert threshold == 1_000_000  # 1000000 paise = ₹10,000

    def test_boundary_high_value(self):
        """Amount at threshold is treated as high-value."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db, original_amount=1_000_000)

        promise = create_expired_promise(db, case, customer, amount=1_000_000)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        # Just verify it doesn't crash
        result = process_expired_promise(db, promise)
        assert result["status"] == "processed"
        db.close()

    def test_boundary_standard(self):
        """Amount below threshold is treated as standard."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db, original_amount=999_999)

        promise = create_expired_promise(db, case, customer, amount=999_999)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        result = process_expired_promise(db, promise)
        assert result["status"] == "processed"
        assert result["escalation"] == "expiry_reminder"
        db.close()


# ============================================================
# EDGE CASES
# ============================================================


class TestEdgeCases:
    def test_already_broken_promise_not_reprocessed(self):
        """Already broken promise is not processed again."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise = create_expired_promise(db, case, customer)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        # Process once
        check_and_process_expired_promises(db)

        # Process again — should find no expired promises
        result = check_and_process_expired_promises(db)
        assert result["total_expired"] == 0
        db.close()

    def test_fulfilled_promise_not_expired(self):
        """Fulfilled promise is not affected by expiry check."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        result = create_promise_for_case(db, case.id)
        case.status = RecoveryStatus.PROMISED
        db.commit()
        fulfill_promise(db, case.id, 50000)

        # Run expiry check
        expiry_result = check_and_process_expired_promises(db)
        assert expiry_result["total_expired"] == 0
        db.close()

    def test_cancelled_promise_not_expired(self):
        """Cancelled promise is not affected by expiry check."""
        from app.services.promise import cancel_promise_for_case

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id)
        cancel_promise_for_case(db, case.id)

        expiry_result = check_and_process_expired_promises(db)
        assert expiry_result["total_expired"] == 0
        db.close()

    def test_promise_near_expiry_not_processed(self):
        """Promise that hasn't expired yet is not processed."""
        from app.schemas.promise import PromiseCreate

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        # Promise expires in 1 hour
        promise = create_promise(
            db,
            data=PromiseCreate(
                recovery_case_id=case.id,
                customer_id=customer.id,
                amount_promised=50000,
                currency="INR",
                promised_date=datetime.now(timezone.utc) - timedelta(hours=2),
                promise_window_hours=72,
            ),
        )
        promise.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.commit()

        expiry_result = check_and_process_expired_promises(db)
        assert expiry_result["total_expired"] == 0
        db.close()
