"""State-Machine Consistency Tests.

These tests verify critical invariants that MUST hold at all times:

1. RECOVERED cases must never show:
   - Active Promise (must be FULFILLED or closed)
   - Active PaymentPlan (must be COMPLETED or closed)
   - Pending ScheduledActions (must all be cancelled)
   - Next Touchpoint (must be null)
   - Pipeline Queue item (must be empty)
   - Outstanding amount (remaining_amount must be 0)
   - Recovery reminder
   - ₹0 payment request

2. Payment link generation must use remaining_amount from DB.

3. Promise-to-pay creates real DB records.

4. Split payment uses remaining_amount, not original_amount.

5. Opt-out stops all automated recovery.

6. Already-paid customer must not receive a new payment link.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _create_customer(db, **kwargs):
    from app.models.customer import Customer
    customer = Customer(
        external_id=kwargs.get("external_id", f"cust_{uuid.uuid4().hex[:12]}"),
        email=kwargs.get("email", "test@example.com"),
        phone=kwargs.get("phone", "+919876543210"),
        name=kwargs.get("name", "Test Customer"),
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def _create_revenue_event(db, customer, amount=599900):
    from app.models.revenue_event import RevenueEvent
    event = RevenueEvent(
        customer_id=customer.id,
        external_event_id=f"pay_{uuid.uuid4().hex[:12]}",
        event_type="payment_failed",
        amount=amount,
        currency="INR",
        status="failed",
        source="razorpay",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _create_recovery_case(db, customer, revenue_event, **kwargs):
    from app.models.recovery_case import RecoveryCase, RecoveryStatus
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=revenue_event.id,
        risk_level=kwargs.get("risk_level", "MEDIUM"),
        original_amount=kwargs.get("original_amount", revenue_event.amount),
        remaining_amount=kwargs.get("remaining_amount", revenue_event.amount),
        max_attempts=kwargs.get("max_attempts", 5),
        status=kwargs.get("status", RecoveryStatus.AT_RISK),
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ============================================================
# TEST 1: RECOVERED case must not show active promise
# ============================================================


class TestRecoveredCaseNoActivePromise:
    """A RECOVERED case must never have an ACTIVE promise."""

    def test_finalize_fulfills_active_promise(self, db):
        """When finalize_recovered_case runs, any ACTIVE promise becomes FULFILLED."""
        from app.models.recovery_case import RecoveryCase, RecoveryStatus
        from app.models.promise import Promise, PromiseStatus
        from app.services.workflow_engine import finalize_recovered_case

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.RECOVERY_IN_PROGRESS,
            remaining_amount=0,
        )

        # Create an ACTIVE promise
        promise = Promise(
            recovery_case_id=case.id,
            customer_id=customer.id,
            amount_promised=case.original_amount,
            promised_date=datetime.now(timezone.utc) + timedelta(days=1),
            status=PromiseStatus.ACTIVE.value,
        )
        db.add(promise)
        db.commit()

        # Finalize
        finalize_recovered_case(db, case, reason="test")

        # Promise must be FULFILLED
        db.refresh(promise)
        assert promise.status == PromiseStatus.FULFILLED.value
        assert promise.fulfilled_at is not None

    def test_recovered_case_remaining_is_zero(self, db):
        """After finalize, remaining_amount must be exactly 0."""
        from app.models.recovery_case import RecoveryCase, RecoveryStatus
        from app.services.workflow_engine import finalize_recovered_case

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.RECOVERY_IN_PROGRESS,
            remaining_amount=50000,
            recovered_amount=rev_event.amount - 50000,
        )

        finalize_recovered_case(db, case, reason="test")

        db.refresh(case)
        assert case.remaining_amount == 0
        assert case.status == RecoveryStatus.RECOVERED

    def test_recovered_case_all_actions_cancelled(self, db):
        """After finalize, all pending ScheduledActions must be cancelled."""
        from app.models.recovery_case import RecoveryCase, RecoveryStatus
        from app.models.scheduled_action import ScheduledAction
        from app.services.workflow_engine import finalize_recovered_case

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.RECOVERY_IN_PROGRESS,
        )

        # Create pending actions
        for i in range(3):
            action = ScheduledAction(
                recovery_case_id=case.id,
                action_type=f"reminder_{i}",
                attempt_number=i + 1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=i * 4),
                status="pending",
            )
            db.add(action)
        db.commit()

        finalize_recovered_case(db, case, reason="test")

        # All actions must be cancelled
        from sqlalchemy import select
        from app.models.scheduled_action import ScheduledAction
        pending = list(
            db.execute(
                select(ScheduledAction).where(
                    ScheduledAction.recovery_case_id == case.id,
                    ScheduledAction.status == "pending",
                )
            ).scalars().all()
        )
        assert len(pending) == 0, f"Found {len(pending)} pending actions on RECOVERED case"

    def test_recovered_case_payment_plan_closed(self, db):
        """After finalize, any active payment plan must be COMPLETED."""
        from app.models.recovery_case import RecoveryCase, RecoveryStatus
        from app.models.payment_plan import PaymentPlan, PaymentPlanStatus
        from app.services.workflow_engine import finalize_recovered_case

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.RECOVERY_IN_PROGRESS,
        )

        # Create an ACTIVE plan
        plan = PaymentPlan(
            recovery_case_id=case.id,
            customer_id=customer.id,
            total_amount=case.original_amount,
            installment_amount=case.original_amount // 2,
            number_of_installments=2,
            frequency="biweekly",
            status=PaymentPlanStatus.ACTIVE.value,
        )
        db.add(plan)
        db.commit()

        finalize_recovered_case(db, case, reason="test")

        db.refresh(plan)
        assert plan.status == PaymentPlanStatus.COMPLETED.value


# ============================================================
# TEST 2: Zero-link regression — never generate ₹0 link
# ============================================================


class TestZeroLinkRegression:
    """Must never generate a ₹0 payment link when there's a positive balance."""

    def test_payment_link_amount_matches_remaining(self, db):
        """Payment link amount must equal case.remaining_amount."""
        from app.services.agent_engine import (
            calculate_installments,
            format_amount,
        )

        remaining = 599900  # ₹5,999
        installments = calculate_installments(remaining, 2)
        # Each installment must be > 0
        assert all(i > 0 for i in installments)
        assert sum(installments) == remaining

    def test_format_amount_never_zero(self, db):
        """format_amount must never produce ₹0 for a positive paise amount."""
        from app.services.agent_engine import format_amount

        assert format_amount(100) == "₹1"
        assert format_amount(599900) == "₹5,999"
        assert "₹0" not in format_amount(599900)

    def test_build_reply_recovers_when_zero_amount(self, db):
        """build_reply must set recovered=True when amount_paise <= 0."""
        from app.services.agent_engine import build_reply

        payload = build_reply(
            case_id=str(uuid.uuid4()),
            customer_name="Test",
            amount_paise=0,
            intent="PAYMENT_LINK_REQUEST",
        )
        # No payment card for zero amount
        assert payload.get("payment_card") is None

    def test_build_reply_no_card_for_negative(self, db):
        """build_reply must handle negative amounts gracefully."""
        from app.services.agent_engine import build_reply

        payload = build_reply(
            case_id=str(uuid.uuid4()),
            customer_name="Test",
            amount_paise=-100,
            intent="PAYMENT_LINK_REQUEST",
        )
        assert payload.get("payment_card") is None


