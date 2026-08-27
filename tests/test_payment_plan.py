"""Tests for Payment Plan Workflow.

Covers:
- Plan calculation and options
- Plan creation and customer agreement
- Installment record creation
- Installment payment tracking
- Installment failure handling
- Revenue map data
- Plan completion (all installments paid)
- Plan defaulting (too many failures)
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
from app.models.payment_plan import PaymentPlan, PaymentPlanStatus
from app.models.installment import Installment, InstallmentStatus
from app.schemas.payment_plan import PaymentPlanCreate
from app.schemas.installment import InstallmentCreate
from app.crud.payment_plan import (
    create_payment_plan,
    get_payment_plan,
    get_active_plan_for_case,
    accept_plan,
    activate_plan,
    create_installment,
    get_installments_for_plan,
    mark_installment_paid,
    mark_installment_failed,
    count_installments_by_status,
)
from app.services.payment_plan import (
    calculate_plan_options,
    create_payment_plan_for_case,
    accept_payment_plan,
    record_installment_payment,
    record_installment_failure,
    get_revenue_map,
    get_merchant_policy,
    FREQUENCIES,
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
        amount=1200000,
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
    original_amount=1200000,
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


def setup_case(db, original_amount=1200000):
    """Create a case for testing."""
    customer = create_test_customer(db)
    revenue_event = create_test_revenue_event(db, customer)
    case = create_test_recovery_case(db, customer, revenue_event, original_amount=original_amount)
    return case, customer


# ============================================================
# PLAN CALCULATION
# ============================================================


class TestPlanCalculation:
    def test_calculate_weekly_options(self):
        """Calculate weekly plan options for ₹12,000."""
        options = calculate_plan_options(1200000, "weekly")

        assert len(options) > 0
        for opt in options:
            assert opt["frequency"] == "weekly"
            assert opt["frequency_label"] == "Weekly"
            assert opt["installment_amount"] > 0
            assert opt["number_of_installments"] >= 2

    def test_calculate_monthly_options(self):
        """Calculate monthly plan options."""
        options = calculate_plan_options(1200000, "monthly")

        assert len(options) > 0
        for opt in options:
            assert opt["frequency"] == "monthly"
            assert opt["frequency_label"] == "Monthly"

    def test_calculate_biweekly_options(self):
        """Calculate biweekly plan options."""
        options = calculate_plan_options(1200000, "biweekly")

        assert len(options) > 0
        for opt in options:
            assert opt["frequency"] == "biweekly"

    def test_options_respect_min_installment(self):
        """Options don't include installments below minimum."""
        policy = get_merchant_policy()
        options = calculate_plan_options(1200000, "weekly")

        for opt in options:
            assert opt["installment_amount"] >= policy["min_installment_amount"]

    def test_options_respect_max_installments(self):
        """Options don't exceed max installments."""
        policy = get_merchant_policy()
        options = calculate_plan_options(1200000, "weekly")

        for opt in options:
            assert opt["number_of_installments"] <= policy["max_installments"]

    def test_small_amount_fewer_options(self):
        """Smaller amounts have fewer plan options."""
        options = calculate_plan_options(200000, "weekly")  # ₹2,000

        # Should have fewer options than ₹12,000
        assert len(options) <= 2


# ============================================================
# PLAN CREATION
# ============================================================


