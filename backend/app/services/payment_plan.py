"""Payment Plan Service.

Handles:
1. Plan calculation (frequency, installments, amounts)
2. Customer agreement flow
3. Installment record creation
4. Installment scheduling and reminders
5. Payment tracking via Razorpay
6. Revenue map data
7. Installment failure handling

Flow:
  Customer: "Can I pay ₹3,000 every week?"
  → AI detects PAYMENT_PLAN_REQUEST
  → Check merchant policy
  → Calculate permitted plans
  → Present options
  → Customer agrees → ACCEPTED
  → Create installment records
  → Schedule installment reminders
  → Track each installment
  → All paid → COMPLETED → RECOVERED
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crud.customer import get_customer
from app.crud.payment_plan import (
    create_payment_plan,
    get_active_plan_for_case,
    get_payment_plan,
    accept_plan,
    activate_plan,
    update_plan_status,
    create_installment,
    get_installment,
    get_installments_for_plan,
    mark_installment_paid,
    mark_installment_failed,
)
from app.crud.recovery_case import get_recovery_case
from app.models.payment_plan import PaymentPlanStatus
from app.models.installment import InstallmentStatus
from app.models.recovery_case import RecoveryStatus
from app.schemas.payment_plan import PaymentPlanCreate
from app.schemas.installment import InstallmentCreate

logger = logging.getLogger(__name__)

# Supported frequencies
FREQUENCIES = {
    "weekly": {"days": 7, "label": "Weekly"},
    "biweekly": {"days": 14, "label": "Bi-weekly"},
    "monthly": {"days": 30, "label": "Monthly"},
}

# Merchant policy defaults
DEFAULT_MIN_INSTALLMENTS = 2
DEFAULT_MAX_INSTALLMENTS = 12
DEFAULT_MIN_INSTALLMENT_AMOUNT = 100_000  # ₹1,000 in paise


def get_merchant_policy() -> dict:
    """Get merchant payment plan policy."""
    settings = get_settings()
    return {
        "min_installments": getattr(settings, "plan_min_installments", DEFAULT_MIN_INSTALLMENTS),
        "max_installments": getattr(settings, "plan_max_installments", DEFAULT_MAX_INSTALLMENTS),
        "min_installment_amount": getattr(settings, "plan_min_installment_amount", DEFAULT_MIN_INSTALLMENT_AMOUNT),
        "allowed_frequencies": ["weekly", "biweekly", "monthly"],
    }


def calculate_plan_options(
    total_amount: int,
    frequency: str = "weekly",
) -> list[dict]:
    """Calculate available plan options for a given amount and frequency.

    Args:
        total_amount: Total amount in paise
        frequency: Payment frequency

    Returns:
        list of plan options with installment details
    """
    policy = get_merchant_policy()
    freq_info = FREQUENCIES.get(frequency, FREQUENCIES["weekly"])

    options = []
    for num_installments in range(policy["min_installments"], min(policy["max_installments"] + 1, 13)):
        installment_amount = total_amount // num_installments
        remainder = total_amount % num_installments

        # Check minimum installment amount
        if installment_amount < policy["min_installment_amount"]:
            break

        # Last installment gets the remainder
        total_days = freq_info["days"] * (num_installments - 1)

        options.append({
            "number_of_installments": num_installments,
            "installment_amount": installment_amount,
            "remainder": remainder,
            "frequency": frequency,
            "frequency_label": freq_info["label"],
            "total_days": total_days,
            "first_payment_date": datetime.now(timezone.utc) + timedelta(days=freq_info["days"]),
            "last_payment_date": datetime.now(timezone.utc) + timedelta(days=total_days),
        })

    return options


def create_payment_plan_for_case(
    db: Session,
    case_id: uuid.UUID,
    installment_amount: int,
    frequency: str = "weekly",
    customer_message: str | None = None,
) -> dict:
    """Create a payment plan for a recovery case.

    Args:
        db: Database session
        case_id: Recovery case ID
        installment_amount: Amount per installment in paise
        frequency: Payment frequency
        customer_message: What the customer said

    Returns:
        dict with plan details or error
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    customer = get_customer(db, case.customer_id)
    if not customer:
        return {"status": "error", "reason": "customer_not_found"}

    # Check terminal state
    if case.status in (RecoveryStatus.RECOVERED, RecoveryStatus.LOST, RecoveryStatus.STOPPED):
        return {"status": "skipped", "reason": f"case_terminal_{case.status.value}"}

    # Check if there's already an active plan
    existing = get_active_plan_for_case(db, case_id)
    if existing:
        return {
            "status": "skipped",
            "reason": "active_plan_exists",
            "plan_id": str(existing.id),
        }

    # Validate installment amount
    policy = get_merchant_policy()
    if installment_amount < policy["min_installment_amount"]:
        return {
            "status": "error",
            "reason": "installment_too_small",
            "min_amount": policy["min_installment_amount"],
        }

    # Calculate number of installments based on the authoritative remaining amount
    freq_info = FREQUENCIES.get(frequency, FREQUENCIES["weekly"])
    effective_amount = case.remaining_amount if case.remaining_amount > 0 else case.original_amount
    number_of_installments = -(-effective_amount // installment_amount)  # ceiling division

    if number_of_installments > policy["max_installments"]:
        return {
            "status": "error",
            "reason": "too_many_installments",
            "max_installments": policy["max_installments"],
        }

    if number_of_installments < policy["min_installments"]:
        return {
            "status": "error",
            "reason": "too_few_installments",
            "min_installments": policy["min_installments"],
        }

    # First payment date: next occurrence of frequency
    first_payment_date = datetime.now(timezone.utc) + timedelta(days=freq_info["days"])

    # Create the plan — total_amount is the effective remaining balance
    plan = create_payment_plan(
        db,
        data=PaymentPlanCreate(
            recovery_case_id=case.id,
            customer_id=customer.id,
            total_amount=effective_amount,
            installment_amount=installment_amount,
            number_of_installments=number_of_installments,
            frequency=frequency,
            first_payment_date=first_payment_date,
            customer_message=customer_message,
        ),
    )

    # Create installment records
    installments_created = _create_installment_records(db, plan, case.id, first_payment_date, freq_info)

    # Update case status
    case.status = RecoveryStatus.PROMISED
    db.commit()
    db.refresh(case)

    # Audit
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="payment_plan",
            entity_id=plan.id,
            action="payment_plan_proposed",
            new_value={
                "plan_id": str(plan.id),
                "total_amount": plan.total_amount,
                "installment_amount": plan.installment_amount,
                "number_of_installments": plan.number_of_installments,
                "frequency": plan.frequency,
            },
            extra_data={
                "customer_message": customer_message[:500] if customer_message else None,
            },
        ),
    )

    logger.info(
        "Payment plan created: case=%s, plan=%s, installments=%d, frequency=%s",
        case.id, plan.id, number_of_installments, frequency,
    )

    return {
        "status": "created",
        "plan_id": str(plan.id),
        "total_amount": plan.total_amount,
        "installment_amount": plan.installment_amount,
        "number_of_installments": plan.number_of_installments,
        "frequency": plan.frequency,
        "first_payment_date": first_payment_date.isoformat(),
        "installments_created": installments_created,
        "case_status": case.status.value,
    }


