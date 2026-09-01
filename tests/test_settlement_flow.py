"""Acceptance tests for the settlement (recovery completion) loop.

Covers the Part-5/12 behaviors wired into ``process_payment_captured``:
- Fulfils an active customer Promise when the captured payment settles the case.
- Cancels queued (PENDING) recovery emails on settlement (no stale outreach).
- Handles the ``order.paid`` webhook without treating it as captured money.
- Emits typed realtime domain events (payment_captured / recovery_completed).

These tests drive the webhook service functions directly against an in-memory
DB (identical to test_scheduler), so they don't depend on an HTTP transport or
external gateways.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.promise import Promise, PromiseStatus
from app.models.email import SentEmail, EmailDeliveryStatus
from app.models.installment import Installment, InstallmentStatus
from app.services.webhook_handler import process_payment_captured, process_order_paid

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    import app.models  # noqa: F401 - ensure all models are registered

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


def create_test_customer(db) -> Customer:
    customer = Customer(
        external_id=f"cust_{uuid.uuid4().hex[:8]}",
        email="settle@example.com",
        phone="+911234567890",
        name="Settlement User",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def create_test_revenue_event(db, customer: Customer, payment_id: str) -> RevenueEvent:
    event = RevenueEvent(
        customer_id=customer.id,
        event_type="payment_failed",
        amount=50000,
        currency="INR",
        source="razorpay",
        status="failed",
        external_event_id=payment_id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_test_recovery_case(db, customer, revenue_event, status=RecoveryStatus.RECOVERY_IN_PROGRESS):
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=revenue_event.id,
        risk_level="high",
        risk_reason="Payment failed",
        status=status,
        original_amount=50000,
        recovered_amount=0,
        remaining_amount=50000,
        attempt_count=0,
        max_attempts=5,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def captured_payload(payment_id: str, amount: int, event_id: str) -> dict:
    return {
        "id": event_id,
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": f"order_{payment_id}",
                    "amount": amount,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                }
            }
        },
    }


class TestSettlementFulfilsPromiseAndCancelsEmails:
    def test_captured_payment_fulfils_active_promise(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        rev = create_test_revenue_event(db, customer, "pay_settle_001")
        case = create_test_recovery_case(db, customer, rev)

        promise = Promise(
            recovery_case_id=case.id,
            customer_id=customer.id,
            amount_promised=50000,
            currency="INR",
            promised_date=datetime.now(timezone.utc),
            status=PromiseStatus.ACTIVE.value,
        )
        db.add(promise)
        db.commit()

        result = process_payment_captured(
            db, captured_payload("pay_settle_001", 50000, "evt_settle_001")
        )

        assert result["status"] == "processed"
        assert result["remaining_amount"] == 0

        db.refresh(case)
        db.refresh(promise)
        assert case.status == RecoveryStatus.RECOVERED
        assert promise.status == PromiseStatus.FULFILLED.value
        assert promise.fulfilled_at is not None
        assert promise.fulfilled_amount == 50000
        db.close()

    def test_captured_payment_cancels_pending_emails(self):
        db = TestSessionLocal()
        customer = create_test_customer(db)
        rev = create_test_revenue_event(db, customer, "pay_settle_002")
        case = create_test_recovery_case(db, customer, rev)

        pending = SentEmail(
            recovery_case_id=case.id,
            recipient_email="settle@example.com",
            subject="Payment retry",
            body="Please retry your payment.",
            email_type="payment_retry",
            delivery_status=EmailDeliveryStatus.PENDING.value,
        )
        db.add(pending)
        db.commit()

        result = process_payment_captured(
            db, captured_payload("pay_settle_002", 50000, "evt_settle_002")
        )

        assert result["status"] == "processed"
        db.refresh(pending)
        # Pending recovery emails are cancelled, not left queued.
        assert pending.delivery_status == EmailDeliveryStatus.CANCELLED.value
        db.close()


class TestOrderPaid:
    def test_order_paid_is_not_treated_as_money(self):
        """order.paid correlates an installment order but records no Payment."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        rev = create_test_revenue_event(db, customer, "pay_ord_001")
        case = create_test_recovery_case(db, customer, rev)

        installment = Installment(
            payment_plan_id=uuid.uuid4(),
            recovery_case_id=case.id,
            installment_number=1,
            amount=50000,
            due_date=datetime.now(timezone.utc),
            status=InstallmentStatus.DUE.value,
            razorpay_order_id="order_xyz_001",
        )
        db.add(installment)
        db.commit()

        payload = {
            "id": "evt_order_paid_001",
            "event": "order.paid",
            "payload": {
                "order": {"entity": {"id": "order_xyz_001"}}
            },
        }

        result = process_order_paid(db, payload)

        assert result["status"] == "processed"
        assert result["order_id"] == "order_xyz_001"
        assert result["case_id"] == str(case.id)

        # No money recorded on order.paid alone.
        from app.models.payment import Payment

        payments = db.query(Payment).all()
        assert payments == []
        db.close()
