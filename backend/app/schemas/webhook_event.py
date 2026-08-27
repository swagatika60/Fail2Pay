from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WebhookEventRead(BaseModel):
    id: UUID
    event_id: str
    event_type: str
    payment_id: str | None
    processed_at: datetime

    model_config = {"from_attributes": True}
