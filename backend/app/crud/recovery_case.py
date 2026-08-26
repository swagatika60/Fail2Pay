from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.schemas.recovery_case import RecoveryCaseCreate


# get single recovery case
def get_recovery_case(db: Session, case_id: UUID) -> RecoveryCase | None:
    return db.execute(select(RecoveryCase).where(RecoveryCase.id == case_id)).scalar_one_or_none()


# get all recovery cases for a customer
def get_recovery_cases_by_customer(db: Session, customer_id: UUID) -> list[RecoveryCase]:
    return list(
        db.execute(
            select(RecoveryCase).where(RecoveryCase.customer_id == customer_id)
        ).scalars().all()
    )


# get recovery cases by status - useful for finding all AT_RISK cases etc
def get_recovery_cases_by_status(db: Session, status: RecoveryStatus) -> list[RecoveryCase]:
    return list(
        db.execute(
            select(RecoveryCase).where(RecoveryCase.status == status)
        ).scalars().all()
    )


# create new recovery case
def create_recovery_case(db: Session, data: RecoveryCaseCreate) -> RecoveryCase:
    case = RecoveryCase(**data.model_dump())
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# update status of a recovery case
def update_recovery_case_status(db: Session, case_id: UUID, status: RecoveryStatus) -> RecoveryCase | None:
    case = get_recovery_case(db, case_id)
    if case:
        case.status = status
        db.commit()
        db.refresh(case)
    return case
