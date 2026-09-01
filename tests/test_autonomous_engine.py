"""Tests for the autonomous recovery engine production hardening.

Covers:
- Loop termination on settlement: payment.captured -> RECOVERED, pending actions
  cancelled, and the reconciliation confirmation message is persisted + broadcast.
- Dispute / escalated-to-human guardrail: scheduled touchpoints are paused
  (cancelled) so the agent stops pinging a contested case.
- The background scheduler loop driver (``run_one_due_poll``) + poll factory.
- The next-touchpoint schedule endpoint (``/api/cases/{id}/schedule``).
- The manual ops scheduler run endpoint (``/api/autonomous/scheduler/run``).
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus

# --- shared in-memory DB ---

test_engine = create_engine(
    "sqlite://",
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
client = TestClient(app)


def _isolated_request(method: str, path: str, **kwargs):
    """Run one HTTP request against OUR in-memory DB, restoring whatever
    dependency override another test module had installed (so we never leak
    our engine into sibling modules that share the global overrides dict)."""
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    try:
        return getattr(client, method)(path, **kwargs)
    finally:
        if prev is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = prev


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    import app.models  # noqa: F401 - register all models

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# --- helpers ---


def create_customer(db) -> Customer:
    cust = Customer(
        external_id=f"cust_{uuid.uuid4().hex[:8]}",
        email="test@example.com",
        phone="+911234567890",
        name="Rahul Sharma",
    )
    db.add(cust)
    db.commit()
    db.refresh(cust)
    return cust


def create_revenue_event(db, customer, amount=50000, external_id=None) -> RevenueEvent:
    event = RevenueEvent(
        customer_id=customer.id,
        event_type="payment_failed",
        amount=amount,
        currency="INR",
        source="razorpay",
        status="failed",
        external_event_id=external_id or f"pay_{uuid.uuid4().hex[:8]}",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_case(
    db,
    status: RecoveryStatus = RecoveryStatus.RECOVERY_IN_PROGRESS,
    amount=50000,
    extra_data=None,
    payment_id=None,
) -> RecoveryCase:
    customer = create_customer(db)
    event = create_revenue_event(
        db, customer, amount=amount, external_id=payment_id
    )
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=event.id,
        risk_level="high",
        status=status,
        original_amount=amount,
        recovered_amount=0,
        remaining_amount=amount,
        attempt_count=0,
        max_attempts=5,
        extra_data=extra_data or {},
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def make_captured_payload(amount, event_id, payment_id):
    return {
        "id": event_id,
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": f"order_{uuid.uuid4().hex[:6]}",
                    "amount": amount,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                }
            }
        },
    }


def make_webhook_payload(event_type, amount=50000, event_id=None, payment_id=None):
    event_id = event_id or f"evt_{uuid.uuid4().hex[:8]}"
    payment_id = payment_id or f"pay_{uuid.uuid4().hex[:8]}"
    status = "failed" if "failed" in event_type else "captured"
    return {
        "id": event_id,
        "event": event_type,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": f"order_{uuid.uuid4().hex[:6]}",
                    "amount": amount,
                    "currency": "INR",
                    "status": status,
                    "method": "upi",
                    "email": "test@example.com",
                    "contact": "+911234567890",
                    "customer_id": f"cust_{uuid.uuid4().hex[:8]}",
                    "failure_reason": "Insufficient funds",
                    "failure_code": "PAYMENT_FAILED",
                }
            }
        },
    }


def get_outbound_messages(db, case_id):
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage
    from sqlalchemy import select

    conv = (
        db.execute(
            select(Conversation)
            .where(
                Conversation.recovery_case_id == case_id,
                Conversation.channel == "whatsapp",
            )
        ).scalars().first()
    )
    if not conv:
        return []
    return list(
        db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.created_at)
        ).scalars().all()
    )


# ============================================================
# SECTION 1: LOOP TERMINATION ON SETTLEMENT
# ============================================================


class TestSettlementConfirmation:
    def test_full_capture_marks_recovered_and_sends_confirmation(self):
        from app.services.webhook_handler import process_payment_captured

        db = TestSessionLocal()
        payment_id = f"pay_{uuid.uuid4().hex[:8]}"
        case = create_case(db, payment_id=payment_id)
        payload = make_captured_payload(case.original_amount, f"evt_{uuid.uuid4().hex[:6]}", payment_id)

        result = process_payment_captured(db, payload)

        assert result["status"] == "processed"
        assert result["remaining_amount"] == 0

        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        assert case.closed_at is not None

        # A reconciliation confirmation must have been written to the thread.
        outbound = get_outbound_messages(db, case.id)
        assert outbound, "expected a settlement confirmation message"
        confirmation = outbound[-1]
        assert "reconciled" in confirmation.content or "settled" in confirmation.content or "Thank you" in confirmation.content
        db.close()

    def test_capture_cancels_pending_actions(self):
        from app.crud.scheduled_action import create_scheduled_action
        from app.crud.scheduled_action import get_pending_actions_for_case
        from app.services.webhook_handler import process_payment_captured

        db = TestSessionLocal()
        payment_id = f"pay_{uuid.uuid4().hex[:8]}"
        case = create_case(db, payment_id=payment_id)
        create_scheduled_action(
            db,
            {
                "recovery_case_id": case.id,
                "action_type": "touchpoint_24h",
                "attempt_number": 1,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) + timedelta(hours=24),
            },
        )
        payload = make_captured_payload(case.original_amount, f"evt_{uuid.uuid4().hex[:6]}", payment_id)
        process_payment_captured(db, payload)
        assert get_pending_actions_for_case(db, case.id) == []
        db.close()

    def test_partial_capture_does_not_send_confirmation(self):
        from app.services.webhook_handler import process_payment_captured

        db = TestSessionLocal()
        payment_id = f"pay_{uuid.uuid4().hex[:8]}"
        case = create_case(db, amount=50000, payment_id=payment_id)
        payload = make_captured_payload(20000, f"evt_{uuid.uuid4().hex[:6]}", payment_id)

        result = process_payment_captured(db, payload)

        assert result["remaining_amount"] == 30000
        db.refresh(case)
        assert case.status == RecoveryStatus.PARTIALLY_RECOVERED

        outbound = get_outbound_messages(db, case.id)
        assert outbound == [], "partial capture must NOT send a reconciliation message"
        db.close()


# ============================================================
# SECTION 2: DISPUTE / ESCALATION GUARDRAIL
# ============================================================


class TestDisputeGuardrail:
    def test_escalated_to_human_cancels_due_touchpoint(self):
        from app.crud.scheduled_action import create_scheduled_action, get_scheduled_action
        from app.services.scheduler import process_single_action

        db = TestSessionLocal()
        case = create_case(db, extra_data={"escalated_to_human": True})
        action = create_scheduled_action(
            db,
            {
                "recovery_case_id": case.id,
                "action_type": "touchpoint_24h",
                "attempt_number": 1,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )

        detail = process_single_action(db, action)

        assert detail["result"] == "cancelled"
        assert detail["reason"] == "case_disputed_escalated"
        assert get_scheduled_action(db, action.id).status == "cancelled"
        db.close()

    def test_is_disputed_flag_cancels_reminder(self):
        from app.crud.scheduled_action import create_scheduled_action
        from app.services.scheduler import process_single_action

        db = TestSessionLocal()
        case = create_case(db, extra_data={"is_disputed": True})
        action = create_scheduled_action(
            db,
            {
                "recovery_case_id": case.id,
                "action_type": "reminder",
                "attempt_number": 1,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )
        detail = process_single_action(db, action)
        assert detail["result"] == "cancelled"
        assert detail["reason"] == "case_disputed_escalated"
        db.close()

    def test_non_disputed_executes_normally(self):
        from app.crud.scheduled_action import create_scheduled_action
        from app.services.scheduler import process_single_action

        db = TestSessionLocal()
        case = create_case(db, extra_data={"failure_reason": "bank_timeout"})
        action = create_scheduled_action(
            db,
            {
                "recovery_case_id": case.id,
                "action_type": "touchpoint_24h",
                "attempt_number": 1,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )
        detail = process_single_action(db, action)
        assert detail["result"] == "executed"
        db.close()


# ============================================================
# SECTION 3: BACKGROUND SCHEDULER LOOP
# ============================================================


class TestAutonomousSchedulerLoop:
    def test_run_one_due_poll_with_factory(self):
        from app.crud.scheduled_action import create_scheduled_action
        from app.services import scheduler

        db = TestSessionLocal()
        case = create_case(db)
        create_scheduled_action(
            db,
            {
                "recovery_case_id": case.id,
                "action_type": "touchpoint_24h",
                "attempt_number": 1,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )

        scheduler.set_scheduler_session_factory(TestSessionLocal)
        try:
            results = scheduler.run_one_due_poll()
            assert results["total_due"] == 1
            assert results["executed"] == 1
        finally:
            scheduler.set_scheduler_session_factory(None)
            db.close()

    def test_loop_poll_interval_and_stop(self):
        from app.services import scheduler

        scheduler.set_scheduler_session_factory(TestSessionLocal)
        try:
            stop = asyncio.Event()
            ticks = []

            async def _run():
                await scheduler.run_scheduler_loop(
                    poll_interval=0.05,
                    stop_event=stop,
                    on_tick=lambda results: ticks.append(results),
                )

            stop.set()
            asyncio.get_event_loop().run_until_complete(_run())
            # With stop already set, no ticks occur and it returns promptly.
            assert ticks == []
        finally:
            scheduler.set_scheduler_session_factory(None)

    def test_manual_ops_endpoint_runs_poll(self):
        from app.crud.scheduled_action import create_scheduled_action

        db = TestSessionLocal()
        case = create_case(db)
        create_scheduled_action(
            db,
            {
                "recovery_case_id": case.id,
                "action_type": "touchpoint_24h",
                "attempt_number": 1,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )
        db.close()

        resp = _isolated_request("post", "/api/autonomous/scheduler/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["executed"] == 1
        assert data["total_due"] == 1


# ============================================================
# SECTION 4: NEXT-TOUCHPOINT SCHEDULE ENDPOINT
# ============================================================


class TestScheduleEndpoint:
    def test_get_schedule_returns_next_pending(self):
        from app.crud.scheduled_action import create_scheduled_action

        db = TestSessionLocal()
        case = create_case(db)
        create_scheduled_action(
            db,
            {
                "recovery_case_id": case.id,
                "action_type": "touchpoint_24h",
                "attempt_number": 1,
                "channel": "whatsapp",
                "scheduled_for": datetime.now(timezone.utc) + timedelta(hours=24),
            },
        )
        case_id = str(case.id)
        db.close()

        resp = _isolated_request("get", f"/api/cases/{case_id}/schedule")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_actions"] == 1
        assert data["pending_count"] == 1
        assert data["next_action"]["action_type"] == "touchpoint_24h"
        assert data["next_action"]["scheduled_for"]
        db.close()

    def test_get_schedule_empty_case(self):
        db = TestSessionLocal()
        case = create_case(db)
        case_id = str(case.id)
        db.close()

        resp = _isolated_request("get", f"/api/cases/{case_id}/schedule")
        assert resp.status_code == 200
        assert resp.json()["next_action"] is None