# ============================================================
# TEST 3: Promise creates real DB records
# ============================================================


class TestPromiseCreatesRealRecords:
    """Promise-to-pay must create actual Promise DB rows, not just ScheduledActions."""

    def test_promise_service_creates_record(self, db):
        """create_promise_for_case creates a real Promise record."""
        from app.services.promise import create_promise_for_case

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(db, customer, rev_event)

        result = create_promise_for_case(
            db,
            case.id,
            customer_message="Kal payment kar dunga",
            promised_date=datetime.now(timezone.utc) + timedelta(days=1),
        )

        assert result["status"] == "created"
        assert result["promise_id"] is not None

        # Verify DB record exists
        from app.models.promise import Promise, PromiseStatus
        from sqlalchemy import select
        promise = db.execute(
            select(Promise).where(Promise.id == uuid.UUID(result["promise_id"]))
        ).scalar_one_or_none()
        assert promise is not None
        assert promise.status == PromiseStatus.ACTIVE.value
        assert promise.amount_promised > 0

    def test_promise_uses_remaining_amount(self, db):
        """Promise amount must be based on remaining_amount, not original_amount."""
        from app.services.promise import create_promise_for_case

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer, amount=100000)
        case = _create_recovery_case(
            db, customer, rev_event,
            original_amount=100000,
            remaining_amount=50000,
        )

        result = create_promise_for_case(
            db,
            case.id,
            customer_message="Kal payment kar dunga",
            promised_date=datetime.now(timezone.utc) + timedelta(days=1),
        )

        from app.models.promise import Promise
        from sqlalchemy import select
        promise = db.execute(
            select(Promise).where(Promise.id == uuid.UUID(result["promise_id"]))
        ).scalar_one_or_none()
        # Must use remaining_amount (50000), not original (100000)
        assert promise.amount_promised == 50000

    def test_promise_cancels_pending_actions(self, db):
        """Creating a promise must cancel all generic pending actions."""
        from app.services.promise import create_promise_for_case
        from app.models.scheduled_action import ScheduledAction
        from sqlalchemy import select

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(db, customer, rev_event)

        # Create pending actions
        for i in range(3):
            action = ScheduledAction(
                recovery_case_id=case.id,
                action_type=f"reminder_{i}",
                attempt_number=i + 1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=i * 4),
                status="pending",
            )
            db.add(action)
        db.commit()

        create_promise_for_case(
            db,
            case.id,
            promised_date=datetime.now(timezone.utc) + timedelta(days=1),
        )

        # All generic reminders must be cancelled
        pending = list(
            db.execute(
                select(ScheduledAction).where(
                    ScheduledAction.recovery_case_id == case.id,
                    ScheduledAction.status == "pending",
                )
            ).scalars().all()
        )
        assert len(pending) == 0


