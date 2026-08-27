import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.scheduled_action import ScheduledAction
from app.schemas.scheduled_action import ScheduledActionCreate


def create_scheduled_action(
    db: Session, data
) -> ScheduledAction:
    """Create a new scheduled action.

    Args:
        data: Either a ScheduledActionCreate model or a dict with the required fields.
    """
    if isinstance(data, dict):
        action = ScheduledAction(**data)
    else:
        action = ScheduledAction(**data.model_dump())
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def get_scheduled_action(
    db: Session, action_id: uuid.UUID
) -> ScheduledAction | None:
    """Get a single scheduled action by ID."""
    return db.execute(
        select(ScheduledAction).where(ScheduledAction.id == action_id)
    ).scalar_one_or_none()


def get_pending_actions_for_case(
    db: Session, case_id: uuid.UUID
) -> list[ScheduledAction]:
    """Get all pending scheduled actions for a recovery case."""
    return list(
        db.execute(
            select(ScheduledAction).where(
                ScheduledAction.recovery_case_id == case_id,
                ScheduledAction.status == "pending",
            )
        ).scalars().all()
    )


def get_due_actions(db: Session) -> list[ScheduledAction]:
    """Get all pending actions whose scheduled_for time has passed.

    These are candidates for execution.
    Uses naive UTC datetime for SQLite compatibility (SQLite stores naive datetimes).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return list(
        db.execute(
            select(ScheduledAction).where(
                ScheduledAction.status == "pending",
                ScheduledAction.scheduled_for <= now,
            )
        ).scalars().all()
    )


def mark_action_executed(
    db: Session, action_id: uuid.UUID
) -> ScheduledAction | None:
    """Mark a scheduled action as executed."""
    action = get_scheduled_action(db, action_id)
    if action:
        action.status = "executed"
        action.executed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(action)
    return action


def cancel_action(
    db: Session,
    action_id: uuid.UUID,
    reason: str,
) -> ScheduledAction | None:
    """Cancel a scheduled action with a reason."""
    action = get_scheduled_action(db, action_id)
    if action:
        action.status = "cancelled"
        action.cancelled_at = datetime.now(timezone.utc)
        action.cancellation_reason = reason
        db.commit()
        db.refresh(action)
    return action


def cancel_pending_actions_for_case(
    db: Session,
    case_id: uuid.UUID,
    reason: str,
) -> int:
    """Cancel all pending scheduled actions for a recovery case.

    Returns the number of actions cancelled.
    """
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(ScheduledAction)
        .where(
            ScheduledAction.recovery_case_id == case_id,
            ScheduledAction.status == "pending",
        )
        .values(
            status="cancelled",
            cancelled_at=now,
            cancellation_reason=reason,
        )
    )
    db.commit()
    return result.rowcount


def get_actions_by_case(
    db: Session, case_id: uuid.UUID
) -> list[ScheduledAction]:
    """Get all scheduled actions for a recovery case (any status)."""
    return list(
        db.execute(
            select(ScheduledAction).where(
                ScheduledAction.recovery_case_id == case_id
            )
        ).scalars().all()
    )
