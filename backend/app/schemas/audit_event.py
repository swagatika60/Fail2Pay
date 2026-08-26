from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditEventCreate(BaseModel):
    recovery_case_id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    old_value: dict | None = None
    new_value: dict | None = None
    extra_data: dict | None = None


class AuditEventRead(BaseModel):
    id: UUID
    recovery_case_id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    old_value: dict | None
    new_value: dict | None
    extra_data: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