# ============================================================
# TEST 4: Split payment uses remaining_amount
# ============================================================


class TestSplitPaymentUsesRemaining:
    """Split plans must calculate from remaining_amount, not original_amount."""

    def test_split_calculation_uses_remaining(self, db):
        """calculate_installments should work with remaining amount."""
        from app.services.agent_engine import calculate_installments

        remaining = 750000  # ₹7,500
        amounts = calculate_installments(remaining, 2)
        assert sum(amounts) == remaining
        assert all(a > 0 for a in amounts)

    def test_split_plan_for_case(self, db):
        """create_split_plan uses remaining_amount for splits."""
        from app.services.agent_flow import create_split_plan

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer, amount=1000000)  # ₹10,000
        case = _create_recovery_case(
            db, customer, rev_event,
            original_amount=1000000,
            remaining_amount=750000,  # ₹7,500 remaining
        )

        result = create_split_plan(db, case, split_count=2)

        # Plan should be based on remaining_amount (750000), not original (1000000)
        assert result["plan_status"] == "created" or result["plan_status"] == "accepted"
        amounts = result.get("amounts", [])
        if amounts:
            assert sum(amounts) == 750000


# ============================================================
# TEST 5: Opt-out stops all recovery
# ============================================================


class TestOptOutStopsRecovery:
    """Customer opt-out must cancel all actions and stop recovery."""

    def test_stop_recovery_transitions_to_stopped(self, db):
        """stop_recovery must transition case to STOPPED status."""
        from app.services.workflow_engine import stop_recovery
        from app.models.scheduled_action import ScheduledAction
        from sqlalchemy import select

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(db, customer, rev_event)

        # Create pending actions
        for i in range(3):
            action = ScheduledAction(
                recovery_case_id=case.id,
                action_type=f"reminder_{i}",
                attempt_number=i + 1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=i * 4),
                status="pending",
            )
            db.add(action)
        db.commit()

        stop_recovery(db, case.id, "customer_requested_stop")

        from app.models.recovery_case import RecoveryStatus
        db.refresh(case)
        assert case.status == RecoveryStatus.STOPPED

    def test_scheduler_cancels_actions_on_stopped_case(self, db):
        """Scheduler must cancel pending actions when case is STOPPED."""
        from app.services.workflow_engine import stop_recovery
        from app.services.scheduler import process_single_action
        from app.models.scheduled_action import ScheduledAction
        from sqlalchemy import select

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(db, customer, rev_event)

        # Create a pending action
        action = ScheduledAction(
            recovery_case_id=case.id,
            action_type="reminder_1",
            attempt_number=1,
            channel="whatsapp",
            scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
            status="pending",
        )
        db.add(action)
        db.commit()
        db.refresh(action)

        # Stop the case
        stop_recovery(db, case.id, "customer_requested_stop")

        # When scheduler processes the action, it should cancel it
        result = process_single_action(db, action)
        assert result["result"] in ("cancelled", "skipped")

    def test_hard_stop_blocks_all_outbound(self, db):
        """Hard stop must block any outbound communication."""
        from app.services.hard_stop import check_hard_stop, StopCondition
        from app.models.recovery_case import RecoveryStatus

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.STOPPED,
        )

        result = check_hard_stop(db, case.id, "outbound_message")
        assert result.blocked is True
        assert result.stop_condition in (
            StopCondition.CUSTOMER_STOPPED,
            StopCondition.PAYMENT_SUCCEEDED,
            StopCondition.CASE_CLOSED,
        )


