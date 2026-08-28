import enum
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Enum, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConversationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    RESOLVED = "RESOLVED"


class Conversation(Base):
    # conversation with customer - whatsapp or email thread
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recovery_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    channel: Mapped[str] = mapped_column(String(50))  # "whatsapp", "email"
    status: Mapped[ConversationStatus] = mapped_column(Enum(ConversationStatus), default=ConversationStatus.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # metadata (e.g. language preference "en"/"hi"/"hi-en"/"or")
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # relationships
    recovery_case = relationship("RecoveryCase", back_populates="conversations")
    messages = relationship("ConversationMessage", back_populates="conversation")
