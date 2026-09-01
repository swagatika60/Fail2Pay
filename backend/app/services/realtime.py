"""Realtime WebSocket broadcast manager.

Pushes live WhatsApp audit events (new inbound/outbound messages, promise
reminders, status updates) to connected dashboard clients over
``/ws/cases/{case_id}``.

The manager is intentionally dependency-light: it only manages the set of
live connections per case and a run-serialized broadcast queue. Persistence
stays in the normal CRUD layer — this module only *notifies* subscribers.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class RealtimeManager:
    """Tracks active WebSocket connections per recovery case."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, case_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[case_id].add(websocket)
        logger.debug("realtime: client connected for case %s", case_id)

    async def disconnect(self, case_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(case_id)
            if conns:
                conns.discard(websocket)
                if not conns:
                    self._connections.pop(case_id, None)
        logger.debug("realtime: client disconnected for case %s", case_id)

    async def broadcast(self, case_id: str, event: dict) -> None:
        """Send an event to every live client for a case."""
        async with self._lock:
            conns = list(self._connections.get(str(case_id), set()))
        if not conns:
            return

        stale = []
        for websocket in conns:
            try:
                await websocket.send_json(event)
            except Exception:  # noqa: BLE001 - best-effort notify
                logger.warning(
                    "realtime: failed to send to a client for case %s", case_id
                )
                stale.append(websocket)

        for websocket in stale:
            await self.disconnect(str(case_id), websocket)


# Module-level singleton used across routes and services.
realtime_manager = RealtimeManager()

# Reference to the server's main event loop. Sync (threadpool) route handlers —
# e.g. the simulate-message demo driver — run off the event loop, so
# ``get_running_loop()`` is unavailable there. We capture the loop at startup
# (see bind_main_loop, wired from the FastAPI lifespan) and schedule broadcasts
# onto it thread-safely instead of silently dropping the live-feed push.
_main_loop = None


def bind_main_loop(loop) -> None:
    """Capture the server's main event loop for cross-thread broadcasts."""
    global _main_loop
    if loop is not None and not loop.is_closed():
        _main_loop = loop


def _schedule_broadcast(coro_factory) -> None:
    """Dispatch a broadcast coroutine onto the main event loop.

    ``coro_factory`` is a zero-arg callable returning the broadcast coroutine;
    the coroutine is only created once a loop is available to await it (avoids
    "coroutine never awaited" warnings in plain-script / no-loop contexts).

    Prefers the caller's running loop (async webhook/service context) and falls
    back to the loop captured at startup (sync route/threadpool context). When
    neither is available (plain scripts, some tests) the broadcast degrades to
    a no-op — the persistent store remains the source of truth.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro_factory())
        return
    except RuntimeError:
        pass

    loop = _main_loop
    if loop is None or loop.is_closed() or not loop.is_running():
        logger.debug("realtime: no running loop, skipping broadcast")
        return

    try:
        loop.call_soon_threadsafe(loop.create_task, coro_factory())
    except Exception:  # noqa: BLE001 - best-effort notify
        logger.debug("realtime: failed to schedule broadcast on main loop")


def build_message_event(
    *,
    conversation_id: str,
    case_id: str,
    message_id: str,
    direction: str,
    content: str,
    message_type: str,
    created_at: str,
    extra_data: dict | None = None,
) -> dict:
    """Serialize a persisted ConversationMessage into a ws event."""
    return {
        "type": "message",
        "conversation_id": conversation_id,
        "case_id": case_id,
        "message": {
            "id": message_id,
            "direction": direction,
            "content": content,
            "message_type": message_type,
            "extra_data": extra_data or {},
            "created_at": created_at,
        },
    }


def publish_message_event(**kwargs) -> None:
    """Fire-and-forget broadcast for a new conversation message.

    Safely invoked from sync service code: schedules the coroutine on the
    running event loop when available, otherwise onto the server's main loop
    captured at startup (see ``bind_main_loop``). Degrades to no-op when no
    loop is reachable — the background poll still reconciles the UI.
    """
    case_id = kwargs.get("case_id")
    if not case_id:
        return

    event = build_message_event(**kwargs)
    _schedule_broadcast(lambda: realtime_manager.broadcast(str(case_id), event))


def build_case_event(
    *,
    event_type: str,
    case_id: str,
    data: dict | None = None,
    occurred_at: str | None = None,
) -> dict:
    """Serialize a typed domain event (PROMISE_CREATED, REMINDER_SENT, etc.).

    Typed events carry a canonical ``event_type`` plus a ``data`` payload so
    the live console can render dedicated badges (payment captured, promise
    made, reminder sent, recovery completed) instead of only raw messages.
    """
    return {
        "type": "case_event",
        "event_type": event_type,
        "case_id": case_id,
        "occurred_at": occurred_at,
        "data": data or {},
    }


def publish_case_event(
    *,
    event_type: str,
    case_id: str,
    data: dict | None = None,
    occurred_at: str | None = None,
) -> None:
    """Fire-and-forget broadcast of a typed domain event to a case's clients."""
    if not case_id:
        return

    event = build_case_event(
        event_type=event_type,
        case_id=str(case_id),
        data=data,
        occurred_at=occurred_at,
    )
    _schedule_broadcast(lambda: realtime_manager.broadcast(str(case_id), event))


def build_agent_step_event(
    *,
    case_id: str,
    step: dict,
) -> dict:
    """Serialize a single agent reasoning step into a ws ``agent_step`` event.

    ``step`` carries the canonical ``step_id``, a ``stage`` (TRIGGER /
    DIAGNOSIS / POLICY / ACTION / LEDGER), a human ``label``, optional
    ``detail``, ``confidence`` and ``latency_ms`` plus ``occurred_at``. The
    dashboard appends these to the live "Agent Thought Stream" as they fire.
    """
    return {
        "type": "agent_step",
        "case_id": case_id,
        "step": step,
    }


def publish_agent_step(
    *,
    case_id: str,
    step: dict,
) -> None:
    """Fire-and-forget broadcast of one agent reasoning step to a case's
    WebSocket clients (the live Agent Thought Stream)."""
    if not case_id:
        return
    event = build_agent_step_event(case_id=str(case_id), step=step)
    _schedule_broadcast(lambda: realtime_manager.broadcast(str(case_id), event))


# ============================================================
# TYPING INDICATOR + REASONING STREAM + STATE SYNC EVENTS
# ============================================================


def publish_typing_indicator(
    *,
    case_id: str,
    is_typing: bool,
    agent_name: str = "Agent",
) -> None:
    """Broadcast a typing indicator to connected clients.

    When ``is_typing`` is True the frontend shows "Agent is typing…" in the
    conversation thread. When False it clears the indicator.
    """
    if not case_id:
        return
    event = {
        "type": "typing_indicator",
        "case_id": str(case_id),
        "is_typing": is_typing,
        "agent_name": agent_name,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    _schedule_broadcast(lambda: realtime_manager.broadcast(str(case_id), event))


def publish_reasoning_stream(
    *,
    case_id: str,
    stage: str,
    label: str,
    detail: str = "",
    confidence: float | None = None,
    metadata: dict | None = None,
) -> None:
    """Broadcast a real-time reasoning token to the Agent Thought Stream.

    ``stage`` is one of: INTENT_PARSING, POLICY_EVALUATION, DIAGNOSTIC_SYNC,
    ACTION_DISPATCH, RESPONSE_GENERATION.
    """
    if not case_id:
        return
    event = {
        "type": "reasoning_stream",
        "case_id": str(case_id),
        "step": {
            "step_id": f"reasoning_{uuid.uuid4().hex[:8]}",
            "stage": stage,
            "type": stage.lower(),
            "label": label,
            "detail": detail,
            "confidence": confidence,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "extra": metadata or {},
        },
    }
    _schedule_broadcast(lambda: realtime_manager.broadcast(str(case_id), event))


def publish_case_state_updated(
    *,
    case_id: str,
    old_status: str | None = None,
    new_status: str | None = None,
    recovery_stage: str | None = None,
    remaining_amount: int | None = None,
    recovered_amount: int | None = None,
    attempt_count: int | None = None,
    promise_status: str | None = None,
    payment_plan_status: str | None = None,
) -> None:
    """Broadcast a case state change so the frontend updates badges,
    progress bar, and pipeline tracker without a page refresh.
    """
    if not case_id:
        return
    event = {
        "type": "case_state_updated",
        "case_id": str(case_id),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            k: v for k, v in {
                "old_status": old_status,
                "new_status": new_status,
                "recovery_stage": recovery_stage,
                "remaining_amount": remaining_amount,
                "recovered_amount": recovered_amount,
                "attempt_count": attempt_count,
                "promise_status": promise_status,
                "payment_plan_status": payment_plan_status,
            }.items() if v is not None
        },
    }
    _schedule_broadcast(lambda: realtime_manager.broadcast(str(case_id), event))


def publish_quick_replies_updated(
    *,
    case_id: str,
    quick_replies: list[dict],
    conversation_id: str | None = None,
) -> None:
    """Broadcast updated quick-reply chips after a conversation turn.

    The frontend replaces the current chip set with these context-aware
    options.
    """
    if not case_id:
        return
    event = {
        "type": "quick_replies_updated",
        "case_id": str(case_id),
        "conversation_id": conversation_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "quick_replies": quick_replies,
        },
    }
    _schedule_broadcast(lambda: realtime_manager.broadcast(str(case_id), event))


