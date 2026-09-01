"""Recovery Stage Derivation — the customer-visible state machine.

Maps the internal ``RecoveryStatus`` (plus engagement signals like an inbound
customer reply or an active payment plan) onto the canonical pipeline the ops
console tracks:

    FAILED → CONTACTED → ENGAGED → PROMISED → RECOVERED
                           │                  └ ESCALATED
                           └ HARD_DROPPED

Derivation is purely deterministic and null-safe so any case (even a half-built
row) yields a stable stage + a 0..5 index for the pipeline tracker UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

# Canonical happy-path pipeline stages in order.
PIPELINE = ["FAILED", "CONTACTED", "ENGAGED", "PROMISED", "PAYMENT_PLAN", "RECOVERED"]

TERMINAL_HARD_DROP = "HARD_DROPPED"
TERMINAL_ESCALATED = "ESCALATED"

STAGE_LABELS = {
    "FAILED": "Failed",
    "CONTACTED": "Contacted",
    "ENGAGED": "Engaged",
    "PROMISED": "Promised",
    "PAYMENT_PLAN": "Payment Plan",
    "RECOVERED": "Recovered",
    "ESCALATED": "Escalated",
    "HARD_DROPPED": "Hard Dropped",
}

_ORDERED = PIPELINE + [TERMINAL_ESCALATED, TERMINAL_HARD_DROP]


@dataclass
class Stage:
    stage: str
    index: int  # -1 for terminal branches, else 0..4
    progress: float  # 0..1 completion fraction along the happy path
    label: str


def stage_index(stage: str) -> int:
    return PIPELINE.index(stage) if stage in PIPELINE else -1


def _progress_for(stage: str) -> float:
    return {
        "FAILED": 0.05,
        "CONTACTED": 0.3,
        "ENGAGED": 0.5,
        "PROMISED": 0.7,
        "PAYMENT_PLAN": 0.8,
        "RECOVERED": 1.0,
        "ESCALATED": 0.9,
        "HARD_DROPPED": 0.0,
    }.get(stage, 0.05)


def _escalation_flag(case) -> str | None:
    """Return the escalation stage when a case is flagged for human/legal."""
    extra = case.extra_data or {}
    for key in (
        "dispute_escalated",
        "human_escalated",
        "escalated_to_human",
        "legal_notice",
        "dispute",
    ):
        if extra.get(key):
            return TERMINAL_ESCALATED
    return None


def _has_inbound(db, case) -> bool:
    """Did the customer actually reply on this case (indicating engagement)?"""
    try:
        from app.models.conversation import Conversation
        from app.models.conversation_message import ConversationMessage

        conv = (
            db.execute(
                select(Conversation)
                .where(
                    Conversation.recovery_case_id == case.id,
                    Conversation.channel == "whatsapp",
                )
                .order_by(Conversation.created_at.desc())
            ).scalars().first()
        )
        if conv is None:
            return False
        inbox = list(
            db.execute(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == conv.id
                )
            ).scalars().all()
        )
        return any(m.direction == "inbound" for m in inbox)
    except Exception:  # noqa: BLE001 - never block recovery on a read
        return False


def _has_plan(db, case) -> bool:
    """Does the case hold an accepted/active installment plan?"""
    try:
        from app.models.payment_plan import PaymentPlan, PaymentPlanStatus

        plans = list(
            db.execute(
                select(PaymentPlan).where(
                    PaymentPlan.recovery_case_id == case.id,
                    PaymentPlan.status.in_(
                        [
                            PaymentPlanStatus.PROPOSED.value,
                            PaymentPlanStatus.ACCEPTED.value,
                            PaymentPlanStatus.ACTIVE.value,
                        ]
                    ),
                )
            ).scalars().all()
        )
        return len(plans) > 0
    except Exception:  # noqa: BLE001
        return False


def derive_stage(db, case) -> Stage:
    """Derive the canonical pipeline stage for a case.

    ``db`` may be ``None`` when engagement sub-reads are not available (the
    derivation still returns a stable stage from status/amounts alone).
    """
    status = case.status.value if hasattr(case.status, "value") else str(case.status)
    status = (status or "AT_RISK").upper()

    escalation = _escalation_flag(case)
    if escalation:
        return Stage(escalation, -1, _progress_for(escalation), STAGE_LABELS[escalation])

    if status == "RECOVERED":
        return Stage("RECOVERED", 5, 1.0, STAGE_LABELS["RECOVERED"])
    if status in ("LOST", "STOPPED"):
        return Stage(
            TERMINAL_HARD_DROP,
            -1,
            _progress_for(TERMINAL_HARD_DROP),
            STAGE_LABELS[TERMINAL_HARD_DROP],
        )
    if status in ("PROMISED", "SCHEDULED", "PAYMENT_PLAN"):
        # An accepted installment plan always surfaces as the PAYMENT_PLAN
        # stage; otherwise PROMISED/SCHEDULED track the customer commitment.
        if status == "PAYMENT_PLAN" or (db and _has_plan(db, case)):
            return Stage("PAYMENT_PLAN", 4, 0.8, STAGE_LABELS["PAYMENT_PLAN"])
        return Stage("PROMISED", 3, 0.7, STAGE_LABELS["PROMISED"])
    if status == "ENGAGED":
        return Stage("ENGAGED", 2, 0.5, STAGE_LABELS["ENGAGED"])
    if status == "PARTIALLY_RECOVERED":
        return Stage("ENGAGED", 2, 0.5, STAGE_LABELS["ENGAGED"])

    if status in ("RECOVERY_IN_PROGRESS", "AT_RISK"):
        engaged = bool(db and (_has_inbound(db, case) or _has_plan(db, case)))
        if status == "AT_RISK" and case.attempt_count == 0 and not engaged:
            return Stage("FAILED", 0, 0.05, STAGE_LABELS["FAILED"])
        stage = "ENGAGED" if engaged else "CONTACTED"
        return Stage(stage, 2 if stage == "ENGAGED" else 1, _progress_for(stage), STAGE_LABELS[stage])

    return Stage("FAILED", 0, 0.05, STAGE_LABELS["FAILED"])


def _stage_amount(case, stage: str) -> int:
    """Money attributed to a stage, matching revenue_map's verified-only rule.

    RECOVERED reflects the *recovered* (captured) value; every other stage
    reflects the still-unpaid balance.
    """
    if stage == "RECOVERED":
        return case.recovered_amount or 0
    return (
        case.remaining_amount if case.remaining_amount > 0 else case.original_amount or 0
    )


def pipeline_from_cases(db, cases) -> list[dict]:
    """Aggregate per-stage amounts for the unified pipeline tracker widget."""
    buckets: dict[str, int] = {s: 0 for s in _ORDERED}
    counts: dict[str, int] = {s: 0 for s in _ORDERED}

    for case in cases:
        st = derive_stage(db, case)
        buckets[st.stage] = buckets.get(st.stage, 0) + _stage_amount(case, st.stage)
        counts[st.stage] = counts.get(st.stage, 0) + 1

    return [
        {
            "stage": s,
            "label": STAGE_LABELS[s],
            "index": stage_index(s),
            "amount": buckets[s],
            "count": counts[s],
        }
        for s in _ORDERED
    ]