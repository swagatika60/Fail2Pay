"""Tests for Promise-to-Pay Service.

Covers:
- Promise creation
- Promise fulfillment (payment received)
- Promise missed (deadline passed)
- Promise cancelled (customer stop)
- Promise expiry check
- Scheduler pause during active promise
- Dashboard data
- Edge cases
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.promise import Promise, PromiseStatus
from app.models.scheduled_action import ScheduledAction
from app.models.audit_event import AuditEvent
from app.schemas.scheduled_action import ScheduledActionCreate
from app.crud.promise import (
    create_promise,
    get_promise,
    get_active_promise_for_case,
    mark_promise_fulfilled,
    mark_promise_missed,
    cancel_promise,
    get_expired_promises,
    count_promises_by_status,
)
from app.crud.scheduled_action import (
    create_scheduled_action,
    get_actions_by_case,
)
from app.services.promise import (
    create_promise_for_case,
    fulfill_promise,
    check_and_expire_promises,
    cancel_promise_for_case,
    get_promise_status,
    get_dashboard_data,
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


def setup_case_with_schedule(db):
    """Create a case with scheduled actions."""
    customer = create_test_customer(db)
    revenue_event = create_test_revenue_event(db, customer)
    case = create_test_recovery_case(db, customer, revenue_event)

    # Add some scheduled actions
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


# ============================================================
# PROMISE CREATION
# ============================================================


class TestPromiseCreation:
    def test_create_promise_for_case(self):
        """Create a promise for a recovery case."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        result = create_promise_for_case(
            db, case.id,
            customer_message="I'll pay tomorrow",
        )

        assert result["status"] == "created"
        assert result["promise_id"] is not None
        assert result["amount_promised"] == 50000
        assert result["promised_date"] is not None
        assert result["expires_at"] is not None
        assert result["case_status"] == "PROMISED"
        db.close()

    def test_promise_cancels_scheduled_actions(self):
        """Creating a promise cancels pending scheduled actions."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        # Verify actions exist
        actions = get_actions_by_case(db, case.id)
        pending_before = [a for a in actions if a.status == "pending"]
        assert len(pending_before) == 4

        result = create_promise_for_case(db, case.id)

        # All pending actions should be cancelled
        actions_after = get_actions_by_case(db, case.id)
        pending_after = [a for a in actions_after if a.status == "pending"]
        assert len(pending_after) == 0
        assert result["actions_cancelled"] == 4
        db.close()

    def test_promise_case_not_found(self):
        """Returns error for nonexistent case."""
        db = TestSessionLocal()

        result = create_promise_for_case(db, uuid.uuid4())

        assert result["status"] == "error"
        assert result["reason"] == "case_not_found"
        db.close()

    def test_promise_case_terminal(self):
        """Cannot create promise for terminal case."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, status=RecoveryStatus.RECOVERED
        )

        result = create_promise_for_case(db, case.id)

        assert result["status"] == "skipped"
        assert "terminal" in result["reason"]
        db.close()

    def test_promise_already_exists(self):
        """Cannot create second promise when one is active."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id)
        result2 = create_promise_for_case(db, case.id)

        assert result2["status"] == "skipped"
        assert result2["reason"] == "active_promise_exists"
        db.close()

    def test_promise_custom_date(self):
        """Promise with custom promised date."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        custom_date = datetime.now(timezone.utc) + timedelta(days=3)
        result = create_promise_for_case(
            db, case.id,
            promised_date=custom_date,
        )

        assert result["status"] == "created"

        promise = get_promise(db, uuid.UUID(result["promise_id"]))
        assert promise.promised_date.date() == custom_date.date()
        db.close()

    def test_promise_stores_message(self):
        """Promise stores the customer's message."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        result = create_promise_for_case(
            db, case.id,
            customer_message="Kal payment kar dunga",
        )

        promise = get_promise(db, uuid.UUID(result["promise_id"]))
        assert promise.customer_message == "Kal payment kar dunga"
        db.close()

    def test_promise_creates_audit_event(self):
        """Promise creation creates an audit event."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id, customer_message="I'll pay")

        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.entity_type == "promise",
        ).all()

        assert len(audits) == 1
        assert audits[0].action == "promise_created"
        db.close()


# ============================================================
# PROMISE FULFILLMENT
# ============================================================


