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
    """Tomorrow at 11:00 AM India time (Asia/Kolkata), as aware UTC.

    Mirrors the agent copy ("kal 11:00 baje reminder bhejenge") so the queued
    promise reminder fires at 11:00 IST, not 11:00 UTC.
    """
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    now_ist = datetime.now(timezone.utc).astimezone(ist)
    tomorrow_ist = now_ist + timedelta(days=1)
    when_ist = tomorrow_ist.replace(hour=11, minute=0, second=0, microsecond=0)
    return when_ist.astimezone(timezone.utc)


def promise_date_for(option: str, custom: datetime | None = None) -> datetime:
    """Deterministic promised-payment datetime for a promise option.

    All promise dates normalize to 11:00 AM IST (matching the agent copy and
    the default "reminder for tomorrow at 11:00 AM") so the Promise and the
    ScheduledAction always stay in sync:

      - "tomorrow" -> next day at 11:00 IST
      - "3days"    -> three days from now at 11:00 IST
      - "custom"   -> the merchant-supplied datetime normalized to 11:00 IST on
                      that day; a past/missing date falls back to tomorrow
                      11:00 IST so a reminder is never scheduled in the past.
    """
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")

    if option == "3days":
        base_ist = (datetime.now(timezone.utc) + timedelta(days=3)).astimezone(ist)
        return base_ist.replace(hour=11, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    if option == "custom" and custom is not None:
        cust = custom
        if cust.tzinfo is None:
            cust = cust.replace(tzinfo=timezone.utc)
        cust_ist = cust.astimezone(ist)
        when_ist = cust_ist.replace(hour=11, minute=0, second=0, microsecond=0)
        if when_ist > datetime.now(timezone.utc).astimezone(ist):
            return when_ist.astimezone(timezone.utc)

    return _tomorrow_at_11am()


def schedule_reminder_tomorrow(
    db: Session,
    case_id,
    channel: str = "whatsapp",
    at: datetime | None = None,
) -> dict:
    """Schedule a promise reminder (default: tomorrow at 11:00 AM).

    ``at`` lets the contextual promise-date options persist the exact promised
    date/time so the ScheduledAction fires at the promised moment. Uses the
    same scheduled-action machinery as the orchestrator so the reminder can be
    executed by the scheduler and cancelled by hard stops.
    """
    from app.crud.scheduled_action import create_scheduled_action
    from app.schemas.scheduled_action import ScheduledActionCreate

    when = at or _tomorrow_at_11am()
    if at is not None:
        reminder_label = f"promise reminder on {when.astimezone(timezone.utc).strftime('%d %b %Y')}"
    else:
        reminder_label = "reminder for tomorrow at 11:00 AM"
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
                "reminder_label": reminder_label,
            },
        ),
    )

    # Typed domain event so the live console badges the queued promise reminder.
    from app.services.realtime import publish_case_event

    publish_case_event(
        event_type="scheduled_action_created",
        case_id=str(case_id),
        data={
            "action_id": str(action.id),
            "action_type": action.action_type,
            "scheduled_for": action.scheduled_for.isoformat() if action.scheduled_for else None,
            "reason": "promise_to_pay",
        },
    )

    return {
        "action_id": str(action.id),
        "action_type": action.action_type,
        "scheduled_for": action.scheduled_for.isoformat(),
        "reminder_label": reminder_label,
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

    # Use the authoritative remaining amount from the DB — never original_amount
    # for a partially-recovered case.
    amount = case.remaining_amount if case.remaining_amount > 0 else case.original_amount
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

    # Build the enterprise payment_plan payload for the broadcast
    payment_plan_payload = agent_engine._build_payment_plan_payload(
        total_amount_paise=amount,
        count=split_count,
        case_id=str(case.id),
    )

    # Broadcast the payment plan update to live dashboards
    from app.services.realtime import publish_payment_plan_updated, publish_case_state_updated

    publish_payment_plan_updated(
        case_id=str(case.id),
        plan=payment_plan_payload,
        installment_breakdown=agent_engine.split_summary(amount, split_count),
        policy_action={
            "increment_attempt_counter": False,
            "next_state": "PAYMENT_PLAN_PENDING",
        },
        action="created",
    )

    # Broadcast case state update so pipeline tracker reflects the plan
    publish_case_state_updated(
        case_id=str(case.id),
        new_status="PAYMENT_PLAN",
        payment_plan_status=plan_result.get("status"),
        remaining_amount=case.remaining_amount,
    )

    # Analytics: log the payment plan creation
    try:
        from app.services.audit_logger import log_payment_plan_proposed
        log_payment_plan_proposed(
            db,
            case.id,
            plan_id=plan_id,
            total=amount,
            installments=split_count,
            frequency=frequency,
        )
    except Exception:  # noqa: BLE001 - never let analytics break recovery
        pass

    return {
        "plan_status": plan_result.get("status"),
        "plan_id": plan_id,
        "split_count": split_count,
        "split": agent_engine.split_plan_payload(amount, count=split_count),
        "amounts": amounts,
        "amounts_formatted": agent_engine.split_summary(amount, split_count)["amounts_formatted"],
        "payment_plan": payment_plan_payload,
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

    msg = ConversationMessage(
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
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Push the Agent reply to live audit dashboards via WebSocket so it appears
    # in the live feed without a page reload.
    from app.services.realtime import publish_message_event

    publish_message_event(
        conversation_id=str(conversation.id),
        case_id=str(case.id),
        message_id=str(msg.id),
        direction="outbound",
        content=reply_text,
        message_type="text",
        created_at=msg.created_at.isoformat() if msg.created_at else "",
        extra_data=msg.extra_data,
    )

    # Push the context-aware quick-reply chips so the live console swaps the
    # chip set for THIS reply immediately (no refresh needed).
    if agent_payload:
        from app.services.realtime import publish_quick_replies_updated

        publish_quick_replies_updated(
            case_id=str(case.id),
            conversation_id=str(conversation.id),
            quick_replies=[
                {"id": qr.get("id"), "label": qr.get("label")}
                for qr in (agent_payload.get("quick_replies") or [])
                if isinstance(qr, dict)
            ],
        )

        # Broadcast payment plan updates if present in the agent payload
        payment_plan = agent_payload.get("payment_plan")
        installment_breakdown = agent_payload.get("installment_breakdown")
        policy_action = agent_payload.get("policy_action")
        if payment_plan or installment_breakdown:
            from app.services.realtime import publish_payment_plan_updated

            # Determine the action type based on the payload
            action = "created"
            if payment_plan and payment_plan.get("is_repeat"):
                action = "modified"
            elif payment_plan and any(
                inst.get("total_parts", 0) > 2
                for inst in payment_plan.get("installments", [])
            ):
                action = "updated"

            publish_payment_plan_updated(
                case_id=str(case.id),
                plan=payment_plan,
                installment_breakdown=installment_breakdown,
                policy_action=policy_action,
                action=action,
            )