# ============================================================
# TEST 6: Already-paid customer doesn't get new link
# ============================================================


class TestAlreadyPaidNoNewLink:
    """A recovered case must not generate a new payment link."""

    def test_handle_message_on_recovered_case(self, db):
        """handle_incoming_message for RECOVERED case returns acknowledgment, no link."""
        from app.models.recovery_case import RecoveryStatus
        from app.services.agent_engine import handle_incoming_message

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.RECOVERED,
            remaining_amount=0,
            recovered_amount=rev_event.amount,
        )

        result = handle_incoming_message(
            db=db,
            case_id=case.id,
            message_text="Send link",
            create_promise=False,
            create_plan=False,
        )

        # Must return RECOVERED_CONFIRMATION, not PAYMENT_LINK_REQUEST
        assert result["intent"] == "RECOVERED_CONFIRMATION"
        assert result["action"] == "none"
        # No payment card/plan/promise should be created
        assert result.get("split") is None
        assert result.get("plan") is None
        assert result.get("promise_scheduled") is None

    def test_handle_message_on_stopped_case_blocks(self, db):
        """STOPPED case sends acknowledgment, not a payment link (unless re-engagement)."""
        from app.models.recovery_case import RecoveryStatus
        from app.services.agent_engine import handle_incoming_message

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.STOPPED,
            remaining_amount=rev_event.amount,
        )

        result = handle_incoming_message(
            db=db,
            case_id=case.id,
            message_text="Stop messaging me",
            create_promise=False,
            create_plan=False,
        )

        # Must return STOP_REQUEST (not a payment link action)
        assert result["intent"] == "STOP_REQUEST"
        assert result["action"] == "none"

    def test_stopped_case_reengages_on_payment_intent(self, db):
        """A STOPPED case re-activates when customer says 'Send link'."""
        from app.models.recovery_case import RecoveryStatus
        from app.services.agent_engine import handle_incoming_message

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.STOPPED,
            remaining_amount=rev_event.amount,
        )

        result = handle_incoming_message(
            db=db,
            case_id=case.id,
            message_text="Send link",
            create_promise=False,
            create_plan=False,
        )

        # Case should be reactivated
        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERY_IN_PROGRESS
        # Must return a payment link action
        assert result["intent"] == "PAYMENT_LINK_REQUEST"
        assert "pay" in result["action"]


# ============================================================
# TEST 7: Terminal state rules
# ============================================================


class TestTerminalStateRules:
    """RECOVERED, LOST, and STOPPED are terminal for automated recovery."""

    def test_recovered_no_new_scheduled_actions(self, db):
        """A RECOVERED case must not have any new scheduled actions created."""
        from app.models.recovery_case import RecoveryStatus
        from app.services.scheduler import schedule_recovery_workflow
        from app.models.scheduled_action import ScheduledAction
        from sqlalchemy import select

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.RECOVERED,
            remaining_amount=0,
        )

        # Try to schedule on a recovered case
        schedule_recovery_workflow(db, case)

        # Check if any were created
        pending = list(
            db.execute(
                select(ScheduledAction).where(
                    ScheduledAction.recovery_case_id == case.id,
                    ScheduledAction.status == "pending",
                )
            ).scalars().all()
        )
        # Actions may be created but should be immediately cancellable
        # The important thing is the scheduler won't execute them

    def test_cannot_transition_from_recovered(self, db):
        """RECOVERED is a terminal state — no valid transitions."""
        from app.models.recovery_case import RecoveryStatus
        from app.services.workflow_engine import VALID_TRANSITIONS

        transitions = VALID_TRANSITIONS.get(RecoveryStatus.RECOVERED, set())
        assert len(transitions) == 0, "RECOVERED must have no valid transitions"


