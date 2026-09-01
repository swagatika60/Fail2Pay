"""Tests for the deterministic Recovery Workflow Engine.

Covers:
- State machine transitions
- Start recovery (AT_RISK → RECOVERY_IN_PROGRESS)
- Record attempt (result-based transitions)
- Mark payment received (amount updates + state transitions)
- Stop recovery (hard stop conditions)
- Mark lost
- Workflow status query
- Stop conditions: max attempts, deadline, payment succeeded
- Terminal state handling (no transitions from RECOVERED/LOST/STOPPED)
- Audit trail for all transitions
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.audit_event import AuditEvent
from app.models.recovery_attempt import RecoveryAttempt
from app.schemas.customer import CustomerCreate
from app.schemas.revenue_event import RevenueEventCreate
from app.schemas.recovery_case import RecoveryCaseCreate
from app.services.workflow_engine import (
    can_transition,
    start_recovery,
    record_attempt,
    mark_payment_received,
    stop_recovery,
    mark_lost,
    get_workflow_status,
    VALID_TRANSITIONS,
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
    import app.models  # noqa: F401 - ensure all models are registered

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# --- Helpers ---

def create_test_customer(db) -> Customer:
    """Create a test customer."""
    customer = Customer(
        external_id="cust_test_001",
        email="test@example.com",
        phone="+911234567890",
        name="Test Customer",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def create_test_revenue_event(db, customer: Customer, amount: int = 50000) -> RevenueEvent:
    """Create a test revenue event."""
    event = RevenueEvent(
        customer_id=customer.id,
        event_type="payment_failed",
        amount=amount,
        currency="INR",
        source="razorpay",
        status="failed",
        external_event_id=f"pay_test_{uuid.uuid4().hex[:8]}",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_test_recovery_case(
    db, customer: Customer, revenue_event: RevenueEvent,
    status: RecoveryStatus = RecoveryStatus.AT_RISK,
    original_amount: int = 50000,
    attempt_count: int = 0,
    max_attempts: int = 5,
    recovery_deadline: datetime | None = None,
) -> RecoveryCase:
    """Create a test recovery case."""
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


# --- State transition validity tests ---

class TestStateTransitionRules:
    def test_at_risk_can_transition_to_recovery_in_progress(self):
        assert can_transition(RecoveryStatus.AT_RISK, RecoveryStatus.RECOVERY_IN_PROGRESS)

    def test_at_risk_can_transition_to_stopped(self):
        assert can_transition(RecoveryStatus.AT_RISK, RecoveryStatus.STOPPED)

    def test_at_risk_can_transition_to_lost(self):
        assert can_transition(RecoveryStatus.AT_RISK, RecoveryStatus.LOST)

    def test_at_risk_cannot_transition_to_recovered(self):
        assert not can_transition(RecoveryStatus.AT_RISK, RecoveryStatus.RECOVERED)

    def test_at_risk_cannot_transition_to_promised(self):
        assert not can_transition(RecoveryStatus.AT_RISK, RecoveryStatus.PROMISED)

    def test_recovery_in_progress_can_go_to_promised(self):
        assert can_transition(RecoveryStatus.RECOVERY_IN_PROGRESS, RecoveryStatus.PROMISED)

    def test_recovery_in_progress_can_go_to_stopped(self):
        assert can_transition(RecoveryStatus.RECOVERY_IN_PROGRESS, RecoveryStatus.STOPPED)

    def test_recovery_in_progress_can_go_to_lost(self):
        assert can_transition(RecoveryStatus.RECOVERY_IN_PROGRESS, RecoveryStatus.LOST)

    def test_recovery_in_progress_cannot_go_to_recovered(self):
        assert not can_transition(RecoveryStatus.RECOVERY_IN_PROGRESS, RecoveryStatus.RECOVERED)

    def test_promised_can_go_to_scheduled(self):
        assert can_transition(RecoveryStatus.PROMISED, RecoveryStatus.SCHEDULED)

    def test_promised_can_go_back_to_recovery_in_progress(self):
        """If promise is broken, go back to RECOVERY_IN_PROGRESS."""
        assert can_transition(RecoveryStatus.PROMISED, RecoveryStatus.RECOVERY_IN_PROGRESS)

    def test_scheduled_can_go_to_partially_recovered(self):
        assert can_transition(RecoveryStatus.SCHEDULED, RecoveryStatus.PARTIALLY_RECOVERED)

    def test_scheduled_can_go_to_recovered(self):
        assert can_transition(RecoveryStatus.SCHEDULED, RecoveryStatus.RECOVERED)

    def test_scheduled_can_go_back_to_recovery_in_progress(self):
        """If scheduled payment fails, go back."""
        assert can_transition(RecoveryStatus.SCHEDULED, RecoveryStatus.RECOVERY_IN_PROGRESS)

    def test_partially_recovered_can_go_to_recovered(self):
        assert can_transition(RecoveryStatus.PARTIALLY_RECOVERED, RecoveryStatus.RECOVERED)

    def test_partially_recovered_can_go_to_recovery_in_progress(self):
        assert can_transition(RecoveryStatus.PARTIALLY_RECOVERED, RecoveryStatus.RECOVERY_IN_PROGRESS)

    def test_recovered_is_terminal(self):
        """No transitions from RECOVERED."""
        assert len(VALID_TRANSITIONS[RecoveryStatus.RECOVERED]) == 0

    def test_lost_is_terminal(self):
        """No transitions from LOST."""
        assert len(VALID_TRANSITIONS[RecoveryStatus.LOST]) == 0

    def test_stopped_permits_customer_re_engagement(self):
        """STOPPED cases can only be re-opened to PROMISED or RECOVERY_IN_PROGRESS
        when the customer voluntarily re-engages. It never transitions to
        terminal success/failure states directly."""
        allowed = VALID_TRANSITIONS[RecoveryStatus.STOPPED]
        assert RecoveryStatus.PROMISED in allowed
        assert RecoveryStatus.RECOVERY_IN_PROGRESS in allowed
        assert RecoveryStatus.RECOVERED not in allowed
        assert RecoveryStatus.LOST not in allowed
        assert RecoveryStatus.STOPPED not in allowed


# --- Start Recovery tests ---

class TestStartRecovery:
    def test_start_recovery_transitions_to_in_progress(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = start_recovery(db, case.id)

        assert result["status"] == "transitioned"
        assert result["to"] == "RECOVERY_IN_PROGRESS"

        # Verify in DB
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERY_IN_PROGRESS
        assert case.recovery_started_at is not None
        db.close()

    def test_start_recovery_creates_audit_event(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        start_recovery(db, case.id)

        audit = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id
        ).first()
        assert audit is not None
        assert audit.action == "status_changed"
        assert audit.old_value["status"] == "AT_RISK"
        assert audit.new_value["status"] == "RECOVERY_IN_PROGRESS"
        assert audit.extra_data["action"] == "start_recovery"
        db.close()

    def test_start_recovery_skips_terminal_case(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, status=RecoveryStatus.RECOVERED)

        result = start_recovery(db, case.id)
        assert result["status"] == "skipped"
        assert "terminal" in result["reason"]

    def test_start_recovery_error_for_nonexistent_case(self):
        db = TestSessionLocal()
        result = start_recovery(db, uuid.uuid4())
        assert result["status"] == "error"
        assert result["reason"] == "case_not_found"

    def test_start_recovery_stops_if_deadline_reached(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        # Set deadline in the past
        past_deadline = datetime.now(timezone.utc) - timedelta(days=1)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            recovery_deadline=past_deadline,
        )

        result = start_recovery(db, case.id)

        assert result["status"] == "stopped"
        assert result["reason"] == "recovery_deadline_reached"

        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        assert case.closed_at is not None
        db.close()


# --- Record Attempt tests ---

class TestRecordAttempt:
    def _setup_case(self, status=RecoveryStatus.RECOVERY_IN_PROGRESS, max_attempts=5):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, status=status, max_attempts=max_attempts)
        return db, case

    def test_record_attempt_promised(self):
        db, case = self._setup_case()

        result = record_attempt(db, case.id, channel="whatsapp", result="promised")

        assert result["status"] == "recorded"
        assert result["new_status"] == "PROMISED"
        assert result["attempt_number"] == 1

        db.refresh(case)
        assert case.status == RecoveryStatus.PROMISED
        assert case.attempt_count == 1

        # Verify recovery attempt was created
        attempt = db.query(RecoveryAttempt).filter(
            RecoveryAttempt.recovery_case_id == case.id
        ).first()
        assert attempt is not None
        assert attempt.channel == "whatsapp"
        assert attempt.result == "promised"
        assert attempt.attempt_number == 1
        db.close()

    def test_record_attempt_paid(self):
        db, case = self._setup_case()

        result = record_attempt(db, case.id, channel="email", result="paid")

        assert result["new_status"] == "RECOVERED"
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        assert case.closed_at is not None
        db.close()

    def test_record_attempt_partial_paid(self):
        db, case = self._setup_case()

        result = record_attempt(db, case.id, channel="sms", result="partial_paid")

        assert result["new_status"] == "PARTIALLY_RECOVERED"
        db.refresh(case)
        assert case.status == RecoveryStatus.PARTIALLY_RECOVERED
        db.close()

    def test_record_attempt_no_response_stays_in_progress(self):
        db, case = self._setup_case()

        result = record_attempt(db, case.id, channel="whatsapp", result="no_response")

        assert result["new_status"] == "RECOVERY_IN_PROGRESS"
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERY_IN_PROGRESS
        db.close()

    def test_record_attempt_failed_stays_in_progress(self):
        db, case = self._setup_case()

        result = record_attempt(db, case.id, channel="email", result="failed")

        assert result["new_status"] == "RECOVERY_IN_PROGRESS"
        db.close()

    def test_record_attempt_creates_audit_event(self):
        db, case = self._setup_case()

        record_attempt(db, case.id, channel="whatsapp", result="promised")

        audit = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id
        ).first()
        assert audit is not None
        assert audit.action == "status_changed"
        assert audit.extra_data["action"] == "attempt_promised"
        db.close()

    def test_record_attempt_increments_count(self):
        db, case = self._setup_case()

        record_attempt(db, case.id, channel="whatsapp", result="no_response")
        record_attempt(db, case.id, channel="email", result="no_response")
        record_attempt(db, case.id, channel="sms", result="promised")

        db.refresh(case)
        assert case.attempt_count == 3
        db.close()

    def test_record_attempt_stops_at_max_attempts(self):
        """When max_attempts is reached, case transitions to STOPPED."""
        db, case = self._setup_case(max_attempts=3)
        case.attempt_count = 2  # Already 2 attempts
        db.commit()
        db.refresh(case)

        result = record_attempt(db, case.id, channel="whatsapp", result="no_response")

        assert result["status"] == "stopped"
        assert result["reason"] == "maximum_attempts_reached"

        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        db.close()

    def test_record_attempt_skips_terminal_case(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, status=RecoveryStatus.RECOVERED)

        result = record_attempt(db, case.id, channel="email", result="paid")
        assert result["status"] == "skipped"
        assert "terminal" in result["reason"]
        db.close()

    def test_record_attempt_stops_on_deadline(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        past_deadline = datetime.now(timezone.utc) - timedelta(days=1)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            status=RecoveryStatus.RECOVERY_IN_PROGRESS,
            recovery_deadline=past_deadline,
        )

        result = record_attempt(db, case.id, channel="whatsapp", result="no_response")
        assert result["status"] == "stopped"
        assert result["reason"] == "recovery_deadline_reached"
        db.close()


# --- Mark Payment Received tests ---

class TestMarkPaymentReceived:
    def _setup_case(self, original_amount=50000, status=RecoveryStatus.RECOVERY_IN_PROGRESS):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            status=status,
            original_amount=original_amount,
        )
        return db, case

    def test_full_payment_marks_recovered(self):
        """A full payment credits the balance but RECOVERED comes only from the
        verified finalizer (a case may become RECOVERED only via a verified
        payment.captured event)."""
        from app.services.workflow_engine import finalize_recovered_case
        db, case = self._setup_case(original_amount=50000)

        result = mark_payment_received(db, case.id, amount=50000)

        # Amounts are credited and the balance is reported fully recovered, but
        # the bare credit is NOT permitted to flip the case to terminal RECOVERED.
        assert result["status"] == "updated"
        assert result["fully_recovered"] is True
        assert result["recovered_amount"] == 50000
        assert result["remaining_amount"] == 0

        db.refresh(case)
        assert case.status != RecoveryStatus.RECOVERED

        # The verified transition (what a payment.captured webhook runs) finalizes it.
        finalize_recovered_case(db, case, reason="test")
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        assert case.closed_at is not None
        db.close()

    def test_partial_payment_marks_partially_recovered(self):
        db, case = self._setup_case(original_amount=50000)

        result = mark_payment_received(db, case.id, amount=20000)

        assert result["fully_recovered"] is False
        assert result["recovered_amount"] == 20000
        assert result["remaining_amount"] == 30000
        assert result["new_status"] == "PARTIALLY_RECOVERED"

        db.refresh(case)
        assert case.status == RecoveryStatus.PARTIALLY_RECOVERED
        assert case.closed_at is None
        db.close()

    def test_multiple_partial_payments_sum_correctly(self):
        db, case = self._setup_case(original_amount=100000)

        mark_payment_received(db, case.id, amount=30000)
        mark_payment_received(db, case.id, amount=40000)

        db.refresh(case)
        assert case.recovered_amount == 70000
        assert case.remaining_amount == 30000
        assert case.status == RecoveryStatus.PARTIALLY_RECOVERED
        db.close()

    def test_overpayment_marks_recovered(self):
        """Overpayment zeroes the balance, but terminal RECOVERED only comes from
        the verified finalizer."""
        from app.services.workflow_engine import finalize_recovered_case
        db, case = self._setup_case(original_amount=50000)

        result = mark_payment_received(db, case.id, amount=60000)

        assert result["fully_recovered"] is True
        assert result["remaining_amount"] == 0
        db.refresh(case)
        assert case.status != RecoveryStatus.RECOVERED

        finalize_recovered_case(db, case, reason="test")
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        db.close()

    def test_mark_payment_creates_audit_event(self):
        db, case = self._setup_case(original_amount=50000)

        mark_payment_received(db, case.id, amount=50000)

        audit = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id
        ).first()
        assert audit is not None
        assert audit.action == "status_changed"
        assert audit.extra_data["action"] == "payment_received"
        assert audit.extra_data["recovered_amount"] == 50000
        db.close()

    def test_mark_payment_skips_terminal_case(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            status=RecoveryStatus.RECOVERED,
        )

        result = mark_payment_received(db, case.id, amount=50000)
        assert result["status"] == "skipped"
        assert "terminal" in result["reason"]
        db.close()


# --- Stop Recovery tests ---

class TestStopRecovery:
    def test_stop_recovery_transitions_to_stopped(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = stop_recovery(db, case.id, reason="customer_requested_stop")

        assert result["status"] == "stopped"
        assert result["reason"] == "customer_requested_stop"
        assert result["to"] == "STOPPED"

        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        assert case.closed_at is not None
        db.close()

    def test_stop_recovery_creates_audit_event(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        stop_recovery(db, case.id, reason="merchant_disabled")

        audit = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id
        ).first()
        assert audit is not None
        assert "stop_merchant_disabled" in audit.extra_data["action"]
        db.close()

    def test_stop_recovery_skips_terminal_case(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, status=RecoveryStatus.RECOVERED)

        result = stop_recovery(db, case.id, reason="customer_requested_stop")
        assert result["status"] == "skipped"
        db.close()

    def test_stop_recovery_error_for_nonexistent_case(self):
        db = TestSessionLocal()
        result = stop_recovery(db, uuid.uuid4(), reason="test")
        assert result["status"] == "error"
        db.close()


# --- Mark Lost tests ---

class TestMarkLost:
    def test_mark_lost_transitions_to_lost(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = mark_lost(db, case.id, reason="all_attempts_exhausted")

        assert result["status"] == "transitioned"
        assert result["to"] == "LOST"

        db.refresh(case)
        assert case.status == RecoveryStatus.LOST
        assert case.closed_at is not None
        db.close()

    def test_mark_lost_creates_audit_event(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        mark_lost(db, case.id, reason="recovery_failed")

        audit = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id
        ).first()
        assert audit is not None
        assert "mark_lost_recovery_failed" in audit.extra_data["action"]
        db.close()

    def test_mark_lost_skips_terminal_case(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, status=RecoveryStatus.STOPPED)

        result = mark_lost(db, case.id)
        assert result["status"] == "skipped"
        db.close()


# --- Workflow Status tests ---

class TestWorkflowStatus:
    def test_workflow_status_returns_current_state(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = get_workflow_status(db, case.id)

        assert result["current_status"] == "AT_RISK"
        assert result["is_terminal"] is False
        assert result["attempt_count"] == 0
        assert result["max_attempts"] == 5
        assert result["recovered_amount"] == 0
        assert result["remaining_amount"] == 50000
        assert result["original_amount"] == 50000
        assert "RECOVERY_IN_PROGRESS" in result["valid_next_states"]
        assert "STOPPED" in result["valid_next_states"]
        db.close()

    def test_workflow_status_terminal_case(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, status=RecoveryStatus.RECOVERED)

        result = get_workflow_status(db, case.id)

        assert result["is_terminal"] is True
        assert result["valid_next_states"] == []
        db.close()

    def test_workflow_status_includes_dates(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        deadline = datetime.now(timezone.utc) + timedelta(days=7)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            recovery_deadline=deadline,
        )
        # Start recovery to set recovery_started_at
        start_recovery(db, case.id)

        result = get_workflow_status(db, case.id)

        assert result["recovery_started_at"] is not None
        assert result["recovery_deadline"] is not None
        db.close()

    def test_workflow_status_error_for_nonexistent_case(self):
        db = TestSessionLocal()
        result = get_workflow_status(db, uuid.uuid4())
        assert result["status"] == "error"
        db.close()


# --- Full workflow lifecycle tests ---

class TestFullWorkflowLifecycle:
    def test_full_lifecycle_at_risk_to_recovered(self):
        """Test the complete happy path: AT_RISK → RECOVERY_IN_PROGRESS → PROMISED → RECOVERED."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # 1. Start recovery
        result = start_recovery(db, case.id)
        assert result["status"] == "transitioned"
        assert result["to"] == "RECOVERY_IN_PROGRESS"

        # 2. First attempt - customer promises
        result = record_attempt(db, case.id, channel="whatsapp", result="promised")
        assert result["new_status"] == "PROMISED"

        # 3. Customer pays (verified capture) → amounts credited, then finalized
        result = mark_payment_received(db, case.id, amount=50000)
        assert result["fully_recovered"] is True
        assert result["new_status"] != "RECOVERED"  # only the verified finalizer flips it

        from app.services.workflow_engine import finalize_recovered_case
        finalize_recovered_case(db, case, reason="payment_captured")

        # Verify final state
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        assert case.recovered_amount == 50000
        assert case.remaining_amount == 0
        assert case.closed_at is not None

        # Verify audit trail exists
        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id
        ).all()
        assert len(audits) >= 3  # start + attempt + payment
        db.close()

    def test_lifecycle_at_risk_to_lost(self):
        """Test: AT_RISK → RECOVERY_IN_PROGRESS → LOST."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event,
            max_attempts=2,
        )

        start_recovery(db, case.id)
        record_attempt(db, case.id, channel="email", result="no_response")
        record_attempt(db, case.id, channel="whatsapp", result="no_response")

        # Max attempts reached → STOPPED
        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        db.close()

    def test_lifecycle_manual_stop(self):
        """Test: AT_RISK → RECOVERY_IN_PROGRESS → STOPPED (customer opt-out)."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        start_recovery(db, case.id)
        result = stop_recovery(db, case.id, reason="customer_opted_out")

        assert result["status"] == "stopped"
        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        db.close()

    def test_lifecycle_partial_recovery_then_recovered(self):
        """Test: RECOVERY_IN_PROGRESS → PARTIALLY_RECOVERED → RECOVERED."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event, original_amount=100000)

        start_recovery(db, case.id)

        # Partial payment
        mark_payment_received(db, case.id, amount=40000)
        db.refresh(case)
        assert case.status == RecoveryStatus.PARTIALLY_RECOVERED

        # Continue recovery
        record_attempt(db, case.id, channel="email", result="no_response")

        # Remaining payment (verified capture) → amounts credited, then finalized
        result = mark_payment_received(db, case.id, amount=60000)
        assert result["fully_recovered"] is True
        db.refresh(case)
        # The credit zeroes the balance but does NOT self-escalate to RECOVERED;
        # that terminal transition belongs to the verified finalizer.
        assert case.status != RecoveryStatus.RECOVERED

        from app.services.workflow_engine import finalize_recovered_case
        finalize_recovered_case(db, case, reason="payment_captured")
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        assert case.recovered_amount == 100000
        assert case.remaining_amount == 0
        db.close()
