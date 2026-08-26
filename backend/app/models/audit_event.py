import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditEvent(Base):
    # audit log - track every change for debugging
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)  # "recovery_case", "payment_plan" etc
    entity_id: Mapped[uuid.UUID] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(50))  # "created", "updated", "status_changed"
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # relationships
    recovery_case = relationship("RecoveryCase", back_populates="audit_events")
