from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SentEmailCreate(BaseModel):
    recovery_case_id: UUID | None = None
    recipient_email: str
    subject: str
    body: str
    email_type: str  # EmailType value
    provider_message_id: str | None = None
    provider_response: dict | None = None
    error_message: str | None = None


class SentEmailRead(BaseModel):
    id: UUID
    recovery_case_id: UUID | None
    recipient_email: str
    subject: str
    body: str
    email_type: str
    delivery_status: str
    provider_message_id: str | None
    provider_response: dict | None
    error_message: str | None
    sent_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