# ============================================================
# PAYMENT PLAN UPDATE EVENTS
# ============================================================

def publish_payment_plan_updated(
    *,
    case_id: str,
    plan: dict | None = None,
    installment_breakdown: dict | None = None,
    policy_action: dict | None = None,
    action: str = "created",
) -> None:
    """Broadcast a payment plan update so live dashboards reflect changes instantly.

    ``action`` is one of: "created", "updated", "sub_split", "modified".
    ``plan`` is the enterprise payment_plan payload (installments, amounts, dates).
    ``installment_breakdown`` is the UI-friendly breakdown with formatted amounts.
    ``policy_action`` carries the deterministic next state.

    The frontend uses this event to:
    - Render/update the Payment Plan panel
    - Animate the installment schedule
    - Update the pipeline tracker state
    - Show modification history (sub-splits, count changes)
    """
    if not case_id:
        return
    event = {
        "type": "payment_plan_updated",
        "case_id": str(case_id),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "action": action,
            "plan": plan,
            "installment_breakdown": installment_breakdown,
            "policy_action": policy_action,
        },
    }
    _schedule_broadcast(lambda: realtime_manager.broadcast(str(case_id), event))


def publish_plan_modification(
    *,
    case_id: str,
    old_count: int | None = None,
    new_count: int | None = None,
    modification_type: str = "change_count",
    customer_message: str | None = None,
) -> None:
    """Broadcast a plan modification event for the audit trail and live dashboard.

    Tracks when a customer changes their installment count, creating a
    clear modification history in the conversation thread.
    """
    if not case_id:
        return
    event = {
        "type": "plan_modification",
        "case_id": str(case_id),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "modification_type": modification_type,
            "old_count": old_count,
            "new_count": new_count,
            "customer_message": customer_message[:200] if customer_message else None,
        },
    }
    _schedule_broadcast(lambda: realtime_manager.broadcast(str(case_id), event))