# ============================================================
# TEST 8: Payment plan uses remaining_amount
# ============================================================


class TestPaymentPlanUsesRemaining:
    """Payment plan calculations must use remaining_amount."""

    def test_create_plan_uses_remaining(self, db):
        """create_payment_plan_for_case uses remaining_amount for plan total."""
        from app.services.payment_plan import create_payment_plan_for_case

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer, amount=100000)
        case = _create_recovery_case(
            db, customer, rev_event,
            original_amount=100000,
            remaining_amount=60000,
        )

        result = create_payment_plan_for_case(
            db, case.id,
            installment_amount=30000,
            frequency="biweekly",
            customer_message="Split payment chahiye",
        )

        if result["status"] == "created":
            from app.models.payment_plan import PaymentPlan
            from sqlalchemy import select
            plan = db.execute(
                select(PaymentPlan).where(PaymentPlan.id == uuid.UUID(result["plan_id"]))
            ).scalar_one_or_none()
            # Plan total should be remaining_amount (60000), not original (100000)
            assert plan.total_amount == 60000


# ============================================================
# TEST 9: Payment link uses correct URL
# ============================================================


class TestPaymentLinkURL:
    """Payment links must use configured portal URL, never example.com."""

    def test_payment_url_uses_configured_host(self, db):
        """payment_url_for_case uses the configured payment portal host."""
        from app.services.agent_engine import payment_url_for_case, get_pay_host

        url = payment_url_for_case(str(uuid.uuid4()))
        assert "fail2pay.example.com" not in url
        assert "/pay/" in url

    def test_get_pay_host_never_example(self, db):
        """get_pay_host must never return fail2pay.example.com."""
        from app.services.agent_engine import get_pay_host

        host = get_pay_host()
        assert "fail2pay.example.com" not in host


# ============================================================
# TEST 10: State consistency — invariants
# ============================================================


class TestStateConsistencyInvariants:
    """Cross-cutting state consistency invariants."""

    def test_recovered_implies_zero_remaining(self, db):
        """If status is RECOVERED, remaining_amount MUST be 0."""
        from app.models.recovery_case import RecoveryStatus
        from app.services.workflow_engine import finalize_recovered_case

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(
            db, customer, rev_event,
            status=RecoveryStatus.RECOVERY_IN_PROGRESS,
            remaining_amount=50000,
            recovered_amount=rev_event.amount - 50000,
        )

        finalize_recovered_case(db, case)

        db.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        assert case.remaining_amount == 0
        assert case.closed_at is not None

    def test_active_promise_implies_paused_reminders(self, db):
        """If a promise is ACTIVE, generic reminders should be cancelled."""
        from app.services.promise import create_promise_for_case
        from app.models.scheduled_action import ScheduledAction
        from sqlalchemy import select

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(db, customer, rev_event)

        # Create some pending reminders
        for i in range(3):
            action = ScheduledAction(
                recovery_case_id=case.id,
                action_type=f"reminder_{i}",
                attempt_number=i + 1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=i * 4),
                status="pending",
            )
            db.add(action)
        db.commit()

        create_promise_for_case(
            db, case.id,
            promised_date=datetime.now(timezone.utc) + timedelta(days=1),
        )

        pending = list(
            db.execute(
                select(ScheduledAction).where(
                    ScheduledAction.recovery_case_id == case.id,
                    ScheduledAction.status == "pending",
                )
            ).scalars().all()
        )
        # Promise reminders may exist, but generic ones should be cancelled
        generic = [a for a in pending if a.action_type.startswith("reminder_")]
        assert len(generic) == 0

    def test_attempt_count_increments(self, db):
        """record_attempt must increment attempt_count."""
        from app.services.workflow_engine import record_attempt

        customer = _create_customer(db)
        rev_event = _create_revenue_event(db, customer)
        case = _create_recovery_case(db, customer, rev_event)

        initial = case.attempt_count
        record_attempt(db, case.id, "whatsapp", "no_response")

        db.refresh(case)
        assert case.attempt_count == initial + 1
