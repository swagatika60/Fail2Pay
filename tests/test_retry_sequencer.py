"""Tests for the Payment Degradation & Mandate Retry Sequencer.

Validates Feature 3:
  - Plans with < 2 failures are NOT degraded
  - Plans with 2+ mandate/autopay failures are degraded to SPLIT_PLAN
  - Plans with 2+ generic failures degrade to ALTERNATE_GATEWAY
  - Retry timeline is timestamped and respects cooldown thresholds
  - Terminal cases never schedule retries (hard-stop aware)
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.payment_plan import PaymentPlan, PaymentPlanStatus
from app.models.installment import Installment

from app.services.retry_sequencer import generate_retry_sequencer


def _create_case(db, amount=1000000, status=RecoveryStatus.RECOVERY_IN_PROGRESS):
    c = Customer(external_id=f"c_{uuid.uuid4().hex[:8]}", email="a@b.com", name="A")
    db.add(c)
    db.commit()
    db.refresh(c)
    ev = RevenueEvent(
        customer_id=c.id, external_event_id=f"e_{uuid.uuid4().hex[:8]}",
        event_type="payment_failed", amount=amount, status="failed", source="razorpay",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    case = RecoveryCase(
        customer_id=c.id, revenue_event_id=ev.id, risk_level="high",
        original_amount=amount, remaining_amount=amount, status=status,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _create_plan(db, case, failures: list[str] | None = None):
    failures = failures or []
    plan = PaymentPlan(
        recovery_case_id=case.id, customer_id=case.customer_id,
        total_amount=case.original_amount, installment_amount=case.original_amount // 2,
        number_of_installments=2, frequency="weekly", currency="INR",
        status=PaymentPlanStatus.ACTIVE.value,
        amount_paid=0, installments_paid=0, installments_failed=len(failures),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    for i, reason in enumerate(failures, start=1):
        db.add(Installment(
            payment_plan_id=plan.id, recovery_case_id=case.id,
            installment_number=i, amount=case.original_amount // 2,
            due_date=datetime.now(timezone.utc) - timedelta(days=i),
            status="FAILED", failure_reason=reason,
        ))
    db.commit()
    db.refresh(plan)
    return plan


class TestRetrySequencer:
    def test_not_degraded_below_threshold(self, db_session):
        case = _create_case(db_session)
        plan = _create_plan(db_session, case, failures=["insufficient_funds"])
        db_session.refresh(plan)
        result = generate_retry_sequencer(db_session, plan.id)
        assert result.degraded is False
        assert result.strategy is None
        assert result.blocked is False
        assert result.timeline

    def test_degraded_to_split_plan_on_mandate_failures(self, db_session):
        case = _create_case(db_session)
        plan = _create_plan(db_session, case, failures=["mandate_declined", "autopay_failed"])
        db_session.refresh(plan)
        result = generate_retry_sequencer(db_session, plan.id)
        assert result.degraded is True
        assert result.strategy == "SPLIT_PLAN"
        assert result.split is not None
        # 50% upfront, 50% in 14 days
        upfront = result.split["upfront_amount"]
        later = result.split["later_amount"]
        assert upfront + later == case.original_amount
        assert abs(upfront - later) <= 1
        assert len(result.timeline) >= 5

    def test_degraded_to_alternate_gateway_on_generic_failures(self, db_session):
        case = _create_case(db_session)
        plan = _create_plan(db_session, case, failures=["payment_failed", "network_error"])
        db_session.refresh(plan)
        result = generate_retry_sequencer(db_session, plan.id)
        assert result.degraded is True
        assert result.strategy == "ALTERNATE_GATEWAY"
        assert result.split is None

    def test_timeline_is_timestamped_and_sorted(self, db_session):
        from datetime import datetime as _dt
        case = _create_case(db_session)
        plan = _create_plan(db_session, case, failures=["mandate_declined", "autopay_failed"])
        db_session.refresh(plan)
        result = generate_retry_sequencer(db_session, plan.id)
        times = [_dt.fromisoformat(step["scheduled_for"]) for step in result.timeline]
        assert all(t is not None for t in times)
        assert times == sorted(times)
        # first scheduled step is "now" (degrade trigger)
        assert result.timeline[0]["action"] == "degrade_trigger"

    def test_terminal_case_blocks_retries(self, db_session):
        case = _create_case(db_session, status=RecoveryStatus.STOPPED)
        plan = _create_plan(db_session, case, failures=["mandate_declined", "autopay_failed"])
        db_session.refresh(plan)
        result = generate_retry_sequencer(db_session, plan.id)
        assert result.blocked is True
        assert "case_terminal" in result.block_reason
        assert result.timeline == []

    def test_sequential_split_dates(self, db_session):
        from datetime import datetime as _dt, timedelta as _td
        case = _create_case(db_session)
        plan = _create_plan(db_session, case, failures=["autopay_failed", "upi_mandate_failed"])
        db_session.refresh(plan)
        result = generate_retry_sequencer(db_session, plan.id)
        later_due = _dt.fromisoformat(result.split["later_due"])
        upfront_due = _dt.fromisoformat(result.split["upfront_due"])
        assert later_due - upfront_due >= _td(days=13)
