from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ConversationMessageCreate(BaseModel):
    conversation_id: UUID
    direction: str  # "inbound" or "outbound"
    content: str
    message_type: str = "text"
    extra_data: dict | None = None


class ConversationMessageRead(BaseModel):
    id: UUID
    conversation_id: UUID
    direction: str
    content: str
    message_type: str
    extra_data: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
