from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.conversation import ConversationStatus


class ConversationCreate(BaseModel):
    recovery_case_id: UUID
    channel: str  # "whatsapp", "email"


class ConversationRead(BaseModel):
    id: UUID
    recovery_case_id: UUID
    channel: str
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