class TestPlanCreation:
    def test_create_payment_plan(self):
        """Create a payment plan for a recovery case."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,  # ₹3,000
            frequency="weekly",
        )

        assert result["status"] == "created"
        assert result["plan_id"] is not None
        assert result["total_amount"] == 1200000
        assert result["installment_amount"] == 300000
        assert result["number_of_installments"] == 4
        assert result["frequency"] == "weekly"
        assert result["installments_created"] == 4
        db.close()

    def test_plan_creates_installments(self):
        """Plan creation creates installment records."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
            frequency="weekly",
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        assert len(installments) == 4
        for i, inst in enumerate(installments):
            assert inst.installment_number == i + 1
            assert inst.status == InstallmentStatus.SCHEDULED.value
            assert inst.amount == 300000
        db.close()

    def test_plan_last_installment_gets_remainder(self):
        """Last installment gets the remainder amount."""
        db = TestSessionLocal()
        case, customer = setup_case(db, original_amount=1250000)  # ₹12,500

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
            frequency="weekly",
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        # ceiling(1250000 / 300000) = 5 installments
        # 4 × 300000 + 1 × 50000 = 1250000
        assert len(installments) == 5
        assert installments[-1].amount == 50000  # remainder
        total = sum(inst.amount for inst in installments)
        assert total == 1250000
        db.close()

    def test_plan_case_not_found(self):
        """Returns error for nonexistent case."""
        db = TestSessionLocal()

        result = create_payment_plan_for_case(
            db, uuid.uuid4(),
            installment_amount=300000,
        )

        assert result["status"] == "error"
        assert result["reason"] == "case_not_found"
        db.close()

    def test_plan_already_exists(self):
        """Cannot create second plan when one is active."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        create_payment_plan_for_case(db, case.id, installment_amount=300000)
        result2 = create_payment_plan_for_case(db, case.id, installment_amount=300000)

        assert result2["status"] == "skipped"
        assert result2["reason"] == "active_plan_exists"
        db.close()

    def test_plan_installment_too_small(self):
        """Returns error when installment is below minimum."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=50000,  # ₹500 — below minimum
        )

        assert result["status"] == "error"
        assert result["reason"] == "installment_too_small"
        db.close()

    def test_plan_creates_audit(self):
        """Plan creation creates an audit event."""
        from app.models.audit_event import AuditEvent

        db = TestSessionLocal()
        case, customer = setup_case(db)

        create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
            customer_message="Can I pay weekly?",
        )

        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "payment_plan_proposed",
        ).all()

        assert len(audits) == 1
        db.close()

    def test_plan_stores_customer_message(self):
        """Plan stores the customer's message."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
            customer_message="Can I pay ₹3,000 every week?",
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        assert plan.customer_message == "Can I pay ₹3,000 every week?"
        db.close()


# ============================================================
# PLAN ACCEPTANCE
# ============================================================


class TestPlanAcceptance:
    def test_accept_plan(self):
        """Customer accepts a proposed plan."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        accept_result = accept_payment_plan(db, case.id, uuid.UUID(result["plan_id"]))

        assert accept_result["status"] == "accepted"
        assert accept_result["plan_id"] == result["plan_id"]

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        assert plan.status == PaymentPlanStatus.ACTIVE.value
        assert plan.agreed_at is not None
        db.close()

    def test_accept_plan_wrong_case(self):
        """Cannot accept plan for wrong case."""
        db = TestSessionLocal()
        case1, _ = setup_case(db)
        case2, _ = setup_case(db)

        result = create_payment_plan_for_case(
            db, case1.id,
            installment_amount=300000,
        )

        accept_result = accept_payment_plan(db, case2.id, uuid.UUID(result["plan_id"]))

        assert accept_result["status"] == "error"
        assert accept_result["reason"] == "plan_does_not_match_case"
        db.close()

    def test_accept_plan_creates_audit(self):
        """Acceptance creates an audit event."""
        from app.models.audit_event import AuditEvent

        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        accept_payment_plan(db, case.id, uuid.UUID(result["plan_id"]))

        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "payment_plan_accepted",
        ).all()

        assert len(audits) == 1
        db.close()


# ============================================================
# INSTALLMENT PAYMENTS
# ============================================================


class TestInstallmentPayments:
    def test_record_payment(self):
        """Record payment for an installment."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        payment_result = record_installment_payment(
            db, installments[0].id, 300000,
            razorpay_payment_id="pay_test123",
        )

        assert payment_result["status"] == "paid"
        assert payment_result["amount"] == 300000

        # Verify installment is paid
        db.refresh(installments[0])
        assert installments[0].status == InstallmentStatus.PAID.value
        assert installments[0].paid_at is not None
        assert installments[0].razorpay_payment_id == "pay_test123"

        # Verify plan totals updated
        db.refresh(plan)
        assert plan.amount_paid == 300000
        assert plan.installments_paid == 1
        db.close()

    def test_record_payment_already_paid(self):
        """Cannot record payment for already-paid installment."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        record_installment_payment(db, installments[0].id, 300000)
        result2 = record_installment_payment(db, installments[0].id, 300000)

        assert result2["status"] == "skipped"
        assert result2["reason"] == "already_paid"
        db.close()

    def test_all_payments_completes_plan(self):
        """All installments paid → plan COMPLETED → case RECOVERED."""
        db = TestSessionLocal()
        case, customer = setup_case(db, original_amount=600000)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        # Pay all installments
        for inst in installments:
            record_installment_payment(db, inst.id, inst.amount)

        # Verify plan is completed
        db.refresh(plan)
        assert plan.status == PaymentPlanStatus.COMPLETED.value
        assert plan.installments_paid == 2
        assert plan.completed_at is not None

        # Verify case is recovered
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        assert case.recovered_amount == 600000
        assert case.remaining_amount == 0
        db.close()

    def test_partial_payments_track_correctly(self):
        """Partial payments track correctly."""
        db = TestSessionLocal()
        case, customer = setup_case(db, original_amount=1200000)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        # Pay 2 of 4 installments
        record_installment_payment(db, installments[0].id, 300000)
        record_installment_payment(db, installments[1].id, 300000)

        db.refresh(plan)
        assert plan.amount_paid == 600000
        assert plan.installments_paid == 2
        assert plan.status != PaymentPlanStatus.COMPLETED.value

        # Case should show partial recovery
        db.refresh(case)
        assert case.recovered_amount == 600000
        assert case.remaining_amount == 600000
        db.close()


# ============================================================
# INSTALLMENT FAILURES
# ============================================================


