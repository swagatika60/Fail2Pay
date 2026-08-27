"""Tests for the deterministic Revenue Risk Engine.

Tests every risk category with various scenarios to ensure
rule-based logic produces correct, auditable results.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

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


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    """Create all tables before each test, drop after."""
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


def _create_customer(db, external_id="cust_test_001"):
    """Helper to create a test customer."""
    from app.models.customer import Customer

    customer = Customer(
        external_id=external_id,
        email="test@example.com",
        phone="+911234567890",
        name="Test User",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def _create_revenue_event(db, customer_id, event_type="payment_failed", amount=50000, status="failed", extra_data=None):
    """Helper to create a test revenue event."""
    from app.models.revenue_event import RevenueEvent

    event = RevenueEvent(
        customer_id=customer_id,
        external_event_id=f"pay_{uuid.uuid4().hex[:8]}",
        event_type=event_type,
        amount=amount,
        currency="INR",
        status=status,
        source="razorpay",
        extra_data=extra_data or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _create_recovery_case(db, customer_id, revenue_event_id):
    """Helper to create a test recovery case."""
    from app.models.recovery_case import RecoveryCase, RecoveryStatus

    case = RecoveryCase(
        customer_id=customer_id,
        revenue_event_id=revenue_event_id,
        risk_level="HIGH",
        original_amount=50000,
        remaining_amount=50000,
        status=RecoveryStatus.AT_RISK,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ============================================================
# PAYMENT_FAILED tests
# ============================================================

class TestPaymentFailedRisk:
    def test_low_amount_is_low_risk(self):
        """Small payment failure should be LOW risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="payment_failed",
            amount=50000,  # ₹500
            extra_data={"failure_reason": "Insufficient funds"},
        )

        assert result.risk_level == "LOW"
        assert result.risk_category == "PAYMENT_FAILED"
        assert result.is_recoverable is True
        assert "low-value" in result.risk_reason.lower()
        db.close()

    def test_medium_amount_is_medium_risk(self):
        """Medium payment failure should be MEDIUM risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="payment_failed",
            amount=15_000_000,  # ₹1,50,000
            extra_data={"failure_reason": "Card declined"},
        )

        assert result.risk_level == "MEDIUM"
        assert result.risk_category == "PAYMENT_FAILED"
        assert result.is_recoverable is True
        assert "medium-value" in result.risk_reason.lower()
        db.close()

    def test_high_amount_is_high_risk(self):
        """Large payment failure should be HIGH risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="payment_failed",
            amount=100_000_000,  # ₹10,00,000
            extra_data={"failure_reason": "Payment gateway error"},
        )

        assert result.risk_level == "HIGH"
        assert result.risk_category == "PAYMENT_FAILED"
        assert result.is_recoverable is True
        assert "high-value" in result.risk_reason.lower()
        db.close()

    def test_frozen_account_is_not_recoverable(self):
        """Frozen account should be HIGH risk and not recoverable."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="payment_failed",
            amount=50000,
            extra_data={"failure_reason": "Frozen"},
        )

        assert result.risk_level == "HIGH"
        assert result.is_recoverable is False
        assert "frozen" in result.risk_reason.lower()
        db.close()

    def test_blocked_account_is_not_recoverable(self):
        """Blocked account should be HIGH risk and not recoverable."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="payment_failed",
            amount=50000,
            extra_data={"failure_reason": "Blocked"},
        )

        assert result.risk_level == "HIGH"
        assert result.is_recoverable is False
        assert "blocked" in result.risk_reason.lower()
        db.close()

    def test_fraud_is_not_recoverable(self):
        """Fraud detection should be HIGH risk and not recoverable."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="payment_failed",
            amount=50000,
            extra_data={"failure_code": "fraud_detected"},
        )

        assert result.risk_level == "HIGH"
        assert result.is_recoverable is False
        assert "fraud" in result.risk_reason.lower()
        db.close()

    def test_factors_include_amount_and_failure_info(self):
        """Risk assessment should include factors for traceability."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="payment_failed",
            amount=75000,
            extra_data={"failure_reason": "Insufficient funds", "failure_code": "card_error"},
        )

        assert result.factors is not None
        assert result.factors["amount"] == 75000
        assert result.factors["failure_reason"] == "insufficient funds"
        assert result.factors["failure_code"] == "card_error"
        db.close()


# ============================================================
# REPEATED_PAYMENT_FAILURE tests
# ============================================================

