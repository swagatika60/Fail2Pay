"""Tests for the Verified Impact Ledger & Recovery Pipeline.

Validates Feature 4:
  - Pipeline funnel stages shrink monotonically
  - Only verified captured payments count as recovered revenue
  - Ledger rows carry risk/status/amounts
  - Promises/messages never inflate recovered revenue
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.payment import Payment
from app.models.conversation import Conversation, ConversationStatus
from app.models.conversation_message import ConversationMessage

from app.services.simulation import compute_verified_impact_ledger

DEMO = "DEMO_SIMULATION"


def _mk_case(db, amount=100000, status=RecoveryStatus.RECOVERED, recovered=0, idx=0, scenario="responds_and_pays"):
    c = Customer(
        external_id=f"{DEMO}_ldg_{idx}", email=f"l{idx}@x.com", name="L User",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    ev = RevenueEvent(
        customer_id=c.id, external_event_id=f"e_{uuid.uuid4().hex[:8]}",
        event_type="payment_failed", amount=amount, status="failed", source="razorpay",
        extra_data={"simulation": True, "scenario": scenario},
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    case = RecoveryCase(
        customer_id=c.id, revenue_event_id=ev.id, risk_level="medium",
        original_amount=amount, remaining_amount=amount - recovered,
        recovered_amount=recovered, status=status,
        extra_data={"simulation": True, "scenario": scenario},
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _add_payment(db, case, amount):
    db.add(Payment(
        recovery_case_id=case.id, amount=amount, status="captured", currency="INR",
        razorpay_payment_id=f"p_{uuid.uuid4().hex[:8]}",
    ))
    db.commit()


def _add_conv(db, case, messages):
    conv = Conversation(
        recovery_case_id=case.id, channel="whatsapp", status=ConversationStatus.ACTIVE,
        extra_data={"simulation": True},
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    for direction, content in messages:
        db.add(ConversationMessage(
            conversation_id=conv.id, direction=direction, content=content, message_type="text",
        ))
    db.commit()


class TestImpactLedger:
    def test_empty_ledger_present_false(self, db_session):
        result = compute_verified_impact_ledger(db_session)
        assert result["present"] is False
        assert result["summary"]["verified_recovered"] == 0
        assert result["ledger"] == []

    def test_only_captured_payments_count_as_recovered(self, db_session):
        """A case with a captured payment is recovered; a case with only a
        promise + outbound message is NOT recovered (no money moved)."""
        recovered_case = _mk_case(db_session, amount=100000, status=RecoveryStatus.RECOVERED, recovered=100000, idx=1)
        _add_payment(db_session, recovered_case, 100000)
        _add_conv(db_session, recovered_case, [("outbound", "Please pay"), ("inbound", "Done!")])

        promised_case = _mk_case(db_session, amount=90000, status=RecoveryStatus.PROMISED, recovered=0, idx=2, scenario="promise_to_pay")
        _add_conv(db_session, promised_case, [("outbound", "Please pay"), ("inbound", "Kal pakka karunga")])

        result = compute_verified_impact_ledger(db_session)
        assert result["present"] is True
        assert result["summary"]["verified_recovered"] == 100000
        assert result["summary"]["original_revenue"] == 190000

        # Promise case is in funnel's promise_captured but NOT verified_recovered
        assert result["funnel"]["promise_captured"]["count"] == 2
        assert result["funnel"]["verified_recovered"]["count"] == 1

    def test_funnel_monotonically_shrinks(self, db_session):
        for idx in range(3):
            c = _mk_case(db_session, amount=100000, status=RecoveryStatus.RECOVERED, recovered=100000, idx=100 + idx)
            _add_payment(db_session, c, 100000)
            _add_conv(db_session, c, [("outbound", "hi")])
        result = compute_verified_impact_ledger(db_session)

        f = result["funnel"]
        assert f["at_risk"]["count"] == 3
        assert (
            f["at_risk"]["count"]
            >= f["intervention_dispatched"]["count"]
            >= f["promise_captured"]["count"]
            >= f["verified_recovered"]["count"]
        )
        assert f["verified_recovered"]["amount"] == 300000

    def test_partial_payment_recovery(self, db_session):
        c = _mk_case(db_session, amount=200000, status=RecoveryStatus.PARTIALLY_RECOVERED, recovered=100000, idx=9)
        _add_payment(db_session, c, 100000)
        result = compute_verified_impact_ledger(db_session)
        # recovered counts the actual captured money, remaining stays
        assert result["summary"]["verified_recovered"] == 100000
        row = result["ledger"][0]
        assert row["verified_recovered_amount"] == 100000
        assert row["remaining_amount"] == 100000
        assert row["verified_recovered"] is True


class TestImpactLedgerAPI:
    def test_get_impact_ledger_endpoint(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine, autoflush=False)()
        try:
            c = _mk_case(session, amount=100000, status=RecoveryStatus.RECOVERED, recovered=100000, idx=20)
            _add_payment(session, c, 100000)
            _add_conv(session, c, [("outbound", "Please pay"), ("inbound", "Done")])

            prior = app.dependency_overrides.get(get_db)
            app.dependency_overrides[get_db] = lambda: session
            try:
                res = TestClient(app).get("/api/simulation/impact-ledger")
                assert res.status_code == 200
                body = res.json()
                assert body["present"] is True
                assert body["summary"]["verified_recovered"] == 100000
                assert body["funnel"]["verified_recovered"]["count"] == 1
                assert body["funnel"]["at_risk"]["count"] == 1
                assert len(body["ledger"]) == 1
            finally:
                if prior is not None:
                    app.dependency_overrides[get_db] = prior
                else:
                    app.dependency_overrides.pop(get_db, None)
        finally:
            session.close()
            Base.metadata.drop_all(bind=engine)
            engine.dispose()
