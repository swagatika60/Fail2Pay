"""Tests for the live WhatsApp audit stream additions.

Covers:
- 24h/72h touchpoint scheduling helper
- promise-reminder standalone scheduler helper
- realtime manager broadcast / build_message_event serialization
- Meta WhatsApp webhook alias route registration (/api/whatsapp/webhook)
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.services import scheduler
from app.services.realtime import (
    build_message_event,
    publish_message_event,
)

test_engine = create_engine(
    "sqlite://",
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


def create_test_customer(db) -> Customer:
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


def create_test_case(db) -> RecoveryCase:
    customer = create_test_customer(db)
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
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=event.id,
        risk_level="high",
        status=RecoveryStatus.RECOVERY_IN_PROGRESS,
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


class TestWhatsAppTouchpointSchedule:
    def test_has_immediate_24h_and_72h(self):
        """Touchpoint config is 0h / 24h / 72h."""
        delays = [s["delay_hours"] for s in scheduler.WHATSAPP_TOUCHPOINT_CONFIG]
        assert delays == [0, 24, 72]

    def test_schedule_whatsapp_touchpoints_creates_3(self):
        db = TestSessionLocal()
        case = create_test_case(db)
        created = scheduler.schedule_whatsapp_touchpoints(db, case)
        assert len(created) == 3
        from app.crud.scheduled_action import get_actions_by_case

        actions = get_actions_by_case(db, case.id)
        types = [a.action_type for a in actions]
        assert types == ["touchpoint_immediate", "touchpoint_24h", "touchpoint_72h"]
        assert all(a.channel == "whatsapp" for a in actions)
        db.close()

    def test_schedule_promise_reminder(self):
        db = TestSessionLocal()
        case = create_test_case(db)
        reminder_at = datetime.now(timezone.utc) + timedelta(hours=4)
        result = scheduler.schedule_promise_reminder(db, case, reminder_at)
        assert result["action_type"] == "promise_reminder"
        assert result["scheduled_for"]
        db.close()


class TestRealtimeMessageEvent:
    def test_build_message_event(self):
        event = build_message_event(
            conversation_id="conv-1",
            case_id="case-1",
            message_id="msg-1",
            direction="inbound",
            content="I'll pay tomorrow",
            message_type="text",
            created_at="2026-01-01T00:00:00Z",
            extra_data={"language": "en"},
        )
        assert event["type"] == "message"
        assert event["case_id"] == "case-1"
        assert event["message"]["direction"] == "inbound"
        assert event["message"]["content"] == "I'll pay tomorrow"

    def test_publish_message_event_without_loop_is_safe(self):
        # No running event loop in a sync context -> no-op (should not raise).
        publish_message_event(
            conversation_id="c",
            case_id="case-x",
            message_id="m",
            direction="outbound",
            content="hi",
            message_type="text",
            created_at="2026-01-01T00:00:00Z",
        )


class TestMetaWebhookRouteRegistration:
    def test_whatsapp_cloud_routes_registered(self):
        from app.main import app

        methods = {("GET", "/api/whatsapp/webhook"), ("POST", "/api/whatsapp/webhook")}
        found = {(m, p) for r in app.routes for m in getattr(r, "methods", []) for p in [r.path]}
        assert methods.issubset(found)

    def test_webhook_verify_token_gate(self):
        from app.services.whatsapp import verify_webhook

        # Without a configured token, verification fails gracefully.
        assert verify_webhook("subscribe", "nope", "challenge") is None
