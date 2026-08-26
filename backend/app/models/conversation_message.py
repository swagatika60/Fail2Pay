import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConversationMessage(Base):
    # individual message in a conversation
    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # "inbound" or "outbound"
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(50), default="text")  # "text", "image", "document"
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # relationships
    conversation = relationship("Conversation", back_populates="messages")
