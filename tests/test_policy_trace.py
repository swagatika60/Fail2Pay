"""Tests for the Decision Audit Trail / Policy Trace endpoint.

Validates Feature 1: /api/cases/{case_id}/policy-trace reconstructs the
AI/Policy decision chain into labeled layers (trigger / ai_judgment /
policy / action / outcome), each carrying its human-readable reason.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus


def _create_customer(db, ext_id="cust_trace_1"):
    c = Customer(external_id=ext_id, email=f"{ext_id}@test.com", name="Trace User")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _create_case(db, customer, amount=500000):
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
        original_amount=amount, remaining_amount=amount,
        status=RecoveryStatus.RECOVERY_IN_PROGRESS,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _build_full_chain(db, case):
    """Populate a representative decision chain across all layers."""
    from app.services.audit_logger import (
        log_revenue_detected,
        log_risk_detected,
        log_recovery_started,
        log_strategy_selected,
        log_action_scheduled,
        log_intent_detected,
        log_message_sent,
        log_promise_created,
        log_payment_recovered,
    )
    return [
        log_revenue_detected(db, case.id, 500000, "pay_1", "mandate_declined"),
        log_risk_detected(db, case.id, "HIGH", "High-value recurring payment failure", 500000),
        log_recovery_started(db, case.id, "default"),
        log_strategy_selected(db, case.id, "SEND_WHATSAPP", "Attempt 1 — WhatsApp preferred"),
        log_action_scheduled(db, case.id, "SEND_WHATSAPP", "whatsapp", "2025-01-01T10:00:00Z"),
        log_intent_detected(db, case.id, "PROMISE_TO_PAY", 0.92, "ai", "Kal pakka karunga"),
        log_message_sent(db, case.id, "whatsapp", "text", "hi-en"),
        log_promise_created(db, case.id, case.customer_id, 500000, "2025-01-15"),
        log_payment_recovered(db, case.id, 500000, "rcp_123"),
    ]


class TestPolicyTraceEndpoint:
    def test_layers_are_classified(self, db_session):
        """Each event is assigned one of the four decision layers."""
        from app.routes.case_detail import get_case_policy_trace

        c = _create_customer(db_session, "pt_1")
        case = _create_case(db_session, c)
        _build_full_chain(db_session, case)

        result = get_case_policy_trace(case.id, db_session)

        assert result["chain"]
        layers = {node["layer"] for node in result["chain"]}
        assert "trigger" in layers
        assert "ai_judgment" in layers
        assert "policy" in layers
        assert "action" in layers
        assert "outcome" in layers

    def test_trigger_layer_has_failure_reason(self, db_session):
        c = _create_customer(db_session, "pt_2")
        case = _create_case(db_session, c)
        _build_full_chain(db_session, case)

        from app.routes.case_detail import get_case_policy_trace
        result = get_case_policy_trace(case.id, db_session)

        trigger = [n for n in result["chain"] if n["layer"] == "trigger"]
        assert len(trigger) >= 1
        assert "mandate_declined" in trigger[0]["reason"]

    def test_ai_judgment_has_confidence_and_source(self, db_session):
        from app.routes.case_detail import get_case_policy_trace

        c = _create_customer(db_session, "pt_3")
        case = _create_case(db_session, c)
        _build_full_chain(db_session, case)

        result = get_case_policy_trace(case.id, db_session)
        ai = [n for n in result["chain"] if n["layer"] == "ai_judgment"][0]
        assert ai["metadata"]["intent"] == "PROMISE_TO_PAY"
        assert ai["metadata"]["source"] == "ai"

    def test_layer_counts_match_chain(self, db_session):
        from app.routes.case_detail import get_case_policy_trace

        c = _create_customer(db_session, "pt_4")
        case = _create_case(db_session, c)
        _build_full_chain(db_session, case)

        result = get_case_policy_trace(case.id, db_session)
        total = sum(result["layer_counts"].values())
        assert total == len(result["chain"])

    def test_unknown_case_404(self, db_session):
        from fastapi import HTTPException
        from app.routes.case_detail import get_case_policy_trace

        with pytest.raises(HTTPException) as exc:
            get_case_policy_trace(uuid.uuid4(), db_session)
        assert exc.value.status_code == 404

    def test_hard_stop_event_classified_as_policy(self, db_session):
        """Hard-stop audit events surface as deterministic policy decisions."""
        from app.models.audit_event import AuditEvent
        from app.schemas.audit_event import AuditEventCreate
        from app.routes.case_detail import get_case_policy_trace

        c = _create_customer(db_session, "pt_5")
        case = _create_case(db_session, c)

        from app.crud.audit_event import create_audit_event
        create_audit_event(
            db_session,
            data=AuditEventCreate(
                recovery_case_id=case.id,
                entity_type="hard_stop",
                entity_id=case.id,
                action="hard_stop_customer_stopped",
                new_value={"stop_condition": "customer_stopped", "reason": "Customer requested stop"},
            ),
        )

        result = get_case_policy_trace(case.id, db_session)
        hs = [n for n in result["chain"] if n["event_type"].startswith("hard_stop")]
        assert hs and hs[0]["layer"] == "policy"


class TestLayerClassificationHelper:
    def test_classify(self):
        from app.routes.case_detail import _classify_policy_layer, _count_layers

        assert _classify_policy_layer("REVENUE_DETECTED") == "trigger"
        assert _classify_policy_layer("INTENT_DETECTED") == "ai_judgment"
        assert _classify_policy_layer("STRATEGY_SELECTED") == "policy"
        assert _classify_policy_layer("MESSAGE_SENT") == "action"
        assert _classify_policy_layer("PAYMENT_RECOVERED") == "outcome"
        assert _classify_policy_layer("hard_stop_customer_stopped") == "policy"

        assert _count_layers([
            {"layer": "trigger"}, {"layer": "action"}, {"layer": "action"},
        ]) == {"trigger": 1, "action": 2}
