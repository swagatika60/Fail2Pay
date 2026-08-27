"""CRUD operations for Conversation and ConversationMessage."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, ConversationStatus
from app.models.conversation_message import ConversationMessage
from app.schemas.conversation import ConversationCreate
from app.schemas.conversation_message import ConversationMessageCreate


# --- Conversation CRUD ---


def create_conversation(db: Session, data: ConversationCreate) -> Conversation:
    """Create a new conversation."""
    conversation = Conversation(**data.model_dump())
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_conversation(db: Session, conversation_id: uuid.UUID) -> Conversation | None:
    """Get a single conversation by ID."""
    return db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    ).scalar_one_or_none()


def get_conversations_by_case(
    db: Session, case_id: uuid.UUID
) -> list[Conversation]:
    """Get all conversations for a recovery case."""
    return list(
        db.execute(
            select(Conversation).where(Conversation.recovery_case_id == case_id)
        ).scalars().all()
    )


def get_active_conversations_by_case(
    db: Session, case_id: uuid.UUID
) -> list[Conversation]:
    """Get active conversations for a recovery case."""
    return list(
        db.execute(
            select(Conversation).where(
                Conversation.recovery_case_id == case_id,
                Conversation.status == ConversationStatus.ACTIVE,
            )
        ).scalars().all()
    )


def get_conversations_by_channel(
    db: Session, case_id: uuid.UUID, channel: str
) -> list[Conversation]:
    """Get conversations for a case filtered by channel."""
    return list(
        db.execute(
            select(Conversation).where(
                Conversation.recovery_case_id == case_id,
                Conversation.channel == channel,
            )
        ).scalars().all()
    )


def update_conversation_status(
    db: Session, conversation_id: uuid.UUID, status: ConversationStatus
) -> Conversation | None:
    """Update conversation status."""
    conversation = get_conversation(db, conversation_id)
    if conversation:
        conversation.status = status
        db.commit()
        db.refresh(conversation)
    return conversation


# --- ConversationMessage CRUD ---


def create_conversation_message(
    db: Session, data: ConversationMessageCreate
) -> ConversationMessage:
    """Create a new conversation message."""
    message = ConversationMessage(**data.model_dump())
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_conversation_message(
    db: Session, message_id: uuid.UUID
) -> ConversationMessage | None:
    """Get a single message by ID."""
    return db.execute(
        select(ConversationMessage).where(ConversationMessage.id == message_id)
    ).scalar_one_or_none()


def get_messages_by_conversation(
    db: Session, conversation_id: uuid.UUID
) -> list[ConversationMessage]:
    """Get all messages for a conversation, ordered by creation time."""
    return list(
        db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at)
        ).scalars().all()
    )


def get_last_message_by_conversation(
    db: Session, conversation_id: uuid.UUID
) -> ConversationMessage | None:
    """Get the most recent message for a conversation."""
    return db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
