from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RecoveryAttemptCreate(BaseModel):
    recovery_case_id: UUID
    attempt_number: int
    channel: str  # "whatsapp", "email"
    status: str
    result: str | None = None
    extra_data: dict | None = None


class RecoveryAttemptRead(BaseModel):
    id: UUID
    recovery_case_id: UUID
    attempt_number: int
    channel: str
    status: str
    result: str | None
    extra_data: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