class TestPromiseFulfillment:
    def test_fulfill_promise(self):
        """Fulfill a promise when payment is received."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        result = fulfill_promise(db, case.id, 50000)

        assert result["status"] == "fulfilled"
        assert result["amount_paid"] == 50000
        assert result["fully_recovered"] is True

        # Promise should be fulfilled
        promise = get_active_promise_for_case(db, case.id)
        assert promise is None  # No longer active

        # Case should be RECOVERED
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        db.close()

    def test_fulfill_promise_partial(self):
        """Fulfill promise with partial payment."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        result = fulfill_promise(db, case.id, 25000)

        assert result["status"] == "fulfilled"
        assert result["fully_recovered"] is False
        assert result["new_status"] == "PARTIALLY_RECOVERED"
        db.close()

    def test_fulfill_no_active_promise(self):
        """Fulfill when no active promise exists."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        result = fulfill_promise(db, case.id, 50000)

        assert result["status"] == "skipped"
        assert result["reason"] == "no_active_promise"
        db.close()

    def test_fulfill_creates_audit(self):
        """Fulfillment creates an audit event."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise_result = create_promise_for_case(db, case.id)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        fulfill_promise(db, case.id, 50000)

        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "promise_fulfilled",
        ).all()

        assert len(audits) == 1
        db.close()


# ============================================================
# PROMISE MISSED
# ============================================================


class TestPromiseMissed:
    def test_missed_promise(self):
        """Missed promise resumes recovery."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        # Create promise that expires soon
        result = create_promise_for_case(db, case.id)
        case.status = RecoveryStatus.PROMISED
        db.commit()

        promise = get_promise(db, uuid.UUID(result["promise_id"]))

        # Expire the promise
        promise.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

        # Check and expire
        expiry_result = check_and_expire_promises(db)

        assert expiry_result["total_expired"] == 1
        assert expiry_result["expired"] == 1
        assert expiry_result["resumed"] == 1

        # Promise should be missed
        db.refresh(promise)
        assert promise.status == PromiseStatus.MISSED.value
        assert promise.missed_at is not None

        # Case should be back to RECOVERY_IN_PROGRESS
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERY_IN_PROGRESS
        db.close()

    def test_no_expired_promises(self):
        """No action when no promises are expired."""
        db = TestSessionLocal()

        result = check_and_expire_promises(db)

        assert result["total_expired"] == 0
        assert result["expired"] == 0
        db.close()


# ============================================================
# PROMISE CANCELLED
# ============================================================


class TestPromiseCancelled:
    def test_cancel_promise(self):
        """Cancel an active promise."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        promise_result = create_promise_for_case(db, case.id)

        result = cancel_promise_for_case(db, case.id, reason="customer_requested_stop")

        assert result["status"] == "cancelled"
        assert result["promise_id"] == promise_result["promise_id"]

        # Promise should be cancelled
        promise = get_promise(db, uuid.UUID(promise_result["promise_id"]))
        assert promise.status == PromiseStatus.CANCELLED.value
        assert promise.cancelled_at is not None
        assert promise.cancellation_reason == "customer_requested_stop"
        db.close()

    def test_cancel_no_active_promise(self):
        """Cancel when no active promise exists."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        result = cancel_promise_for_case(db, case.id)

        assert result["status"] == "skipped"
        assert result["reason"] == "no_active_promise"
        db.close()

    def test_cancel_creates_audit(self):
        """Cancellation creates an audit event."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id)
        cancel_promise_for_case(db, case.id)

        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "promise_cancelled",
        ).all()

        assert len(audits) == 1
        db.close()


# ============================================================
# SCHEDULER PAUSE
# ============================================================


class TestSchedulerPause:
    def test_active_promise_cancels_reminders(self):
        """Active promise causes reminders to be cancelled."""
        from app.services.scheduler import process_single_action
        from app.crud.scheduled_action import create_scheduled_action
        from app.schemas.scheduled_action import ScheduledActionCreate

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        # Create a promise
        create_promise_for_case(db, case.id)

        # Create a new scheduled action
        action = create_scheduled_action(
            db,
            data=ScheduledActionCreate(
                recovery_case_id=case.id,
                action_type="reminder_1",
                attempt_number=2,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),  # due now
            ),
        )

        detail = process_single_action(db, action)

        assert detail["result"] == "cancelled"
        assert detail["reason"] == "active_promise_exists"
        db.close()

    def test_no_promise_allows_reminders(self):
        """Without active promise, reminders execute normally."""
        from app.services.scheduler import process_single_action
        from app.crud.scheduled_action import create_scheduled_action
        from app.schemas.scheduled_action import ScheduledActionCreate

        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

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

        assert detail["result"] == "executed"
        db.close()


# ============================================================
# PROMISE STATUS
# ============================================================


