from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RiskAssessment(BaseModel):
    """Deterministic risk assessment result.

    Every field is computed by rule-based logic — no AI or LLM involved.
    """

    risk_level: str  # "HIGH", "MEDIUM", "LOW"
    risk_reason: str
    is_recoverable: bool
    risk_category: str  # e.g. "PAYMENT_FAILED", "REPEATED_PAYMENT_FAILURE"
    # optional context about how the decision was made
    factors: dict | None = None


class RiskAssessmentResult(BaseModel):
    """Full result including the assessment and audit info."""

    assessment: RiskAssessment
    recovery_case_id: UUID | None = None
    audit_event_id: UUID | None = None
    assessed_at: datetime
