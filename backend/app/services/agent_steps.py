"""Agent reasoning step stream (persisted + live).

Every decision the autonomous engine makes is surfaced as a *reasoning step* —
``[Trigger Received] -> [Root Cause: ...] -> [Policy Check: ...] ->
[Action Dispatched] -> [Ledger Verified]``. Steps are:

1. **Persisted** to the audit trail (``action="agent_step"``) so the full
   chain is immutable and re-playable after a reload.
2. **Broadcast** over the case WebSocket as an ``agent_step`` event so the
   dashboard's Agent Thought Stream animates in real time.

The engine never emits a step that consists of money — only verified captured
payments (see ``webhook_handler._record_verified_payment``) count as revenue.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crud.audit_event import create_audit_event
from app.schemas.audit_event import AuditEventCreate
from app.services.realtime import publish_agent_step

logger = logging.getLogger(__name__)


class AgentStage:
    """Canonical reasoning pipeline stages (order = execution order)."""

    TRIGGER = "TRIGGER"
    DIAGNOSIS = "DIAGNOSIS"
    POLICY = "POLICY"
    ACTION = "ACTION"
    LEDGER = "LEDGER"


def emit_case_step(
    db: Session,
    *,
    case_id,
    stage: str,
    label: str,
    detail: str | None = None,
    confidence: float | None = None,
    latency_ms: int | None = None,
    step_type: str = "reasoning",
    extra: dict | None = None,
    _t0: int | None = None,
) -> dict:
    """Persist + broadcast one agent reasoning step for a case.

    Returns the serialized step dict so callers can inspect/attach it.
    ``_t0`` is an optional monotonic start timestamp used to compute
    ``latency_ms`` automatically when the caller times the span; an explicit
    ``latency_ms`` always wins.
    """
    if _t0 is not None and latency_ms is None:
        latency_ms = max(0, int((time.monotonic() - _t0) * 1000))

    step_id = str(uuid.uuid4())
    occurred_at = datetime.now(timezone.utc).isoformat()

    step = {
        "step_id": step_id,
        "stage": stage,
        "type": step_type,
        "label": label,
        "detail": detail,
        "confidence": confidence,
        "latency_ms": latency_ms,
        "occurred_at": occurred_at,
        "extra": extra or {},
    }

    try:
        create_audit_event(
            db,
            data=AuditEventCreate(
                recovery_case_id=case_id,
                entity_type="agent_step",
                entity_id=case_id,
                action="agent_step",
                new_value={
                    "stage": stage,
                    "step_id": step_id,
                    "label": label,
                    "detail": detail,
                    "confidence": confidence,
                    "latency_ms": latency_ms,
                    "step_type": step_type,
                },
                extra_data={"step": step},
            ),
        )
    except Exception:  # noqa: BLE001 - never let telemetry break recovery
        logger.warning("agent_step: failed to persist audit step %s", label)

    publish_agent_step(case_id=str(case_id), step=step)
    return step


def get_case_steps(db: Session, case_id, limit: int = 60) -> list[dict]:
    """Return the most recent persisted reasoning steps for a case."""
    from sqlalchemy import select

    from app.models.audit_event import AuditEvent

    events = list(
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.recovery_case_id == case_id,
                AuditEvent.action == "agent_step",
            )
            .order_by(AuditEvent.created_at.asc())
        ).scalars().all()
    )

    total = len(events)
    tail = events[-limit:] if limit else events
    steps = []
    for e in tail:
        meta = (e.extra_data or {}).get("step") or (e.new_value or {})
        steps.append(
            {
                "step_id": meta.get("step_id") or str(e.id),
                "stage": meta.get("stage") or "UNKNOWN",
                "type": meta.get("step_type") or "reasoning",
                "label": meta.get("label") or e.action,
                "detail": meta.get("detail"),
                "confidence": meta.get("confidence"),
                "latency_ms": meta.get("latency_ms"),
                "occurred_at": e.created_at.isoformat() if e.created_at else None,
                "extra": meta.get("extra") or {},
            }
        )
    return steps


STAGE_ORDER = [
    AgentStage.TRIGGER,
    AgentStage.DIAGNOSIS,
    AgentStage.POLICY,
    AgentStage.ACTION,
    AgentStage.LEDGER,
]


def summarize_steps(steps: list[dict]) -> dict:
    """Lightweight telemetry over a case's reasoning steps."""
    counts: dict[str, int] = {}
    latencies: list[int] = []
    for s in steps:
        stage = s.get("stage")
        counts[stage] = counts.get(stage, 0) + 1
        if isinstance(s.get("latency_ms"), int):
            latencies.append(s["latency_ms"])
    return {
        "step_count": len(steps),
        "by_stage": {k: counts.get(k, 0) for k in STAGE_ORDER},
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
    }