"""Installment Workflow Service.

Manages the lifecycle of individual installments within a payment plan.

Lifecycle:
    SCHEDULED → DUE (when reminder is due) → PAID (payment received)
                                              → FAILED (payment failed)
                                              → OVERDUE (missed deadline)

Key rules:
    - Do NOT send reminders for paid installments
    - Do NOT create duplicate reminders
    - When all installments paid: plan COMPLETED, case RECOVERED, cancel all
    - Failed installments create bounded recovery
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.audit_event import create_audit_event
from app.crud.payment_plan import (
    get_payment_plan,
    get_installments_for_plan,
    get_next_due_installment,
    mark_installment_paid,
    mark_installment_failed,
    mark_installment_overdue,
    count_installments_by_status,
    update_plan_status,
)
from app.crud.recovery_case import get_recovery_case
from app.crud.scheduled_action import (
    cancel_pending_actions_for_case,
    create_scheduled_action,
)
from app.models.installment import InstallmentStatus
from app.models.payment_plan import PaymentPlanStatus
from app.models.recovery_case import RecoveryStatus
from app.schemas.audit_event import AuditEventCreate
from app.schemas.scheduled_action import ScheduledActionCreate

logger = logging.getLogger(__name__)

# Reminder configuration: send reminder N hours before due date
REMINDER_BEFORE_DUE_HOURS = 24  # 1 day before

# Minimum hours between duplicate reminders for the same installment
MIN_REMINDER_INTERVAL_HOURS = 12


def process_installment_statuses(db: Session) -> dict:
    """Process all installments and update their statuses.

    Called periodically (e.g., by a cron job or background task).

    Transitions:
        SCHEDULED → DUE (when due_date is within reminder window)
        SCHEDULED/DUE → OVERDUE (when due_date has passed and not paid)

    Returns:
        Summary dict with transition counts
    """
    results = {
        "to_due": 0,
        "to_overdue": 0,
        "details": [],
    }

    now = datetime.now(timezone.utc)

    # Find installments that should transition to DUE
    from sqlalchemy import select
    from app.models.installment import Installment

    # SCHEDULED → DUE: due_date is within REMINDER_BEFORE_DUE_HOURS of now
    scheduled_installments = list(
        db.execute(
            select(Installment).where(
                Installment.status == InstallmentStatus.SCHEDULED.value,
                Installment.due_date <= now + timedelta(hours=REMINDER_BEFORE_DUE_HOURS),
            )
        ).scalars().all()
    )

    for inst in scheduled_installments:
        inst.status = InstallmentStatus.DUE.value
        results["to_due"] += 1
        results["details"].append({
            "installment_id": str(inst.id),
            "installment_number": inst.installment_number,
            "transition": "SCHEDULED → DUE",
            "due_date": inst.due_date.isoformat(),
        })

    if scheduled_installments:
        db.commit()

    # SCHEDULED/DUE → OVERDUE: due_date has passed and still not paid
    overdue_cutoff = now - timedelta(hours=1)  # grace period of 1 hour
    overdue_installments = list(
        db.execute(
            select(Installment).where(
                Installment.status.in_([
                    InstallmentStatus.SCHEDULED.value,
                    InstallmentStatus.DUE.value,
                ]),
                Installment.due_date < overdue_cutoff,
            )
        ).scalars().all()
    )

    for inst in overdue_installments:
        inst.status = InstallmentStatus.OVERDUE.value
        results["to_overdue"] += 1
        results["details"].append({
            "installment_id": str(inst.id),
            "installment_number": inst.installment_number,
            "transition": f"{inst.status} → OVERDUE",
            "due_date": inst.due_date.isoformat(),
        })

    if overdue_installments:
        db.commit()

    logger.info(
        "Installment status processing: %d → DUE, %d → OVERDUE",
        results["to_due"],
        results["to_overdue"],
    )

    return results


def schedule_installment_reminder(
    db: Session,
    installment_id,
    hours_before_due: int = REMINDER_BEFORE_DUE_HOURS,
) -> dict:
    """Schedule a reminder for an installment before its due date.

    Rules:
    - Do NOT schedule for PAID installments
    - Do NOT create duplicate reminders (check existing pending)
    - Reminder is scheduled hours_before_due before the due_date

    Args:
        db: Database session
        installment_id: UUID of the installment
        hours_before_due: Hours before due date to send reminder

    Returns:
        dict with scheduling result
    """
    from app.crud.payment_plan import get_installment

    installment = get_installment(db, installment_id)
    if not installment:
        return {"status": "error", "reason": "installment_not_found"}

    # Rule: Do NOT send reminders for paid installments
    if installment.status == InstallmentStatus.PAID.value:
        return {"status": "skipped", "reason": "installment_already_paid"}

    # Rule: Do NOT send reminders for cancelled installments
    if installment.status == InstallmentStatus.CANCELLED.value:
        return {"status": "skipped", "reason": "installment_cancelled"}

    # Check for duplicate: any existing pending reminder for this installment
    from app.models.scheduled_action import ScheduledAction
    from sqlalchemy import select

    all_pending = list(
        db.execute(
            select(ScheduledAction).where(
                ScheduledAction.recovery_case_id == installment.recovery_case_id,
                ScheduledAction.action_type == "installment_reminder",
                ScheduledAction.status == "pending",
            )
        ).scalars().all()
    )

    existing = None
    for action in all_pending:
        meta = action.extra_data or {}
        if meta.get("installment_id") == str(installment.id):
            existing = action
            break

    if existing:
        return {
            "status": "skipped",
            "reason": "reminder_already_scheduled",
            "existing_action_id": str(existing.id),
        }

    # Calculate reminder time
    reminder_time = installment.due_date - timedelta(hours=hours_before_due)
    now = datetime.now(timezone.utc)

    # Make naive datetimes comparable with aware datetimes (SQLite compat)
    if reminder_time.tzinfo is None:
        reminder_time = reminder_time.replace(tzinfo=timezone.utc)

    # If reminder time is in the past, schedule immediately (but not for paid)
    if reminder_time <= now:
        reminder_time = now + timedelta(minutes=5)

    # Create the scheduled action
    action = create_scheduled_action(
        db,
        data=ScheduledActionCreate(
            recovery_case_id=installment.recovery_case_id,
            action_type="installment_reminder",
            attempt_number=installment.installment_number,
            channel="whatsapp",
            scheduled_for=reminder_time,
            extra_data={
                "installment_id": str(installment.id),
                "installment_number": installment.installment_number,
                "amount": installment.amount,
                "due_date": installment.due_date.isoformat(),
                "payment_plan_id": str(installment.payment_plan_id),
            },
        ),
    )

    logger.info(
        "Installment reminder scheduled: installment=%s, number=%d, reminder_at=%s",
        installment.id,
        installment.installment_number,
        reminder_time.isoformat(),
    )

    return {
        "status": "scheduled",
        "action_id": str(action.id),
        "installment_id": str(installment.id),
        "installment_number": installment.installment_number,
        "reminder_at": reminder_time.isoformat(),
        "due_date": installment.due_date.isoformat(),
    }


def record_installment_payment(
    db: Session,
    installment_id,
    amount: int,
    razorpay_payment_id: str | None = None,
) -> dict:
    """Record payment for an installment and update plan/case.

    Flow:
    1. Mark installment as PAID
    2. Update payment plan (amount_paid, installments_paid)
    3. Update case (recovered_amount, remaining_amount)
    4. If all installments paid → plan COMPLETED, case RECOVERED
    5. Cancel all future actions

    Args:
        db: Database session
        installment_id: UUID of the installment
        amount: Amount paid in paise
        razorpay_payment_id: Razorpay payment ID

    Returns:
        dict with payment result
    """
    from app.crud.payment_plan import get_installment

    installment = get_installment(db, installment_id)
    if not installment:
        return {"status": "error", "reason": "installment_not_found"}

    if installment.status == InstallmentStatus.PAID.value:
        return {"status": "skipped", "reason": "already_paid"}

    # Mark installment as paid
    mark_installment_paid(db, installment_id, amount, razorpay_payment_id)

    # Update plan totals
    plan = get_payment_plan(db, installment.payment_plan_id)
    if plan:
        plan.amount_paid += amount
        plan.installments_paid += 1
        db.commit()
        db.refresh(plan)

    # Update case recovered amount
    case = get_recovery_case(db, installment.recovery_case_id)
    if case:
        case.recovered_amount += amount
        case.remaining_amount = max(0, case.original_amount - case.recovered_amount)

        # Check if plan is complete (all installments paid)
        if plan and plan.installments_paid >= plan.number_of_installments:
            # Mark plan as COMPLETED
            update_plan_status(db, plan.id, PaymentPlanStatus.COMPLETED.value)

            # Mark case as RECOVERED
            case.status = RecoveryStatus.RECOVERED
            case.closed_at = datetime.now(timezone.utc)

            # Cancel all future actions
            cancelled = cancel_pending_actions_for_case(
                db, case.id, reason="payment_plan_completed"
            )

            logger.info(
                "Payment plan COMPLETED: case=%s, plan=%s, cancelled=%d actions",
                case.id,
                plan.id,
                cancelled,
            )

            return {
                "status": "paid",
                "installment_id": str(installment.id),
                "amount": amount,
                "installment_number": installment.installment_number,
                "plan_completed": True,
                "case_recovered": True,
                "actions_cancelled": cancelled,
                "recovered_amount": case.recovered_amount,
                "remaining_amount": case.remaining_amount,
            }
        else:
            # Partial payment - update case status
            if case.status in (RecoveryStatus.RECOVERY_IN_PROGRESS, RecoveryStatus.PROMISED, RecoveryStatus.SCHEDULED):
                case.status = RecoveryStatus.PARTIALLY_RECOVERED

        db.commit()

    # Audit
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=installment.recovery_case_id,
            entity_type="installment",
            entity_id=installment.id,
            action="installment_paid",
            new_value={
                "installment_id": str(installment.id),
                "amount": amount,
                "installment_number": installment.installment_number,
                "razorpay_payment_id": razorpay_payment_id,
                "plan_installments_paid": plan.installments_paid if plan else 0,
                "plan_installments_total": plan.number_of_installments if plan else 0,
            },
        ),
    )

    return {
        "status": "paid",
        "installment_id": str(installment.id),
        "amount": amount,
        "installment_number": installment.installment_number,
        "plan_completed": False,
        "case_recovered": False,
        "recovered_amount": case.recovered_amount if case else 0,
        "remaining_amount": case.remaining_amount if case else 0,
    }


def record_installment_failure(
    db: Session,
    installment_id,
    reason: str = "payment_failed",
) -> dict:
    """Record failure for an installment.

    Flow:
    1. Mark installment as FAILED
    2. Create bounded recovery for the failed amount
    3. Check if plan should be DEFAULTED (too many failures)

    Args:
        db: Database session
        installment_id: UUID of the installment
        reason: Failure reason

    Returns:
        dict with failure result
    """
    from app.crud.payment_plan import get_installment

    installment = get_installment(db, installment_id)
    if not installment:
        return {"status": "error", "reason": "installment_not_found"}

    if installment.status == InstallmentStatus.PAID.value:
        return {"status": "skipped", "reason": "already_paid"}

    # Mark installment as failed
    mark_installment_failed(db, installment_id, reason)

    # Update plan failed count
    plan = get_payment_plan(db, installment.payment_plan_id)
    defaulted = False
    if plan:
        plan.installments_failed += 1
        db.commit()
        db.refresh(plan)

        # Check if too many failures (defaulted)
        failure_threshold = max(1, plan.number_of_installments // 2)
        if plan.installments_failed >= failure_threshold:
            update_plan_status(db, plan.id, PaymentPlanStatus.DEFAULTED.value)
            defaulted = True
            logger.info(
                "Payment plan DEFAULTED: case=%s, plan=%s, failures=%d",
                installment.recovery_case_id,
                plan.id,
                plan.installments_failed,
            )

    # Audit
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=installment.recovery_case_id,
            entity_type="installment",
            entity_id=installment.id,
            action="installment_failed",
            new_value={
                "installment_id": str(installment.id),
                "reason": reason,
                "installment_number": installment.installment_number,
                "amount": installment.amount,
                "plan_defaulted": defaulted,
            },
        ),
    )

    return {
        "status": "failed",
        "installment_id": str(installment.id),
        "amount": installment.amount,
        "installment_number": installment.installment_number,
        "reason": reason,
        "plan_defaulted": defaulted,
    }


def get_installment_workflow_status(db: Session, plan_id) -> dict:
    """Get the workflow status of all installments in a plan.

    Returns:
        dict with installment statuses and summary
    """
    plan = get_payment_plan(db, plan_id)
    if not plan:
        return {"status": "error", "reason": "plan_not_found"}

    installments = get_installments_for_plan(db, plan_id)

    summary = {
        "total": len(installments),
        "paid": 0,
        "due": 0,
        "scheduled": 0,
        "failed": 0,
        "overdue": 0,
        "cancelled": 0,
    }

    installment_details = []
    for inst in installments:
        status_key = inst.status.lower()
        if status_key in summary:
            summary[status_key] += 1

        installment_details.append({
            "id": str(inst.id),
            "number": inst.installment_number,
            "amount": inst.amount,
            "status": inst.status,
            "due_date": inst.due_date.isoformat() if inst.due_date else None,
            "paid_at": inst.paid_at.isoformat() if inst.paid_at else None,
            "paid_amount": inst.paid_amount,
            "failed_at": inst.failed_at.isoformat() if inst.failed_at else None,
            "failure_reason": inst.failure_reason,
        })

    return {
        "plan_id": str(plan_id),
        "plan_status": plan.status,
        "summary": summary,
        "installments": installment_details,
        "revenue_map": {
            "original_at_risk": plan.total_amount,
            "paid": plan.amount_paid,
            "scheduled": sum(
                inst.amount for inst in installments
                if inst.status in (InstallmentStatus.SCHEDULED.value, InstallmentStatus.DUE.value)
            ),
            "remaining": plan.total_amount - plan.amount_paid,
        },
    }


def cancel_all_installment_reminders(
    db: Session,
    case_id,
    reason: str = "plan_completed",
) -> int:
    """Cancel all pending installment reminders for a case.

    Called when:
    - Payment plan is completed
    - Case is recovered
    - Customer requests stop

    Returns:
        Number of actions cancelled
    """
    from app.models.scheduled_action import ScheduledAction
    from sqlalchemy import select

    pending_reminders = list(
        db.execute(
            select(ScheduledAction).where(
                ScheduledAction.recovery_case_id == case_id,
                ScheduledAction.action_type == "installment_reminder",
                ScheduledAction.status == "pending",
            )
        ).scalars().all()
    )

    count = 0
    for action in pending_reminders:
        action.status = "cancelled"
        action.cancelled_at = datetime.now(timezone.utc)
        action.cancellation_reason = reason
        count += 1

    if count:
        db.commit()
        logger.info(
            "Cancelled %d installment reminders for case %s (reason: %s)",
            count,
            case_id,
            reason,
        )

    return count
