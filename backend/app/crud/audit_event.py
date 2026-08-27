from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.schemas.audit_event import AuditEventCreate


def create_audit_event(db: Session, data: AuditEventCreate) -> AuditEvent:
    """Create a new audit event entry."""
    event = AuditEvent(**data.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