class TestPromiseStatus:
    def test_status_with_active_promise(self):
        """Get status with active promise."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id, customer_message="I'll pay")

        status = get_promise_status(db, case.id)

        assert status["has_active_promise"] is True
        assert status["amount_promised"] == 50000
        assert status["customer_message"] == "I'll pay"
        assert status["active_count"] == 1
        db.close()

    def test_status_without_promise(self):
        """Get status without active promise."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        status = get_promise_status(db, case.id)

        assert status["has_active_promise"] is False
        assert status["total_promises"] == 0
        db.close()

    def test_status_counts(self):
        """Status includes correct counts."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        # Create and fulfill one promise on case1
        result1 = create_promise_for_case(db, case.id)
        case.status = RecoveryStatus.PROMISED
        db.commit()
        fulfill_promise(db, case.id, 50000)

        # Create active promise on a different case
        case2, customer2 = setup_case_with_schedule(db)
        create_promise_for_case(db, case2.id)

        # Check counts for case1 (fulfilled only)
        status1 = get_promise_status(db, case.id)
        assert status1["active_count"] == 0
        assert status1["fulfilled_count"] == 1
        assert status1["missed_count"] == 0

        # Check counts for case2 (active only)
        status2 = get_promise_status(db, case2.id)
        assert status2["active_count"] == 1
        assert status2["fulfilled_count"] == 0
        assert status2["missed_count"] == 0
        db.close()


# ============================================================
# DASHBOARD
# ============================================================


class TestDashboard:
    def test_dashboard_data(self):
        """Dashboard shows promised revenue data."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        create_promise_for_case(db, case.id)

        data = get_dashboard_data(db)

        assert data["metrics"]["active_count"] == 1
        assert data["metrics"]["total_promised_amount"] == 50000
        assert len(data["promises"]) == 1
        db.close()

    def test_dashboard_fulfillment_rate(self):
        """Dashboard calculates fulfillment rate."""
        db = TestSessionLocal()
        case1, customer1 = setup_case_with_schedule(db)

        # Fulfill one promise
        result1 = create_promise_for_case(db, case1.id)
        case1.status = RecoveryStatus.PROMISED
        db.commit()
        fulfill_promise(db, case1.id, 50000)

        # Miss another promise
        case2, customer2 = setup_case_with_schedule(db)
        result2 = create_promise_for_case(db, case2.id)
        case2.status = RecoveryStatus.PROMISED
        db.commit()

        promise2 = get_promise(db, uuid.UUID(result2["promise_id"]))
        promise2.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        check_and_expire_promises(db)

        data = get_dashboard_data(db)

        assert data["metrics"]["fulfilled_count"] == 1
        assert data["metrics"]["missed_count"] == 1
        assert data["metrics"]["fulfillment_rate"] == 50.0
        db.close()

    def test_dashboard_empty(self):
        """Dashboard works with no promises."""
        db = TestSessionLocal()

        data = get_dashboard_data(db)

        assert data["metrics"]["active_count"] == 0
        assert data["metrics"]["total_promised_amount"] == 0
        assert data["promises"] == []
        db.close()


# ============================================================
# EDGE CASES
# ============================================================


class TestEdgeCases:
    def test_promise_default_date(self):
        """Default promised date is tomorrow 18:00 UTC."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        result = create_promise_for_case(db, case.id)

        promise = get_promise(db, uuid.UUID(result["promise_id"]))
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        assert promise.promised_date.day == tomorrow.day
        assert promise.promised_date.hour == 18
        db.close()

    def test_promise_default_window(self):
        """Default promise window is 72 hours."""
        db = TestSessionLocal()
        case, customer = setup_case_with_schedule(db)

        result = create_promise_for_case(db, case.id)

        promise = get_promise(db, uuid.UUID(result["promise_id"]))
        assert promise.promise_window_hours == 72

        # Expiry should be promised_date + 72 hours
        expected_expiry = promise.promised_date + timedelta(hours=72)
        assert promise.expires_at == expected_expiry
        db.close()

    def test_multiple_cases_independent_promises(self):
        """Different cases can have independent promises."""
        db = TestSessionLocal()
        case1, customer1 = setup_case_with_schedule(db)
        case2, customer2 = setup_case_with_schedule(db)

        result1 = create_promise_for_case(db, case1.id)
        result2 = create_promise_for_case(db, case2.id)

        assert result1["promise_id"] != result2["promise_id"]

        status1 = get_promise_status(db, case1.id)
        status2 = get_promise_status(db, case2.id)

        assert status1["has_active_promise"] is True
        assert status2["has_active_promise"] is True
        db.close()

    def test_promise_amount_matches_case(self):
        """Promise amount matches the case original amount."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, original_amount=149900
        )

        result = create_promise_for_case(db, case.id)

        assert result["amount_promised"] == 149900
        db.close()