class TestRepeatedPaymentFailureRisk:
    def test_first_failure_is_low_risk(self):
        """First failure should be LOW risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="repeated_payment_failure",
            amount=50000,
        )

        assert result.risk_level == "LOW"
        assert result.risk_category == "REPEATED_PAYMENT_FAILURE"
        assert result.is_recoverable is True
        assert "first" in result.risk_reason.lower()
        db.close()

    def test_two_failures_is_medium_risk(self):
        """Two failures should be MEDIUM risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        # Create one past failure
        _create_revenue_event(db, customer.id, "payment_failed", 50000, "failed")

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="repeated_payment_failure",
            amount=50000,
        )

        assert result.risk_level == "MEDIUM"
        assert result.is_recoverable is True
        assert "2 payment failures" in result.risk_reason
        db.close()

    def test_three_failures_is_high_risk(self):
        """Three or more failures should be HIGH risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        # Create two past failures
        _create_revenue_event(db, customer.id, "payment_failed", 50000, "failed")
        _create_revenue_event(db, customer.id, "payment_failed", 50000, "failed")

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="repeated_payment_failure",
            amount=50000,
        )

        assert result.risk_level == "HIGH"
        assert result.is_recoverable is True
        assert "3 payment failures" in result.risk_reason
        db.close()

    def test_five_failures_is_not_recoverable(self):
        """5+ failures should be not recoverable."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        # Create four past failures
        for _ in range(4):
            _create_revenue_event(db, customer.id, "payment_failed", 50000, "failed")

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="repeated_payment_failure",
            amount=50000,
        )

        assert result.risk_level == "HIGH"
        assert result.is_recoverable is False
        assert "5 payment failures" in result.risk_reason
        assert "stopping" in result.risk_reason.lower()
        db.close()

    def test_factors_include_failure_count(self):
        """Factors should include failure count."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        # Create 2 past failures
        _create_revenue_event(db, customer.id, "payment_failed", 50000, "failed")
        _create_revenue_event(db, customer.id, "payment_failed", 50000, "failed")

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="repeated_payment_failure",
            amount=50000,
        )

        assert result.factors["failure_count"] == 3  # 2 past + 1 current
        db.close()


# ============================================================
# OVERDUE_INVOICE tests
# ============================================================

class TestOverdueInvoiceRisk:
    def test_recently_overdue_is_low_risk(self):
        """Invoice overdue by < 7 days should be LOW risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        due_date = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="overdue_invoice",
            amount=50000,
            extra_data={"due_date": due_date},
        )

        assert result.risk_level == "LOW"
        assert result.risk_category == "OVERDUE_INVOICE"
        assert result.is_recoverable is True
        assert "3 days" in result.risk_reason
        db.close()

    def test_medium_overdue_is_medium_risk(self):
        """Invoice overdue by 7-29 days should be MEDIUM risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        due_date = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="overdue_invoice",
            amount=50000,
            extra_data={"due_date": due_date},
        )

        assert result.risk_level == "MEDIUM"
        assert result.is_recoverable is True
        assert "15 days" in result.risk_reason
        db.close()

    def test_highly_overdue_is_high_risk(self):
        """Invoice overdue by >= 30 days should be HIGH risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        due_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="overdue_invoice",
            amount=50000,
            extra_data={"due_date": due_date},
        )

        assert result.risk_level == "HIGH"
        assert result.is_recoverable is True
        assert "45 days" in result.risk_reason
        db.close()

    def test_overdue_days_can_be_passed_directly(self):
        """overdue_days can be passed directly instead of due_date."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="overdue_invoice",
            amount=50000,
            extra_data={"overdue_days": 10},
        )

        assert result.risk_level == "MEDIUM"
        assert result.factors["overdue_days"] == 10
        db.close()

    def test_invoice_is_always_recoverable(self):
        """Overdue invoices are always recoverable."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        # Even 90 days overdue
        due_date = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="overdue_invoice",
            amount=50000,
            extra_data={"due_date": due_date},
        )

        assert result.is_recoverable is True
        db.close()

    def test_no_due_date_defaults_to_low_risk(self):
        """Missing due_date should default to LOW risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="overdue_invoice",
            amount=50000,
            extra_data={},
        )

        assert result.risk_level == "LOW"
        assert result.factors["overdue_days"] == 0
        db.close()


# ============================================================
# FAILED_SUBSCRIPTION tests
# ============================================================

class TestFailedSubscriptionRisk:
    def test_active_subscription_is_medium_risk(self):
        """Active subscription with failed payment should be MEDIUM risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="failed_subscription",
            amount=50000,
            extra_data={"subscription_status": "active"},
        )

        assert result.risk_level == "MEDIUM"
        assert result.risk_category == "FAILED_SUBSCRIPTION"
        assert result.is_recoverable is True
        assert "active" in result.risk_reason.lower()
        db.close()

    def test_cancelled_subscription_is_high_risk(self):
        """Cancelled subscription should be HIGH risk and not recoverable."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="failed_subscription",
            amount=50000,
            extra_data={"subscription_status": "cancelled"},
        )

        assert result.risk_level == "HIGH"
        assert result.is_recoverable is False
        assert "cancelled" in result.risk_reason.lower()
        db.close()

    def test_expired_subscription_is_high_risk(self):
        """Expired subscription should be HIGH risk and not recoverable."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="failed_subscription",
            amount=50000,
            extra_data={"subscription_status": "expired"},
        )

        assert result.risk_level == "HIGH"
        assert result.is_recoverable is False
        assert "expired" in result.risk_reason.lower()
        db.close()

    def test_past_due_subscription_is_low_risk(self):
        """Past due subscription should be LOW risk (grace period)."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="failed_subscription",
            amount=50000,
            extra_data={"subscription_status": "past_due"},
        )

        assert result.risk_level == "LOW"
        assert result.is_recoverable is True
        assert "grace" in result.risk_reason.lower()
        db.close()

    def test_unknown_subscription_status_is_medium(self):
        """Unknown subscription status should default to MEDIUM risk."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="failed_subscription",
            amount=50000,
            extra_data={"subscription_status": "something_weird"},
        )

        assert result.risk_level == "MEDIUM"
        assert result.is_recoverable is True
        db.close()

    def test_factors_include_subscription_info(self):
        """Factors should include subscription status and billing cycle."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="failed_subscription",
            amount=50000,
            extra_data={
                "subscription_status": "active",
                "billing_cycle": "monthly",
            },
        )

        assert result.factors["subscription_status"] == "active"
        assert result.factors["billing_cycle"] == "monthly"
        db.close()


# ============================================================
# Unknown event type tests
# ============================================================

class TestUnknownEventType:
    def test_unknown_event_returns_medium_risk(self):
        """Unknown event type should default to MEDIUM risk, not recoverable."""
        from app.services.revenue_risk import assess_risk

        db = TestSessionLocal()
        customer = _create_customer(db)

        result = assess_risk(
            db=db,
            customer_id=str(customer.id),
            revenue_event_id=str(uuid.uuid4()),
            event_type="some_new_event_type",
            amount=50000,
        )

        assert result.risk_level == "MEDIUM"
        assert result.risk_category == "UNKNOWN"
        assert result.is_recoverable is False
        assert "unknown event type" in result.risk_reason.lower()
        db.close()


# ============================================================
# Audit trail integration tests
# ============================================================

class TestRiskAuditTrail:
    def test_risk_assessment_logged_to_audit(self):
        """Every risk assessment should create an audit event."""
        from app.services.revenue_risk import assess_and_log_risk

        db = TestSessionLocal()
        customer = _create_customer(db)
        revenue_event = _create_revenue_event(db, customer.id)
        recovery_case = _create_recovery_case(db, customer.id, revenue_event.id)

        result = assess_and_log_risk(
            db=db,
            recovery_case_id=str(recovery_case.id),
            customer_id=str(customer.id),
            revenue_event_id=str(revenue_event.id),
            event_type="payment_failed",
            amount=50000,
            extra_data={"failure_reason": "Insufficient funds"},
        )

        assert "audit_event_id" in result
        assert result["audit_event_id"] is not None

        # Verify the audit event was created
        from app.models.audit_event import AuditEvent

        audit = db.query(AuditEvent).filter(
            AuditEvent.id == uuid.UUID(result["audit_event_id"])
        ).first()
        assert audit is not None
        assert audit.action == "risk_assessed"
        assert audit.entity_type == "risk_assessment"
        assert audit.new_value["risk_level"] == "LOW"
        assert audit.new_value["risk_category"] == "PAYMENT_FAILED"
        assert audit.new_value["is_recoverable"] is True
        db.close()

    def test_audit_includes_assessment_and_event_info(self):
        """Audit event should include both assessment result and event context."""
        from app.services.revenue_risk import assess_and_log_risk

        db = TestSessionLocal()
        customer = _create_customer(db)
        revenue_event = _create_revenue_event(db, customer.id, amount=15_000_000)
        recovery_case = _create_recovery_case(db, customer.id, revenue_event.id)

        result = assess_and_log_risk(
            db=db,
            recovery_case_id=str(recovery_case.id),
            customer_id=str(customer.id),
            revenue_event_id=str(revenue_event.id),
            event_type="payment_failed",
            amount=15_000_000,
            extra_data={"failure_reason": "Card expired"},
        )

        from app.models.audit_event import AuditEvent

        audit = db.query(AuditEvent).filter(
            AuditEvent.id == uuid.UUID(result["audit_event_id"])
        ).first()

        # Check extra_data has event context
        assert audit.extra_data["customer_id"] == str(customer.id)
        assert audit.extra_data["revenue_event_id"] == str(revenue_event.id)
        assert audit.extra_data["event_type"] == "payment_failed"
        assert audit.extra_data["amount"] == 15_000_000

        # Check new_value has assessment result
        assert audit.new_value["risk_level"] == "MEDIUM"
        assert audit.new_value["factors"]["amount"] == 15_000_000
        db.close()
