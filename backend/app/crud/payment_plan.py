import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.payment_plan import PaymentPlan, PaymentPlanStatus
from app.models.installment import Installment, InstallmentStatus
from app.schemas.payment_plan import PaymentPlanCreate
from app.schemas.installment import InstallmentCreate


# --- PaymentPlan CRUD ---


def create_payment_plan(db: Session, data: PaymentPlanCreate) -> PaymentPlan:
    """Create a new payment plan."""
    plan = PaymentPlan(**data.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def get_payment_plan(db: Session, plan_id: uuid.UUID) -> PaymentPlan | None:
    """Get a single payment plan by ID."""
    return db.execute(
        select(PaymentPlan).where(PaymentPlan.id == plan_id)
    ).scalar_one_or_none()


def get_active_plan_for_case(db: Session, case_id: uuid.UUID) -> PaymentPlan | None:
    """Get the active payment plan for a recovery case.

    Includes PROPOSED, ACCEPTED, and ACTIVE plans.
    """
    return db.execute(
        select(PaymentPlan).where(
            PaymentPlan.recovery_case_id == case_id,
            PaymentPlan.status.in_([
                PaymentPlanStatus.PROPOSED.value,
                PaymentPlanStatus.ACCEPTED.value,
                PaymentPlanStatus.ACTIVE.value,
            ]),
        )
    ).scalar_one_or_none()


def get_plans_by_case(db: Session, case_id: uuid.UUID) -> list[PaymentPlan]:
    """Get all payment plans for a recovery case."""
    return list(
        db.execute(
            select(PaymentPlan)
            .where(PaymentPlan.recovery_case_id == case_id)
            .order_by(PaymentPlan.created_at.desc())
        ).scalars().all()
    )


def update_plan_status(
    db: Session,
    plan_id: uuid.UUID,
    status: str,
) -> PaymentPlan | None:
    """Update payment plan status."""
    plan = get_payment_plan(db, plan_id)
    if plan:
        plan.status = status
        if status == PaymentPlanStatus.COMPLETED.value:
            plan.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(plan)
    return plan


def accept_plan(db: Session, plan_id: uuid.UUID) -> PaymentPlan | None:
    """Accept a proposed payment plan."""
    plan = get_payment_plan(db, plan_id)
    if plan:
        plan.status = PaymentPlanStatus.ACCEPTED.value
        plan.agreed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(plan)
    return plan


def activate_plan(db: Session, plan_id: uuid.UUID) -> PaymentPlan | None:
    """Activate an accepted payment plan."""
    plan = get_payment_plan(db, plan_id)
    if plan:
        plan.status = PaymentPlanStatus.ACTIVE.value
        db.commit()
        db.refresh(plan)
    return plan


# --- Installment CRUD ---


def create_installment(db: Session, data: InstallmentCreate) -> Installment:
    """Create a new installment."""
    installment = Installment(**data.model_dump())
    db.add(installment)
    db.commit()
    db.refresh(installment)
    return installment


def get_installment(db: Session, installment_id: uuid.UUID) -> Installment | None:
    """Get a single installment by ID."""
    return db.execute(
        select(Installment).where(Installment.id == installment_id)
    ).scalar_one_or_none()


def get_installments_for_plan(db: Session, plan_id: uuid.UUID) -> list[Installment]:
    """Get all installments for a payment plan."""
    return list(
        db.execute(
            select(Installment)
            .where(Installment.payment_plan_id == plan_id)
            .order_by(Installment.installment_number)
        ).scalars().all()
    )


def get_next_due_installment(db: Session, plan_id: uuid.UUID) -> Installment | None:
    """Get the next due installment for a plan."""
    return db.execute(
        select(Installment).where(
            Installment.payment_plan_id == plan_id,
            Installment.status.in_([
                InstallmentStatus.SCHEDULED.value,
                InstallmentStatus.DUE.value,
            ]),
        )
        .order_by(Installment.due_date)
        .limit(1)
    ).scalar_one_or_none()


def mark_installment_paid(
    db: Session,
    installment_id: uuid.UUID,
    amount: int,
    razorpay_payment_id: str | None = None,
) -> Installment | None:
    """Mark an installment as paid."""
    installment = get_installment(db, installment_id)
    if installment:
        installment.status = InstallmentStatus.PAID.value
        installment.paid_at = datetime.now(timezone.utc)
        installment.paid_amount = amount
        if razorpay_payment_id:
            installment.razorpay_payment_id = razorpay_payment_id
        db.commit()
        db.refresh(installment)
    return installment


def mark_installment_failed(
    db: Session,
    installment_id: uuid.UUID,
    reason: str = "payment_failed",
) -> Installment | None:
    """Mark an installment as failed."""
    installment = get_installment(db, installment_id)
    if installment:
        installment.status = InstallmentStatus.FAILED.value
        installment.failed_at = datetime.now(timezone.utc)
        installment.failure_reason = reason
        db.commit()
        db.refresh(installment)
    return installment


def mark_installment_overdue(db: Session, installment_id: uuid.UUID) -> Installment | None:
    """Mark an installment as overdue."""
    installment = get_installment(db, installment_id)
    if installment:
        installment.status = InstallmentStatus.OVERDUE.value
        db.commit()
        db.refresh(installment)
    return installment


def get_overdue_installments(db: Session) -> list[Installment]:
    """Get all overdue installments."""
    now = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(Installment).where(
                Installment.status.in_([
                    InstallmentStatus.DUE.value,
                    InstallmentStatus.SCHEDULED.value,
                ]),
                Installment.due_date <= now,
            )
        ).scalars().all()
    )


def get_installments_by_case(db: Session, case_id: uuid.UUID) -> list[Installment]:
    """Get all installments for a recovery case."""
    return list(
        db.execute(
            select(Installment)
            .where(Installment.recovery_case_id == case_id)
            .order_by(Installment.due_date)
        ).scalars().all()
    )


def count_installments_by_status(
    db: Session, plan_id: uuid.UUID, status: str
) -> int:
    """Count installments by status for a plan."""
    result = db.execute(
        select(func.count(Installment.id)).where(
            Installment.payment_plan_id == plan_id,
            Installment.status == status,
        )
    )
    return result.scalar() or 0