class TestInstallmentFailures:
    def test_record_failure(self):
        """Record failure for an installment."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        failure_result = record_installment_failure(
            db, installments[0].id,
            reason="insufficient_funds",
        )

        assert failure_result["status"] == "failed"
        assert failure_result["reason"] == "insufficient_funds"

        db.refresh(installments[0])
        assert installments[0].status == InstallmentStatus.FAILED.value
        assert installments[0].failed_at is not None
        assert installments[0].failure_reason == "insufficient_funds"

        db.refresh(plan)
        assert plan.installments_failed == 1
        db.close()

    def test_multiple_failures_default_plan(self):
        """Too many failures → plan DEFAULTED."""
        db = TestSessionLocal()
        case, customer = setup_case(db, original_amount=600000)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        # Fail both installments (50% of 2 = 1, so 2 failures triggers default)
        record_installment_failure(db, installments[0].id)
        record_installment_failure(db, installments[1].id)

        db.refresh(plan)
        assert plan.status == PaymentPlanStatus.DEFAULTED.value
        assert plan.installments_failed == 2
        db.close()

    def test_failure_creates_audit(self):
        """Failure creates an audit event."""
        from app.models.audit_event import AuditEvent

        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        record_installment_failure(db, installments[0].id)

        audits = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id,
            AuditEvent.action == "installment_failed",
        ).all()

        assert len(audits) == 1
        db.close()


# ============================================================
# REVENUE MAP
# ============================================================


class TestRevenueMap:
    def test_revenue_map_no_plan(self):
        """Revenue map without a plan."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        revenue_map = get_revenue_map(db, case.id)

        assert revenue_map["original_at_risk"] == 1200000
        assert revenue_map["paid"] == 0
        assert revenue_map["scheduled"] == 0
        assert revenue_map["remaining"] == 1200000
        assert revenue_map["plan"] is None
        assert revenue_map["installments"] == []
        db.close()

    def test_revenue_map_with_plan(self):
        """Revenue map with active plan."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        revenue_map = get_revenue_map(db, case.id)

        assert revenue_map["original_at_risk"] == 1200000
        assert revenue_map["plan"] is not None
        assert revenue_map["plan"]["installments_total"] == 4
        assert len(revenue_map["installments"]) == 4
        db.close()

    def test_revenue_map_after_payments(self):
        """Revenue map reflects payments."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        # Pay first installment
        record_installment_payment(db, installments[0].id, 300000)

        revenue_map = get_revenue_map(db, case.id)

        assert revenue_map["paid"] == 300000
        assert revenue_map["remaining"] == 900000
        assert revenue_map["scheduled"] == 900000  # 3 remaining installments
        db.close()

    def test_revenue_map_case_not_found(self):
        """Revenue map returns error for nonexistent case."""
        db = TestSessionLocal()

        revenue_map = get_revenue_map(db, uuid.uuid4())

        assert revenue_map["status"] == "error"
        db.close()


# ============================================================
# MERCHANT POLICY
# ============================================================


class TestMerchantPolicy:
    def test_default_policy(self):
        """Default merchant policy values."""
        policy = get_merchant_policy()

        assert policy["min_installments"] == 2
        assert policy["max_installments"] == 12
        assert policy["min_installment_amount"] == 100000
        assert "weekly" in policy["allowed_frequencies"]
        assert "monthly" in policy["allowed_frequencies"]

    def test_frequencies_defined(self):
        """All frequencies are defined."""
        assert "weekly" in FREQUENCIES
        assert "biweekly" in FREQUENCIES
        assert "monthly" in FREQUENCIES

        for freq, info in FREQUENCIES.items():
            assert "days" in info
            assert "label" in info
            assert info["days"] > 0


# ============================================================
# EDGE CASES
# ============================================================


class TestEdgeCases:
    def test_plan_for_terminal_case(self):
        """Cannot create plan for terminal case."""
        db = TestSessionLocal()
        case, customer = setup_case(db)
        case.status = RecoveryStatus.RECOVERED
        db.commit()

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        assert result["status"] == "skipped"
        assert "terminal" in result["reason"]
        db.close()

    def test_plan_with_custom_first_payment_date(self):
        """Plan with custom first payment date."""
        db = TestSessionLocal()
        case, customer = setup_case(db)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=300000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        installments = get_installments_for_plan(db, plan.id)

        # First installment should be ~1 week from now
        first_due = installments[0].due_date
        # Handle naive datetimes from SQLite
        if first_due.tzinfo is None:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            now = datetime.now(timezone.utc)
        days_until = (first_due - now).days
        assert 6 <= days_until <= 8
        db.close()

    def test_plan_amount_matches_case(self):
        """Plan total matches case original amount."""
        db = TestSessionLocal()
        case, customer = setup_case(db, original_amount=500000)

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=100000,
        )

        plan = get_payment_plan(db, uuid.UUID(result["plan_id"]))
        assert plan.total_amount == 500000
        db.close()

    def test_multiple_cases_independent_plans(self):
        """Different cases can have independent plans."""
        db = TestSessionLocal()
        case1, _ = setup_case(db)
        case2, _ = setup_case(db)

        result1 = create_payment_plan_for_case(
            db, case1.id, installment_amount=300000,
        )
        result2 = create_payment_plan_for_case(
            db, case2.id, installment_amount=200000,
        )

        assert result1["plan_id"] != result2["plan_id"]
        assert result1["installment_amount"] != result2["installment_amount"]
        db.close()
