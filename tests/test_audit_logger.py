"""Tests for Centralized Audit Logging Service.

Covers:
- All 23 event types
- Timeline query
- Timeline summary
- Event metadata completeness
- Amount formatting
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus


# ============ Helpers ============

def _create_customer(db, ext_id="cust_audit_1"):
    c = Customer(external_id=ext_id, email=f"{ext_id}@test.com", name="Test User")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _create_case(db, customer, amount=120000):
    ev = RevenueEvent(
        customer_id=customer.id,
        external_event_id=f"evt_{uuid.uuid4().hex[:8]}",
        event_type="payment_failed", amount=amount, status="failed", source="razorpay",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    case = RecoveryCase(
        customer_id=customer.id, revenue_event_id=ev.id, risk_level="high",
        original_amount=amount, remaining_amount=amount, status=RecoveryStatus.RECOVERY_IN_PROGRESS,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ============ All 23 Event Types ============

class TestAllEventTypes:
    def test_revenue_detected(self, db_session):
        from app.services.audit_logger import log_revenue_detected
        c = _create_customer(db_session, "c1")
        case = _create_case(db_session, c)
        result = log_revenue_detected(db_session, case.id, 120000, "pay_123", "insufficient_funds")
        assert result["event_type"] == "REVENUE_DETECTED"
        assert result["result"] == "detected"

    def test_risk_detected(self, db_session):
        from app.services.audit_logger import log_risk_detected
        c = _create_customer(db_session, "c2")
        case = _create_case(db_session, c)
        result = log_risk_detected(db_session, case.id, "HIGH", "High-value failure", 120000)
        assert result["event_type"] == "RISK_DETECTED"
        assert result["result"] == "high"

    def test_recovery_started(self, db_session):
        from app.services.audit_logger import log_recovery_started
        c = _create_customer(db_session, "c3")
        case = _create_case(db_session, c)
        result = log_recovery_started(db_session, case.id, "default")
        assert result["event_type"] == "RECOVERY_STARTED"

    def test_strategy_selected(self, db_session):
        from app.services.audit_logger import log_strategy_selected
        c = _create_customer(db_session, "c4")
        case = _create_case(db_session, c)
        result = log_strategy_selected(db_session, case.id, "gentle", "Low risk customer")
        assert result["event_type"] == "STRATEGY_SELECTED"

    def test_action_scheduled(self, db_session):
        from app.services.audit_logger import log_action_scheduled
        c = _create_customer(db_session, "c5")
        case = _create_case(db_session, c)
        result = log_action_scheduled(db_session, case.id, "reminder_1", "whatsapp", "2026-01-01T12:00:00Z")
        assert result["event_type"] == "ACTION_SCHEDULED"

    def test_action_cancelled(self, db_session):
        from app.services.audit_logger import log_action_cancelled
        c = _create_customer(db_session, "c6")
        case = _create_case(db_session, c)
        result = log_action_cancelled(db_session, case.id, "reminder_1", "payment_recovered")
        assert result["event_type"] == "ACTION_CANCELLED"

    def test_message_sent(self, db_session):
        from app.services.audit_logger import log_message_sent
        c = _create_customer(db_session, "c7")
        case = _create_case(db_session, c)
        result = log_message_sent(db_session, case.id, "whatsapp", "text", "en")
        assert result["event_type"] == "MESSAGE_SENT"

    def test_message_failed(self, db_session):
        from app.services.audit_logger import log_message_failed
        c = _create_customer(db_session, "c8")
        case = _create_case(db_session, c)
        result = log_message_failed(db_session, case.id, "whatsapp", "API timeout", True)
        assert result["event_type"] == "MESSAGE_FAILED"

    def test_customer_replied(self, db_session):
        from app.services.audit_logger import log_customer_replied
        c = _create_customer(db_session, "c9")
        case = _create_case(db_session, c)
        result = log_customer_replied(db_session, case.id, c.id, "I'll pay tomorrow", "en")
        assert result["event_type"] == "CUSTOMER_REPLIED"

    def test_intent_detected(self, db_session):
        from app.services.audit_logger import log_intent_detected
        c = _create_customer(db_session, "c10")
        case = _create_case(db_session, c)
        result = log_intent_detected(db_session, case.id, "PROMISE_TO_PAY", 0.94, "ai", "I'll pay tomorrow")
        assert result["event_type"] == "INTENT_DETECTED"

    def test_promise_created(self, db_session):
        from app.services.audit_logger import log_promise_created
        c = _create_customer(db_session, "c11")
        case = _create_case(db_session, c)
        result = log_promise_created(db_session, case.id, c.id, 50000, "2026-01-05")
        assert result["event_type"] == "PROMISE_CREATED"

    def test_payment_plan_proposed(self, db_session):
        from app.services.audit_logger import log_payment_plan_proposed
        c = _create_customer(db_session, "c12")
        case = _create_case(db_session, c)
        result = log_payment_plan_proposed(db_session, case.id, uuid.uuid4(), 120000, 4, "weekly")
        assert result["event_type"] == "PAYMENT_PLAN_PROPOSED"

    def test_payment_plan_accepted(self, db_session):
        from app.services.audit_logger import log_payment_plan_accepted
        c = _create_customer(db_session, "c13")
        case = _create_case(db_session, c)
        result = log_payment_plan_accepted(db_session, case.id, uuid.uuid4(), 120000)
        assert result["event_type"] == "PAYMENT_PLAN_ACCEPTED"

    def test_installment_created(self, db_session):
        from app.services.audit_logger import log_installment_created
        c = _create_customer(db_session, "c14")
        case = _create_case(db_session, c)
        result = log_installment_created(db_session, case.id, uuid.uuid4(), 1, 30000, "2026-01-07")
        assert result["event_type"] == "INSTALLMENT_CREATED"

    def test_installment_paid(self, db_session):
        from app.services.audit_logger import log_installment_paid
        c = _create_customer(db_session, "c15")
        case = _create_case(db_session, c)
        result = log_installment_paid(db_session, case.id, uuid.uuid4(), 30000, 1)
        assert result["event_type"] == "INSTALLMENT_PAID"

    def test_invoice_requested(self, db_session):
        from app.services.audit_logger import log_invoice_requested
        c = _create_customer(db_session, "c16")
        case = _create_case(db_session, c)
        result = log_invoice_requested(db_session, case.id, c.id)
        assert result["event_type"] == "INVOICE_REQUESTED"

    def test_invoice_sent(self, db_session):
        from app.services.audit_logger import log_invoice_sent
        c = _create_customer(db_session, "c17")
        case = _create_case(db_session, c)
        result = log_invoice_sent(db_session, case.id, uuid.uuid4(), "email")
        assert result["event_type"] == "INVOICE_SENT"

    def test_payment_retried(self, db_session):
        from app.services.audit_logger import log_payment_retried
        c = _create_customer(db_session, "c18")
        case = _create_case(db_session, c)
        result = log_payment_retried(db_session, case.id, 120000, "https://pay.example.com/123")
        assert result["event_type"] == "PAYMENT_RETRIED"

    def test_payment_recovered(self, db_session):
        from app.services.audit_logger import log_payment_recovered
        c = _create_customer(db_session, "c19")
        case = _create_case(db_session, c)
        result = log_payment_recovered(db_session, case.id, 120000, "pay_123")
        assert result["event_type"] == "PAYMENT_RECOVERED"

    def test_recovery_stopped(self, db_session):
        from app.services.audit_logger import log_recovery_stopped
        c = _create_customer(db_session, "c20")
        case = _create_case(db_session, c)
        result = log_recovery_stopped(db_session, case.id, "customer_requested")
        assert result["event_type"] == "RECOVERY_STOPPED"

    def test_recovery_expired(self, db_session):
        from app.services.audit_logger import log_recovery_expired
        c = _create_customer(db_session, "c21")
        case = _create_case(db_session, c)
        result = log_recovery_expired(db_session, case.id, "2026-01-01")
        assert result["event_type"] == "RECOVERY_EXPIRED"

    def test_ai_error(self, db_session):
        from app.services.audit_logger import log_ai_error
        c = _create_customer(db_session, "c22")
        case = _create_case(db_session, c)
        result = log_ai_error(db_session, case.id, "API timeout", "intent_detection")
        assert result["event_type"] == "AI_ERROR"

    def test_external_api_error(self, db_session):
        from app.services.audit_logger import log_external_api_error
        c = _create_customer(db_session, "c23")
        case = _create_case(db_session, c)
        result = log_external_api_error(db_session, case.id, "Razorpay", "Server error 500", "create_order")
        assert result["event_type"] == "EXTERNAL_API_ERROR"

    def test_all_23_types_have_descriptions(self):
        from app.services.audit_logger import AuditEventType, EVENT_DESCRIPTIONS
        types = sorted(x for x in dir(AuditEventType) if not x.startswith("_"))
        # Every defined event type must have a user-facing description.
        # (31 types today; keep the actual count in sync with the enum.)
        assert len(types) == 31
        for t in types:
            assert getattr(AuditEventType, t) in EVENT_DESCRIPTIONS

    def test_all_23_types_have_icons(self):
        from app.services.audit_logger import AuditEventType, EVENT_ICONS
        types = [x for x in dir(AuditEventType) if not x.startswith("_")]
        for t in types:
            assert getattr(AuditEventType, t) in EVENT_ICONS

    def test_all_23_types_have_colors(self):
        from app.services.audit_logger import AuditEventType, EVENT_COLORS
        types = [x for x in dir(AuditEventType) if not x.startswith("_")]
        for t in types:
            assert getattr(AuditEventType, t) in EVENT_COLORS


# ============ Timeline Query ============

class TestTimelineQuery:
    def test_timeline_returns_events(self, db_session):
        from app.services.audit_logger import (
            log_revenue_detected, log_risk_detected, log_recovery_started,
            log_message_sent, log_recovery_stopped, get_recovery_timeline,
        )
        c = _create_customer(db_session, "c_tl_1")
        case = _create_case(db_session, c)

        # Create a sequence of events
        log_revenue_detected(db_session, case.id, 120000, "pay_1", "failed")
        log_risk_detected(db_session, case.id, "HIGH", "High value", 120000)
        log_recovery_started(db_session, case.id)
        log_message_sent(db_session, case.id, "whatsapp")
        log_recovery_stopped(db_session, case.id, "customer_requested")

        timeline = get_recovery_timeline(db_session, case.id)

        assert timeline["total_events"] == 5
        assert len(timeline["timeline"]) == 5
        assert timeline["case"]["customer_name"] == "Test User"

    def test_timeline_chronological_order(self, db_session):
        from app.services.audit_logger import (
            log_recovery_started, log_message_sent, log_payment_recovered,
            get_recovery_timeline,
        )
        c = _create_customer(db_session, "c_tl_2")
        case = _create_case(db_session, c)

        log_recovery_started(db_session, case.id)
        log_message_sent(db_session, case.id, "whatsapp")
        log_payment_recovered(db_session, case.id, 120000)

        timeline = get_recovery_timeline(db_session, case.id)
        events = timeline["timeline"]

        # Events should be in chronological order
        for i in range(1, len(events)):
            assert events[i]["timestamp"] >= events[i-1]["timestamp"]

    def test_timeline_summary_counts(self, db_session):
        from app.services.audit_logger import (
            log_message_sent, log_message_failed, log_customer_replied,
            log_payment_recovered, get_recovery_timeline,
        )
        c = _create_customer(db_session, "c_tl_3")
        case = _create_case(db_session, c)

        log_message_sent(db_session, case.id, "whatsapp")
        log_message_sent(db_session, case.id, "whatsapp")
        log_message_sent(db_session, case.id, "email")
        log_message_failed(db_session, case.id, "whatsapp", "timeout")
        log_customer_replied(db_session, case.id, c.id, "Hello")
        log_payment_recovered(db_session, case.id, 60000)

        timeline = get_recovery_timeline(db_session, case.id)
        summary = timeline["summary"]

        assert summary["messages_sent"] == 3
        assert summary["messages_failed"] == 1
        assert summary["customer_replies"] == 1
        assert summary["payments_recovered"] == 1

    def test_timeline_empty_case(self, db_session):
        from app.services.audit_logger import get_recovery_timeline
        c = _create_customer(db_session, "c_tl_4")
        case = _create_case(db_session, c)

        timeline = get_recovery_timeline(db_session, case.id)
        assert timeline["total_events"] == 0
        assert timeline["timeline"] == []

    def test_timeline_event_metadata(self, db_session):
        from app.services.audit_logger import log_intent_detected, get_recovery_timeline
        c = _create_customer(db_session, "c_tl_5")
        case = _create_case(db_session, c)

        log_intent_detected(db_session, case.id, "PROMISE_TO_PAY", 0.94, "ai", "I'll pay tomorrow")

        timeline = get_recovery_timeline(db_session, case.id)
        event = timeline["timeline"][0]

        assert event["event_type"] == "INTENT_DETECTED"
        assert event["icon"] == "🧠"
        assert event["color"] == "purple"
        assert "PROMISE_TO_PAY" in event["reason"]
        assert event["metadata"]["confidence"] == 0.94


# ============ Amount Formatting ============

class TestAmountFormatting:
    def test_format_small_amount(self):
        from app.services.audit_logger import _format_amount
        assert _format_amount(500) == "₹5"

    def test_format_medium_amount(self):
        from app.services.audit_logger import _format_amount
        assert _format_amount(120000) == "₹1,200"

    def test_format_large_amount(self):
        from app.services.audit_logger import _format_amount
        assert _format_amount(15000000) == "₹1,50,000"

    def test_format_with_metadata(self, db_session):
        from app.services.audit_logger import log_payment_recovered
        from app.models.audit_event import AuditEvent
        from sqlalchemy import select
        c = _create_customer(db_session, "c_fmt_1")
        case = _create_case(db_session, c)

        log_payment_recovered(db_session, case.id, 120000, "pay_123")

        audit = db_session.execute(
            select(AuditEvent).where(
                AuditEvent.recovery_case_id == case.id,
                AuditEvent.action == "PAYMENT_RECOVERED",
            )
        ).scalar_one_or_none()

        assert audit is not None
        meta = audit.extra_data
        assert meta["amount"] == 120000
        assert meta["amount_formatted"] == "₹1,200"
        assert meta["result"] == "recovered"
        assert meta["payment_id"] == "pay_123"
