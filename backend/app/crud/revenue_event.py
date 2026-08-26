from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.revenue_event import RevenueEvent
from app.schemas.revenue_event import RevenueEventCreate


# get single revenue event
def get_revenue_event(db: Session, event_id: UUID) -> RevenueEvent | None:
    return db.execute(select(RevenueEvent).where(RevenueEvent.id == event_id)).scalar_one_or_none()


# get all revenue events for a customer
def get_revenue_events_by_customer(db: Session, customer_id: UUID) -> list[RevenueEvent]:
    return list(
        db.execute(
            select(RevenueEvent).where(RevenueEvent.customer_id == customer_id)
        ).scalars().all()
    )


# create new revenue event
def create_revenue_event(db: Session, data: RevenueEventCreate) -> RevenueEvent:
    event = RevenueEvent(**data.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
