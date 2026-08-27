"""Tests for Installment Workflow Service.

Covers:
- Status transitions (SCHEDULED→DUE→PAID/FAILED/OVERDUE)
- Reminder scheduling (before due date, no duplicates, skip paid)
- Payment recording (installment, plan, case updates)
- Plan completion (all installments paid → plan COMPLETED, case RECOVERED)
- Failed installment recovery (bounded)
- Cancellation of future actions
- Revenue map data
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.payment_plan import PaymentPlan, PaymentPlanStatus
from app.models.installment import Installment, InstallmentStatus
from app.models.scheduled_action import ScheduledAction
from app.crud.payment_plan import (
    create_payment_plan,
    create_installment,
    get_installment,
    get_installments_for_plan,
)
from app.schemas.payment_plan import PaymentPlanCreate
from app.schemas.installment import InstallmentCreate


# ============ Helpers ============

def _create_customer(db, external_id="cust_inst_1"):
    customer = Customer(external_id=external_id, email=f"{external_id}@test.com", name="Test User")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def _create_case(db, customer, amount=120000, status=RecoveryStatus.SCHEDULED):
    event = RevenueEvent(
        customer_id=customer.id,
        external_event_id=f"evt_{uuid.uuid4().hex[:8]}",
        event_type="payment_failed",
        amount=amount,
        status="failed",
        source="razorpay",
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=event.id,
        risk_level="high",
        original_amount=amount,
        remaining_amount=amount,
        status=status,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _create_plan(db, case, total=120000, installment=30000, n=4, frequency="weekly"):
    plan = create_payment_plan(
        db,
        data=PaymentPlanCreate(
            recovery_case_id=case.id,
            customer_id=case.customer_id,
            total_amount=total,
            installment_amount=installment,
            number_of_installments=n,
            frequency=frequency,
        ),
    )
    return plan


def _create_installments(db, plan, case, n=4, amount=30000, start_days=7):
    installments = []
    for i in range(n):
        due = datetime.now(timezone.utc) + timedelta(days=start_days + 7 * i)
        inst = create_installment(
            db,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=i + 1,
                amount=amount,
                due_date=due,
            ),
        )
        installments.append(inst)
    return installments


# ============ Status Transitions ============

class TestStatusTransitions:
    def test_scheduled_to_due(self, db_session):
        """Installments transition to DUE when due_date is within reminder window."""
        from app.services.installment_workflow import process_installment_statuses

        customer = _create_customer(db_session, "cust_trans_1")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        # Create installment due in 23 hours (within 24h window)
        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=datetime.now(timezone.utc) + timedelta(hours=23),
            ),
        )

        assert inst.status == InstallmentStatus.SCHEDULED.value

        result = process_installment_statuses(db_session)

        assert result["to_due"] >= 1
        db_session.refresh(inst)
        assert inst.status == InstallmentStatus.DUE.value

    def test_scheduled_stays_scheduled_when_far(self, db_session):
        """Installments far from due date stay SCHEDULED."""
        from app.services.installment_workflow import process_installment_statuses

        customer = _create_customer(db_session, "cust_trans_2")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        # Due in 48 hours (outside 24h window)
        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=datetime.now(timezone.utc) + timedelta(hours=48),
            ),
        )

        result = process_installment_statuses(db_session)
        assert result["to_due"] == 0
        db_session.refresh(inst)
        assert inst.status == InstallmentStatus.SCHEDULED.value

    def test_scheduled_to_overdue(self, db_session):
        """Installments past due date transition to OVERDUE."""
        from app.services.installment_workflow import process_installment_statuses

        customer = _create_customer(db_session, "cust_trans_3")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        # Due 2 hours ago
        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=datetime.now(timezone.utc) - timedelta(hours=2),
            ),
        )

        result = process_installment_statuses(db_session)
        assert result["to_overdue"] >= 1
        db_session.refresh(inst)
        assert inst.status == InstallmentStatus.OVERDUE.value

    def test_paid_not_affected(self, db_session):
        """Paid installments are not affected by status processing."""
        from app.services.installment_workflow import process_installment_statuses

        customer = _create_customer(db_session, "cust_trans_4")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=datetime.now(timezone.utc) - timedelta(hours=2),
            ),
        )
        inst.status = InstallmentStatus.PAID.value
        db_session.commit()

        result = process_installment_statuses(db_session)
        db_session.refresh(inst)
        assert inst.status == InstallmentStatus.PAID.value

    def test_failed_not_affected(self, db_session):
        """Failed installments are not affected by status processing."""
        from app.services.installment_workflow import process_installment_statuses

        customer = _create_customer(db_session, "cust_trans_5")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=datetime.now(timezone.utc) - timedelta(hours=2),
            ),
        )
        inst.status = InstallmentStatus.FAILED.value
        db_session.commit()

        result = process_installment_statuses(db_session)
        db_session.refresh(inst)
        assert inst.status == InstallmentStatus.FAILED.value

    def test_multiple_installments_process(self, db_session):
        """Multiple installments are processed correctly."""
        from app.services.installment_workflow import process_installment_statuses

        customer = _create_customer(db_session, "cust_trans_6")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        installments = _create_installments(db_session, plan, case, n=4)

        # First two due within 24h
        installments[0].due_date = datetime.now(timezone.utc) + timedelta(hours=10)
        installments[1].due_date = datetime.now(timezone.utc) + timedelta(hours=20)
        # Last two due later
        installments[2].due_date = datetime.now(timezone.utc) + timedelta(days=3)
        installments[3].due_date = datetime.now(timezone.utc) + timedelta(days=4)
        db_session.commit()

        result = process_installment_statuses(db_session)
        assert result["to_due"] == 2


# ============ Reminder Scheduling ============

class TestReminderScheduling:
    def test_schedule_reminder_before_due(self, db_session):
        """Reminder is scheduled before the due date."""
        from app.services.installment_workflow import schedule_installment_reminder

        customer = _create_customer(db_session, "cust_rem_1")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        due_date = datetime.now(timezone.utc) + timedelta(days=2)
        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=due_date,
            ),
        )

        result = schedule_installment_reminder(db_session, inst.id)

        assert result["status"] == "scheduled"
        assert "action_id" in result

        # Verify the action was created
        action = db_session.get(ScheduledAction, uuid.UUID(result["action_id"]))
        assert action is not None
        assert action.action_type == "installment_reminder"
        assert action.status == "pending"

        # Reminder should be before due date (SQLite may return naive datetimes)
        sched = action.scheduled_for.replace(tzinfo=timezone.utc) if action.scheduled_for.tzinfo is None else action.scheduled_for
        due = due_date.replace(tzinfo=timezone.utc) if due_date.tzinfo is None else due_date
        assert sched < due

    def test_no_reminder_for_paid_installment(self, db_session):
        """No reminder is scheduled for paid installments."""
        from app.services.installment_workflow import schedule_installment_reminder

        customer = _create_customer(db_session, "cust_rem_2")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=datetime.now(timezone.utc) + timedelta(days=2),
            ),
        )
        inst.status = InstallmentStatus.PAID.value
        db_session.commit()

        result = schedule_installment_reminder(db_session, inst.id)
        assert result["status"] == "skipped"
        assert result["reason"] == "installment_already_paid"

    def test_no_reminder_for_cancelled_installment(self, db_session):
        """No reminder is scheduled for cancelled installments."""
        from app.services.installment_workflow import schedule_installment_reminder

        customer = _create_customer(db_session, "cust_rem_3")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=datetime.now(timezone.utc) + timedelta(days=2),
            ),
        )
        inst.status = InstallmentStatus.CANCELLED.value
        db_session.commit()

        result = schedule_installment_reminder(db_session, inst.id)
        assert result["status"] == "skipped"
        assert result["reason"] == "installment_cancelled"

    def test_no_duplicate_reminders(self, db_session):
        """Duplicate reminders are not created."""
        from app.services.installment_workflow import schedule_installment_reminder

        customer = _create_customer(db_session, "cust_rem_4")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=datetime.now(timezone.utc) + timedelta(days=2),
            ),
        )

        # Schedule first reminder
        result1 = schedule_installment_reminder(db_session, inst.id)
        assert result1["status"] == "scheduled"

        # Try to schedule again
        result2 = schedule_installment_reminder(db_session, inst.id)
        assert result2["status"] == "skipped"
        assert result2["reason"] == "reminder_already_scheduled"

    def test_reminder_for_nonexistent_installment(self, db_session):
        """Scheduling reminder for nonexistent installment returns error."""
        from app.services.installment_workflow import schedule_installment_reminder

        fake_id = uuid.uuid4()
        result = schedule_installment_reminder(db_session, fake_id)
        assert result["status"] == "error"
        assert result["reason"] == "installment_not_found"

    def test_reminder_scheduled_imminently_when_past(self, db_session):
        """When due date is imminent, reminder is scheduled soon (not in the past)."""
        from app.services.installment_workflow import schedule_installment_reminder

        customer = _create_customer(db_session, "cust_rem_5")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)

        inst = create_installment(
            db_session,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case.id,
                installment_number=1,
                amount=30000,
                due_date=datetime.now(timezone.utc) + timedelta(hours=2),
            ),
        )

        result = schedule_installment_reminder(db_session, inst.id, hours_before_due=24)
        assert result["status"] == "scheduled"

        action = db_session.get(ScheduledAction, uuid.UUID(result["action_id"]))
        sched = action.scheduled_for.replace(tzinfo=timezone.utc) if action.scheduled_for.tzinfo is None else action.scheduled_for
        assert sched >= datetime.now(timezone.utc)


# ============ Payment Recording ============

class TestPaymentRecording:
    def test_record_payment_updates_installment(self, db_session):
        """Recording payment updates installment status to PAID."""
        from app.services.installment_workflow import record_installment_payment

        customer = _create_customer(db_session, "cust_pay_1")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=1)

        result = record_installment_payment(
            db_session, installments[0].id, 30000, "pay_test_123"
        )

        assert result["status"] == "paid"
        assert result["amount"] == 30000
        assert result["plan_completed"] is False
        assert result["case_recovered"] is False

        db_session.refresh(installments[0])
        assert installments[0].status == InstallmentStatus.PAID.value
        assert installments[0].paid_amount == 30000
        assert installments[0].razorpay_payment_id == "pay_test_123"

    def test_record_payment_updates_plan(self, db_session):
        """Recording payment updates plan amount_paid and installments_paid."""
        from app.services.installment_workflow import record_installment_payment

        customer = _create_customer(db_session, "cust_pay_2")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=4)

        record_installment_payment(db_session, installments[0].id, 30000)

        db_session.refresh(plan)
        assert plan.amount_paid == 30000
        assert plan.installments_paid == 1

    def test_record_payment_updates_case(self, db_session):
        """Recording payment updates case recovered_amount and remaining_amount."""
        from app.services.installment_workflow import record_installment_payment

        customer = _create_customer(db_session, "cust_pay_3")
        case = _create_case(db_session, customer, amount=120000)
        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=4)

        record_installment_payment(db_session, installments[0].id, 30000)

        db_session.refresh(case)
        assert case.recovered_amount == 30000
        assert case.remaining_amount == 90000

    def test_record_payment_already_paid(self, db_session):
        """Cannot record payment for already-paid installment."""
        from app.services.installment_workflow import record_installment_payment

        customer = _create_customer(db_session, "cust_pay_4")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=1)

        # Mark as paid first
        installments[0].status = InstallmentStatus.PAID.value
        db_session.commit()

        result = record_installment_payment(db_session, installments[0].id, 30000)
        assert result["status"] == "skipped"
        assert result["reason"] == "already_paid"

    def test_record_payment_nonexistent_installment(self, db_session):
        """Recording payment for nonexistent installment returns error."""
        from app.services.installment_workflow import record_installment_payment

        result = record_installment_payment(db_session, uuid.uuid4(), 30000)
        assert result["status"] == "error"
        assert result["reason"] == "installment_not_found"

    def test_partial_payment_updates_status(self, db_session):
        """Partial payment updates case to PARTIALLY_RECOVERED."""
        from app.services.installment_workflow import record_installment_payment

        customer = _create_customer(db_session, "cust_pay_5")
        case = _create_case(db_session, customer, amount=120000)
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        db_session.commit()

        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=4)

        record_installment_payment(db_session, installments[0].id, 30000)

        db_session.refresh(case)
        assert case.status == RecoveryStatus.PARTIALLY_RECOVERED


# ============ Plan Completion ============

class TestPlanCompletion:
    def test_all_installments_paid_completes_plan(self, db_session):
        """When all installments are paid, plan is COMPLETED and case is RECOVERED."""
        from app.services.installment_workflow import record_installment_payment

        customer = _create_customer(db_session, "cust_comp_1")
        case = _create_case(db_session, customer, amount=120000)
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        db_session.commit()

        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=4, amount=30000)

        # Pay all 4 installments
        for inst in installments:
            result = record_installment_payment(db_session, inst.id, 30000)

        # Last payment should complete the plan
        assert result["plan_completed"] is True
        assert result["case_recovered"] is True

        # Verify plan status
        db_session.refresh(plan)
        assert plan.status == PaymentPlanStatus.COMPLETED.value
        assert plan.amount_paid == 120000
        assert plan.installments_paid == 4
        assert plan.completed_at is not None

        # Verify case status
        db_session.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        assert case.recovered_amount == 120000
        assert case.remaining_amount == 0
        assert case.closed_at is not None

    def test_completion_cancels_future_actions(self, db_session):
        """When plan completes, all pending actions are cancelled."""
        from app.services.installment_workflow import record_installment_payment

        customer = _create_customer(db_session, "cust_comp_2")
        case = _create_case(db_session, customer, amount=60000)
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        db_session.commit()

        plan = _create_plan(db_session, case, total=60000, installment=30000, n=2)
        installments = _create_installments(db_session, plan, case, n=2, amount=30000)

        # Create some pending scheduled actions
        from app.crud.scheduled_action import create_scheduled_action
        from app.schemas.scheduled_action import ScheduledActionCreate

        for i in range(3):
            create_scheduled_action(
                db_session,
                data=ScheduledActionCreate(
                    recovery_case_id=case.id,
                    action_type=f"reminder_{i+1}",
                    attempt_number=i+1,
                    channel="whatsapp",
                    scheduled_for=datetime.now(timezone.utc) + timedelta(hours=4*(i+1)),
                ),
            )

        db_session.commit()

        # Pay first installment
        record_installment_payment(db_session, installments[0].id, 30000)

        # Pay second (final) installment
        result = record_installment_payment(db_session, installments[1].id, 30000)
        assert result["actions_cancelled"] >= 3

        # Verify actions are cancelled
        from sqlalchemy import select
        pending = db_session.execute(
            select(ScheduledAction).where(
                ScheduledAction.recovery_case_id == case.id,
                ScheduledAction.status == "pending",
            )
        ).scalars().all()
        assert len(pending) == 0

    def test_not_all_paid_keeps_plan_active(self, db_session):
        """When not all installments are paid, plan stays ACTIVE."""
        from app.services.installment_workflow import record_installment_payment

        customer = _create_customer(db_session, "cust_comp_3")
        case = _create_case(db_session, customer, amount=120000)
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        db_session.commit()

        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=4, amount=30000)

        # Pay only 2 of 4
        record_installment_payment(db_session, installments[0].id, 30000)
        record_installment_payment(db_session, installments[1].id, 30000)

        db_session.refresh(plan)
        assert plan.status != PaymentPlanStatus.COMPLETED.value
        assert plan.installments_paid == 2
        assert plan.amount_paid == 60000

        db_session.refresh(case)
        assert case.status != RecoveryStatus.RECOVERED


# ============ Failed Installment Recovery ============

class TestFailedInstallmentRecovery:
    def test_record_failure(self, db_session):
        """Recording failure marks installment as FAILED."""
        from app.services.installment_workflow import record_installment_failure

        customer = _create_customer(db_session, "cust_fail_1")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=1)

        result = record_installment_failure(db_session, installments[0].id, "insufficient_funds")

        assert result["status"] == "failed"
        assert result["reason"] == "insufficient_funds"
        assert result["plan_defaulted"] is False

        db_session.refresh(installments[0])
        assert installments[0].status == InstallmentStatus.FAILED.value
        assert installments[0].failure_reason == "insufficient_funds"
        assert installments[0].failed_at is not None

    def test_failure_updates_plan_failed_count(self, db_session):
        """Failure increments plan installments_failed count."""
        from app.services.installment_workflow import record_installment_failure

        customer = _create_customer(db_session, "cust_fail_2")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=4)

        record_installment_failure(db_session, installments[0].id)

        db_session.refresh(plan)
        assert plan.installments_failed == 1

    def test_multiple_failures_default_plan(self, db_session):
        """Too many failures marks plan as DEFAULTED."""
        from app.services.installment_workflow import record_installment_failure

        customer = _create_customer(db_session, "cust_fail_3")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=4)

        # Fail 2 of 4 (threshold = 4//2 = 2)
        record_installment_failure(db_session, installments[0].id)
        record_installment_failure(db_session, installments[1].id)

        db_session.refresh(plan)
        assert plan.status == PaymentPlanStatus.DEFAULTED.value
        assert plan.installments_failed == 2

    def test_failure_already_paid(self, db_session):
        """Cannot record failure for already-paid installment."""
        from app.services.installment_workflow import record_installment_failure

        customer = _create_customer(db_session, "cust_fail_4")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=1)

        installments[0].status = InstallmentStatus.PAID.value
        db_session.commit()

        result = record_installment_failure(db_session, installments[0].id)
        assert result["status"] == "skipped"
        assert result["reason"] == "already_paid"

    def test_failure_nonexistent_installment(self, db_session):
        """Recording failure for nonexistent installment returns error."""
        from app.services.installment_workflow import record_installment_failure

        result = record_installment_failure(db_session, uuid.uuid4())
        assert result["status"] == "error"
        assert result["reason"] == "installment_not_found"


# ============ Workflow Status ============

class TestWorkflowStatus:
    def test_get_workflow_status(self, db_session):
        """Get workflow status returns correct summary."""
        from app.services.installment_workflow import get_installment_workflow_status

        customer = _create_customer(db_session, "cust_status_1")
        case = _create_case(db_session, customer)
        plan = _create_plan(db_session, case)
        installments = _create_installments(db_session, plan, case, n=4)

        # Pay 1, fail 1
        installments[0].status = InstallmentStatus.PAID.value
        installments[0].paid_amount = 30000
        installments[1].status = InstallmentStatus.FAILED.value
        # Update plan amount_paid to match
        plan.amount_paid = 30000
        plan.installments_paid = 1
        db_session.commit()

        result = get_installment_workflow_status(db_session, plan.id)

        assert result["plan_id"] == str(plan.id)
        assert result["summary"]["total"] == 4
        assert result["summary"]["paid"] == 1
        assert result["summary"]["failed"] == 1
        assert result["summary"]["scheduled"] == 2
        assert result["revenue_map"]["paid"] == 30000
        assert result["revenue_map"]["original_at_risk"] == 120000

    def test_get_workflow_status_nonexistent_plan(self, db_session):
        """Get workflow status for nonexistent plan returns error."""
        from app.services.installment_workflow import get_installment_workflow_status

        result = get_installment_workflow_status(db_session, uuid.uuid4())
        assert result["status"] == "error"
        assert result["reason"] == "plan_not_found"

    def test_revenue_map_shows_scheduled_amount(self, db_session):
        """Revenue map shows scheduled amount for pending installments."""
        from app.services.installment_workflow import get_installment_workflow_status

        customer = _create_customer(db_session, "cust_status_2")
        case = _create_case(db_session, customer, amount=120000)
        plan = _create_plan(db_session, case)
        _create_installments(db_session, plan, case, n=4, amount=30000)

        result = get_installment_workflow_status(db_session, plan.id)

        assert result["revenue_map"]["scheduled"] == 120000
        assert result["revenue_map"]["paid"] == 0
        assert result["revenue_map"]["remaining"] == 120000


# ============ Cancel Installment Reminders ============

class TestCancelInstallmentReminders:
    def test_cancel_reminders(self, db_session):
        """Cancel all installment reminders for a case."""
        from app.services.installment_workflow import cancel_all_installment_reminders

        customer = _create_customer(db_session, "cust_cancel_1")
        case = _create_case(db_session, customer)

        # Create some installment reminders
        for i in range(3):
            action = ScheduledAction(
                recovery_case_id=case.id,
                action_type="installment_reminder",
                attempt_number=i + 1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=4 * (i + 1)),
                status="pending",
            )
            db_session.add(action)
        db_session.commit()

        count = cancel_all_installment_reminders(db_session, case.id)
        assert count == 3

        # Verify they're cancelled
        from sqlalchemy import select
        pending = db_session.execute(
            select(ScheduledAction).where(
                ScheduledAction.recovery_case_id == case.id,
                ScheduledAction.status == "pending",
                ScheduledAction.action_type == "installment_reminder",
            )
        ).scalars().all()
        assert len(pending) == 0

    def test_cancel_reminders_only_affects_pending(self, db_session):
        """Cancel only affects pending reminders, not executed ones."""
        from app.services.installment_workflow import cancel_all_installment_reminders

        customer = _create_customer(db_session, "cust_cancel_2")
        case = _create_case(db_session, customer)

        # Create pending and executed reminders
        for status in ["pending", "pending", "executed"]:
            action = ScheduledAction(
                recovery_case_id=case.id,
                action_type="installment_reminder",
                attempt_number=1,
                channel="whatsapp",
                scheduled_for=datetime.now(timezone.utc) + timedelta(hours=4),
                status=status,
            )
            db_session.add(action)
        db_session.commit()

        count = cancel_all_installment_reminders(db_session, case.id)
        assert count == 2  # Only pending ones cancelled

    def test_cancel_no_reminders(self, db_session):
        """Cancel returns 0 when no reminders exist."""
        from app.services.installment_workflow import cancel_all_installment_reminders

        customer = _create_customer(db_session, "cust_cancel_3")
        case = _create_case(db_session, customer)

        count = cancel_all_installment_reminders(db_session, case.id)
        assert count == 0


# ============ End-to-End Lifecycle ============

class TestEndToEndLifecycle:
    def test_full_lifecycle_paid(self, db_session):
        """Full lifecycle: create plan → reminders → payments → plan complete → case recovered."""
        from app.services.installment_workflow import (
            process_installment_statuses,
            schedule_installment_reminder,
            record_installment_payment,
        )

        # Setup
        customer = _create_customer(db_session, "cust_e2e_1")
        case = _create_case(db_session, customer, amount=120000)
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        db_session.commit()

        plan = _create_plan(db_session, case, total=120000, installment=30000, n=4)

        # Create installments due in 23 hours (within reminder window)
        installments = []
        for i in range(4):
            due = datetime.now(timezone.utc) + timedelta(hours=23)
            inst = create_installment(
                db_session,
                data=InstallmentCreate(
                    payment_plan_id=plan.id,
                    recovery_case_id=case.id,
                    installment_number=i + 1,
                    amount=30000,
                    due_date=due,
                ),
            )
            installments.append(inst)

        # Process statuses (SCHEDULED → DUE)
        status_result = process_installment_statuses(db_session)
        assert status_result["to_due"] == 4

        # Schedule reminders
        for inst in installments:
            rem_result = schedule_installment_reminder(db_session, inst.id)
            assert rem_result["status"] == "scheduled"

        # Pay all installments
        for inst in installments:
            pay_result = record_installment_payment(db_session, inst.id, 30000)
            assert pay_result["status"] == "paid"

        # Verify final state
        db_session.refresh(plan)
        db_session.refresh(case)

        assert plan.status == PaymentPlanStatus.COMPLETED.value
        assert plan.amount_paid == 120000
        assert plan.installments_paid == 4
        assert case.status == RecoveryStatus.RECOVERED
        assert case.recovered_amount == 120000
        assert case.remaining_amount == 0

    def test_full_lifecycle_with_failure(self, db_session):
        """Full lifecycle: create plan → payment fails → plan defaulted."""
        from app.services.installment_workflow import (
            record_installment_payment,
            record_installment_failure,
        )

        # Setup
        customer = _create_customer(db_session, "cust_e2e_2")
        case = _create_case(db_session, customer, amount=120000)
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        db_session.commit()

        plan = _create_plan(db_session, case, total=120000, installment=30000, n=4)
        installments = _create_installments(db_session, plan, case, n=4, amount=30000)

        # Pay first installment
        record_installment_payment(db_session, installments[0].id, 30000)

        # Fail remaining 2 (threshold = 4//2 = 2)
        record_installment_failure(db_session, installments[1].id, "card_declined")
        result = record_installment_failure(db_session, installments[2].id, "insufficient_funds")

        assert result["plan_defaulted"] is True

        db_session.refresh(plan)
        assert plan.status == PaymentPlanStatus.DEFAULTED.value
        assert plan.amount_paid == 30000
        assert plan.installments_paid == 1
        assert plan.installments_failed == 2

        db_session.refresh(case)
        assert case.recovered_amount == 30000
        assert case.remaining_amount == 90000

    def test_mixed_paid_and_failed(self, db_session):
        """Some installments paid, some failed — plan stays active."""
        from app.services.installment_workflow import (
            record_installment_payment,
            record_installment_failure,
        )

        customer = _create_customer(db_session, "cust_e2e_3")
        case = _create_case(db_session, customer, amount=120000)
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        db_session.commit()

        plan = _create_plan(db_session, case, total=120000, installment=30000, n=4)
        installments = _create_installments(db_session, plan, case, n=4, amount=30000)

        # Activate plan first (like accept_payment_plan would do)
        from app.crud.payment_plan import activate_plan
        activate_plan(db_session, plan.id)

        # Pay 2, fail 1 (not enough to default)
        record_installment_payment(db_session, installments[0].id, 30000)
        record_installment_payment(db_session, installments[1].id, 30000)
        record_installment_failure(db_session, installments[2].id, "timeout")

        db_session.refresh(plan)
        assert plan.status == PaymentPlanStatus.ACTIVE.value  # Not defaulted (1 failure < 2 threshold)
        assert plan.installments_paid == 2
        assert plan.installments_failed == 1
        assert plan.amount_paid == 60000
