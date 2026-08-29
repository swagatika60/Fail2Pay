"""Agent Flow: multi-turn WhatsApp recovery dialogue (demo driver).

Brings together the contextual copy from ``agent_engine`` with the real
bounded intent pipeline so that each simulated customer reply drives a full,
human-like dialogue cycle:

  Customer bubble -> (agent typing) -> contextual Agent reply + action payload

This module is intentionally deterministic. AI is used ONLY for bounded intent
classification; every status change, promise, payment plan and reply is decided
by code. Only verified captured payments ever count as recovered revenue.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import agent_engine


def _tomorrow_at_11am() -> datetime:
    """Tomorrow at 11:00 AM local (naive, DB-compatible) UTC-shifted time."""
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=11, minute=0, second=0, microsecond=0)


def schedule_reminder_tomorrow(db: Session, case_id, channel: str = "whatsapp") -> dict:
    """Schedule a promise reminder for tomorrow at 11:00 AM.

    Uses the same scheduled-action machinery as the orchestrator so the
    reminder can be executed by the scheduler and cancelled by hard stops.
    """
    from app.crud.scheduled_action import create_scheduled_action
    from app.schemas.scheduled_action import ScheduledActionCreate

    when = _tomorrow_at_11am()
    action = create_scheduled_action(
        db,
        data=ScheduledActionCreate(
            recovery_case_id=case_id,
            action_type="reminder",
            attempt_number=1,
            channel=channel,
            scheduled_for=when,
            extra_data={
                "reason": "promise_to_pay",
                "reminder_label": "Promise reminder at 11:00 AM",
            },
        ),
    )
    return {
        "action_id": str(action.id),
        "action_type": action.action_type,
        "scheduled_for": action.scheduled_for.isoformat(),
        "reminder_label": "reminder for tomorrow at 11:00 AM",
    }


def create_split_plan(db: Session, case, split_count: int = 2, days_apart: int = 15) -> dict:
    """Create a real split EMI plan for a case (arbitrary ``split_count``).

    Uses the merchant plan service so the plan is a genuine, payable plan. The
    exact per-installment amounts come from ``calculate_installments`` (integer
    division + remainder spread across the FIRST tranches) so the total is
    always preserved. Due dates are staged ``days_apart`` apart.

    Returns a dict with plan payload + the split summary for the agent copy.
    """
    from app.models.installment import Installment
    from app.services.payment_plan import (
        accept_payment_plan,
        create_payment_plan_for_case,
    )
    from sqlalchemy import select

    amount = case.original_amount
    amounts = agent_engine.calculate_installments(amount, split_count)
    base = amounts[0]

    frequency = "biweekly" if days_apart >= 14 else "weekly"
    plan_result = create_payment_plan_for_case(
        db,
        case.id,
        installment_amount=base,
        frequency=frequency,
        customer_message=f"customer_requested_{split_count}_emi_split",
    )

    if plan_result.get("status") == "error":
        return {
            "plan_status": "error",
            "reason": plan_result.get("reason", "unknown_error"),
            "split": agent_engine.split_plan_payload(amount, count=split_count),
            "amounts": amounts,
        }

    plan_id = plan_result.get("plan_id")
    if plan_id:
        plan_uuid = uuid.UUID(plan_id)
        if plan_result.get("status") in ("created",):
            accept_payment_plan(db, case.id, plan_uuid)

        # Overwrite each installment amount so remainder lands on the FIRST
        # tranches (matches calculate_installments), not the last one.
        installments = list(
            db.execute(
                select(Installment)
                .where(Installment.payment_plan_id == plan_uuid)
                .order_by(Installment.installment_number)
            ).scalars().all()
        )
        for i, inst in enumerate(installments):
            inst.amount = amounts[i] if i < len(amounts) else base
        db.commit()

    return {
        "plan_status": plan_result.get("status"),
        "plan_id": plan_id,
        "split_count": split_count,
        "split": agent_engine.split_plan_payload(amount, count=split_count),
        "amounts": amounts,
        "amounts_formatted": agent_engine.split_summary(amount, split_count)["amounts_formatted"],
    }


def persist_agent_reply(
    db: Session,
    case,
    reply_text: str,
    agent_payload: dict | None,
    channel: str = "whatsapp",
) -> None:
    """Write the outbound Agent bubble (with its action payload) to the thread.

    The payload is stored in the message ``extra_data`` so the UI can re-render
    the thread from the database without any client-side state.
    """
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage

    conversation = (
        db.execute(
            select(Conversation)
            .where(
                Conversation.recovery_case_id == case.id,
                Conversation.channel == channel,
            )
            .order_by(Conversation.created_at.desc())
        ).scalars().first()
    )

    if conversation is None:
        from app.models.conversation import ConversationStatus

        conversation = Conversation(
            recovery_case_id=case.id,
            channel=channel,
            status=ConversationStatus.ACTIVE,
            extra_data={"source": "agent_engine"},
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            direction="outbound",
            content=reply_text,
            message_type="text",
            extra_data={
                "source": "agent_engine",
                "is_reply": True,
                "agent_payload": agent_payload,
            },
        )
    )
    db.commit()
