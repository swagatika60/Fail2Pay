from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# schema for creating a customer
class CustomerCreate(BaseModel):
    external_id: str  # razorpay customer id
    email: str | None = None
    phone: str | None = None
    name: str | None = None


# schema for reading customer data back
class CustomerRead(BaseModel):
    id: UUID
    external_id: str
    email: str | None
    phone: str | None
    name: str | None
    created_at: datetime
    updated_at: datetime

    # this lets pydantic read from sqlalchemy model attributes
    model_config = {"from_attributes": True}
