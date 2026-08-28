"""Tests for the Simulated Customer Message / Opt-Out triggers endpoint.

Validates Feature 2:
  - "stop" trigger -> hard-stop #2 (opt-out) -> case STOPPED + guardrail note
  - "promise" trigger -> PROMISE_TO_PAY -> creates real Promise
  - "wrong_bill" trigger -> QUESTION -> NO hard stop
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus


def _create_customer(db, ext_id="cust_sim_1", phone="919999000001"):
    c = Customer(
        external_id=ext_id,
        email=f"{ext_id}@test.com",
        name="Sim User",
        phone=phone,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _create_case(db, customer, amount=300000):
    ev = RevenueEvent(
        customer_id=customer.id,
        external_event_id=f"evt_{uuid.uuid4().hex[:8]}",
        event_type="payment_failed", amount=amount, status="failed", source="razorpay",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    case = RecoveryCase(
        customer_id=customer.id, revenue_event_id=ev.id, risk_level="medium",
        original_amount=amount, remaining_amount=amount,
        status=RecoveryStatus.RECOVERY_IN_PROGRESS,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


class TestSimulateMessage:
    def test_stop_trigger_sets_stopped_with_guardrail(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session)
        case = _create_case(db_session, c)

        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="stop"), db_session
        )

        assert resp["opt_out_triggered"] is True
        assert resp["case_status"] == "STOPPED"
        assert "Policy Guardrail" in resp["guardrail_note"]

    def test_stop_trigger_respects_hard_stop(self, db_session):
        """Stop message always wins — even if a promise existed, it's cancelled."""
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest
        from app.services.promise import create_promise_for_case

        c = _create_customer(db_session, phone="919999000002")
        case = _create_case(db_session, c)
        create_promise_for_case(db_session, case.id, customer_message="I will pay")

        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="stop"), db_session
        )

        from app.models.promise import Promise
        db_session.expire_all()
        active = db_session.query(Promise).filter(
            Promise.recovery_case_id == case.id,
            Promise.status == "ACTIVE",
        ).first()
        assert active is None
        assert resp["case_status"] == "STOPPED"

    def test_promise_trigger_creates_promise(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, phone="919999000003")
        case = _create_case(db_session, c)

        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="promise"), db_session
        )

        from app.models.promise import Promise
        active = db_session.query(Promise).filter(
            Promise.recovery_case_id == case.id,
            Promise.status == "ACTIVE",
        ).first()
        assert active is not None
        assert resp["detected_intent"] == "PROMISE_TO_PAY"
        assert resp["opt_out_triggered"] is False

    def test_wrong_bill_trigger_no_hard_stop(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, phone="919999000004")
        case = _create_case(db_session, c)

        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="wrong_bill"), db_session
        )

        assert resp["opt_out_triggered"] is False
        assert resp["case_status"] != "STOPPED"
        assert resp["guardrail_note"] is None

    def test_logs_audit_events(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest
        from app.models.audit_event import AuditEvent

        c = _create_customer(db_session, phone="919999000005")
        case = _create_case(db_session, c)

        simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="stop"), db_session
        )

        events = db_session.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == case.id
        ).all()
        actions = {e.action for e in events}
        assert "CUSTOMER_REPLIED" in actions
        assert "INTENT_DETECTED" in actions

    def test_unknown_case_404(self, db_session):
        from fastapi import HTTPException
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        with pytest.raises(HTTPException) as exc:
            simulate_customer_message(
                uuid.uuid4(), SimulateMessageRequest(trigger="stop"), db_session
            )
        assert exc.value.status_code == 404