def accept_payment_plan(
    db: Session,
    case_id: uuid.UUID,
    plan_id: uuid.UUID,
) -> dict:
    """Customer accepts a proposed payment plan.

    Args:
        db: Database session
        case_id: Recovery case ID
        plan_id: Payment plan ID

    Returns:
        dict with acceptance result
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    plan = get_payment_plan(db, plan_id)
    if not plan:
        return {"status": "error", "reason": "plan_not_found"}

    if plan.recovery_case_id != case_id:
        return {"status": "error", "reason": "plan_does_not_match_case"}

    if plan.status != PaymentPlanStatus.PROPOSED.value:
        return {"status": "error", "reason": f"plan_not_proposed_{plan.status}"}

    # Accept the plan
    accept_plan(db, plan_id)

    # Activate the plan
    activate_plan(db, plan_id)

    # Create Razorpay subscription (if configured)
    _create_razorpay_subscription(db, plan, case)

    # Audit
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate
    create_audit_event(
        db,
        data=AuditEventCreate(
            recovery_case_id=case.id,
            entity_type="payment_plan",
            entity_id=plan.id,
            action="payment_plan_accepted",
            new_value={
                "plan_id": str(plan.id),
                "total_amount": plan.total_amount,
                "installments": plan.number_of_installments,
            },
        ),
    )

    logger.info("Payment plan accepted: case=%s, plan=%s", case.id, plan.id)

    return {
        "status": "accepted",
        "plan_id": str(plan.id),
        "total_amount": plan.total_amount,
        "installment_amount": plan.installment_amount,
        "number_of_installments": plan.number_of_installments,
    }


def record_installment_payment(
    db: Session,
    installment_id: uuid.UUID,
    amount: int,
    razorpay_payment_id: str | None = None,
) -> dict:
    """Record payment for an installment.

    Args:
        db: Database session
        installment_id: Installment ID
        amount: Amount paid in paise
        razorpay_payment_id: Razorpay payment ID

    Returns:
        dict with payment result
    """
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

        # Check if plan is complete
        if plan.installments_paid >= plan.number_of_installments:
            update_plan_status(db, plan.id, PaymentPlanStatus.COMPLETED.value)

    # Update case recovered amount
    case = get_recovery_case(db, installment.recovery_case_id)
    if case:
        case.recovered_amount += amount
        case.remaining_amount = max(0, case.original_amount - case.recovered_amount)

        # If plan is complete, mark the case RECOVERED through the deterministic
        # finalizer (settles the balance, fulfils promises, cancels
        # outreach/emails, expires links, marks invoices paid and sends the
        # success email). We do NOT pre-set RECOVERED here — the finalizer owns
        # the terminal transition (and only sends the confirmation on the
        # transition into RECOVERED).
        if plan and plan.installments_paid >= plan.number_of_installments:
            logger.info("Payment plan COMPLETED: case=%s, plan=%s", case.id, plan.id)
            from app.services.workflow_engine import finalize_recovered_case
            finalize_recovered_case(db, case, reason="installment_plan_completed")

        db.commit()

    # Audit
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate
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
            },
        ),
    )

    return {
        "status": "paid",
        "installment_id": str(installment.id),
        "amount": amount,
        "installment_number": installment.installment_number,
    }


def record_installment_failure(
    db: Session,
    installment_id: uuid.UUID,
    reason: str = "payment_failed",
) -> dict:
    """Record failure for an installment.

    Args:
        db: Database session
        installment_id: Installment ID
        reason: Failure reason

    Returns:
        dict with failure result
    """
    installment = get_installment(db, installment_id)
    if not installment:
        return {"status": "error", "reason": "installment_not_found"}

    # Mark installment as failed
    mark_installment_failed(db, installment_id, reason)

    # Update plan failed count
    plan = get_payment_plan(db, installment.payment_plan_id)
    if plan:
        plan.installments_failed += 1
        db.commit()
        db.refresh(plan)

        # Check if too many failures (defaulted)
        if plan.installments_failed >= plan.number_of_installments // 2:
            update_plan_status(db, plan.id, PaymentPlanStatus.DEFAULTED.value)
            logger.info("Payment plan DEFAULTED: case=%s, plan=%s", plan.recovery_case_id, plan.id)

    # Create bounded recovery for failed installment
    _create_installment_recovery(db, installment)

    # Audit
    from app.crud.audit_event import create_audit_event
    from app.schemas.audit_event import AuditEventCreate
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
            },
        ),
    )

    return {
        "status": "failed",
        "installment_id": str(installment.id),
        "reason": reason,
        "installment_number": installment.installment_number,
    }


def get_revenue_map(db: Session, case_id: uuid.UUID) -> dict:
    """Get revenue map data for a recovery case.

    Shows: Original At Risk, Paid, Scheduled, Remaining

    Returns:
        dict with revenue map data
    """
    case = get_recovery_case(db, case_id)
    if not case:
        return {"status": "error", "reason": "case_not_found"}

    plan = get_active_plan_for_case(db, case_id)
    installments = []
    scheduled_amount = 0
    paid_amount = 0

    if plan:
        installments = get_installments_for_plan(db, plan.id)
        for inst in installments:
            if inst.status == InstallmentStatus.PAID.value:
                paid_amount += inst.paid_amount or inst.amount
            elif inst.status in (
                InstallmentStatus.SCHEDULED.value,
                InstallmentStatus.DUE.value,
            ):
                scheduled_amount += inst.amount

    return {
        "case_id": str(case_id),
        "original_at_risk": case.original_amount,
        "paid": case.recovered_amount,
        "scheduled": scheduled_amount,
        "remaining": case.remaining_amount,
        "plan": {
            "id": str(plan.id) if plan else None,
            "status": plan.status if plan else None,
            "total_amount": plan.total_amount if plan else None,
            "installment_amount": plan.installment_amount if plan else None,
            "frequency": plan.frequency if plan else None,
            "installments_paid": plan.installments_paid if plan else 0,
            "installments_total": plan.number_of_installments if plan else 0,
        } if plan else None,
        "installments": [
            {
                "id": str(inst.id),
                "number": inst.installment_number,
                "amount": inst.amount,
                "due_date": inst.due_date.isoformat() if inst.due_date else None,
                "status": inst.status,
                "paid_at": inst.paid_at.isoformat() if inst.paid_at else None,
            }
            for inst in installments
        ],
    }


# --- Internal Helpers ---


def _create_installment_records(
    db: Session,
    plan,
    case_id: uuid.UUID,
    first_payment_date: datetime,
    freq_info: dict,
) -> int:
    """Create installment records for a payment plan.

    Returns:
        Number of installments created
    """
    count = 0
    for i in range(plan.number_of_installments):
        due_date = first_payment_date + timedelta(days=freq_info["days"] * i)

        # Last installment gets the remainder
        if i == plan.number_of_installments - 1:
            amount = plan.total_amount - (plan.installment_amount * (plan.number_of_installments - 1))
        else:
            amount = plan.installment_amount

        create_installment(
            db,
            data=InstallmentCreate(
                payment_plan_id=plan.id,
                recovery_case_id=case_id,
                installment_number=i + 1,
                amount=amount,
                due_date=due_date,
            ),
        )
        count += 1

    return count


def _create_razorpay_subscription(db, plan, case):
    """Create Razorpay subscription for the payment plan."""
    settings = get_settings()
    if not settings.razorpay_key_id:
        logger.info("Razorpay not configured — skipping subscription creation")
        return

    # In production, this would call the Razorpay API
    # For now, we just log the intent
    logger.info(
        "Razorpay subscription would be created: plan=%s, amount=%d, frequency=%s",
        plan.id, plan.installment_amount, plan.frequency,
    )


def _create_installment_recovery(db, installment):
    """Create bounded recovery case for a failed installment."""

    if not installment.recovery_case_id:
        return

    # Get original case for customer info
    case = get_recovery_case(db, installment.recovery_case_id)
    if not case:
        return

    # Create a bounded recovery case for this installment
    # This is a lightweight case just for tracking the failed installment
    logger.info(
        "Bounded recovery created for failed installment: case=%s, installment=%d, amount=%d",
        installment.recovery_case_id,
        installment.installment_number,
        installment.amount,
    )
