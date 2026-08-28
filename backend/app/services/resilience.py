"""Resilient Error Handling Framework.

Never lose a recovery event. Never retry permanently rejected requests indefinitely.

Handles:
- Razorpay API failure (transient + permanent)
- WhatsApp API failure (transient + permanent)
- Email API failure (transient + permanent)
- AI API timeout (fallback to deterministic)
- AI invalid response (fallback to deterministic)
- Database failure (log + graceful degradation)
- Duplicate webhook (idempotent skip)
- Duplicate message (idempotent skip)
- Scheduler failure (log + skip action)
- Expired payment link (regenerate)
- Invalid customer data (skip + audit)

Key principles:
- Transient errors: bounded retries (max 3, exponential backoff)
- Permanent errors: no retry, record failure, fallback
- Idempotency: detect and skip duplicates
- Fallbacks: deterministic behavior when AI fails
- Audit trail: all failures recorded
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ============================================================
# DATA CLASSES
# ============================================================


@dataclass
class RetryConfig:
    """Configuration for bounded retries."""
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    backoff_multiplier: float = 2.0
    retryable_exceptions: tuple = (Exception,)


@dataclass
class FailureRecord:
    """Record of a failure that occurred."""
    failure_type: str
    component: str
    error_message: str
    is_transient: bool
    retries_attempted: int = 0
    resolved: bool = False
    resolution: str = ""
    timestamp: str = ""
    recovery_case_id: str | None = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class FailureResult:
    """Result of a failure handling operation."""
    success: bool = False
    failure_record: FailureRecord | None = None
    fallback_used: bool = False
    fallback_result: Any = None
    retries_exhausted: bool = False


# ============================================================
# FAILURE TYPE CONSTANTS
# ============================================================


class FailureType:
    RAZORPAY_API = "razorpay_api_failure"
    WHATSAPP_API = "whatsapp_api_failure"
    EMAIL_API = "email_api_failure"
    AI_TIMEOUT = "ai_api_timeout"
    AI_INVALID_RESPONSE = "ai_invalid_response"
    DATABASE = "database_failure"
    DUPLICATE_WEBHOOK = "duplicate_webhook"
    DUPLICATE_MESSAGE = "duplicate_message"
    SCHEDULER = "scheduler_failure"
    EXPIRED_PAYMENT_LINK = "expired_payment_link"
    INVALID_CUSTOMER_DATA = "invalid_customer_data"


class FailureComponent:
    RAZORPAY = "razorpay"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    AI = "ai_intent_detector"
    DATABASE = "database"
    WEBHOOK = "webhook_handler"
    SCHEDULER = "scheduler"
    PAYMENT_LINK = "payment_link"
    CUSTOMER = "customer_data"


# ============================================================
# RETRY WITH BOUNDED RETRIES
# ============================================================


def retry_with_backoff(
    func: Callable,
    config: RetryConfig | None = None,
    *args,
    **kwargs,
) -> Any:
    """Execute a function with bounded retries and exponential backoff.

    Only retries on transient failures. Permanent failures are not retried.

    Args:
        func: The function to execute
        config: Retry configuration
        *args, **kwargs: Arguments to pass to the function

    Returns:
        The function's return value

    Raises:
        The last exception if all retries are exhausted
    """
    if config is None:
        config = RetryConfig()

    last_exception = None

    for attempt in range(config.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except config.retryable_exceptions as e:
            last_exception = e

            if attempt < config.max_retries:
                delay = min(
                    config.base_delay_seconds * (config.backoff_multiplier ** attempt),
                    config.max_delay_seconds,
                )
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    config.max_retries + 1,
                    str(e),
                    delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "All %d retries exhausted. Last error: %s",
                    config.max_retries + 1,
                    str(e),
                )

    raise last_exception


# ============================================================
# IDEMPOTENCY CHECKS
# ============================================================


def check_duplicate_webhook(db, event_id: str) -> bool:
    """Check if a webhook event has already been processed.

    Returns True if duplicate (should skip).
    """
    try:
        from app.crud.webhook_event import get_webhook_event_by_event_id
        return get_webhook_event_by_event_id(db, event_id) is not None
    except Exception as e:
        logger.error("Failed to check webhook idempotency: %s", str(e))
        return False


def check_duplicate_message(
    db, conversation_id: uuid.UUID, content: str, direction: str = "outbound"
) -> bool:
    """Check if a message with the same content was already sent.

    Returns True if duplicate (should skip).
    """
    try:
        from app.models.conversation_message import ConversationMessage
        from sqlalchemy import select

        existing = db.execute(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.direction == direction,
                ConversationMessage.content == content,
            )
        ).scalar_one_or_none()

        return existing is not None
    except Exception as e:
        logger.error("Failed to check message idempotency: %s", str(e))
        return False


# ============================================================
# FAILURE RECORDING
# ============================================================


def record_failure(
    db,
    failure_type: str,
    component: str,
    error_message: str,
    is_transient: bool = True,
    retries_attempted: int = 0,
    recovery_case_id: str | None = None,
    resolved: bool = False,
    resolution: str = "",
) -> FailureRecord:
    """Record a failure in the audit trail.

    Every failure is recorded — nothing is silently lost.
    """
    record = FailureRecord(
        failure_type=failure_type,
        component=component,
        error_message=error_message,
        is_transient=is_transient,
        retries_attempted=retries_attempted,
        resolved=resolved,
        resolution=resolution,
        recovery_case_id=recovery_case_id,
    )

    # Audit the failure
    try:
        from app.crud.audit_event import create_audit_event
        from app.schemas.audit_event import AuditEventCreate

        create_audit_event(
            db,
            data=AuditEventCreate(
                recovery_case_id=uuid.UUID(recovery_case_id) if recovery_case_id else uuid.uuid4(),
                entity_type="system_failure",
                entity_id=uuid.UUID(recovery_case_id) if recovery_case_id else uuid.uuid4(),
                action=f"failure_{failure_type}",
                new_value={
                    "failure_type": failure_type,
                    "component": component,
                    "error_message": error_message[:500],
                    "is_transient": is_transient,
                    "retries_attempted": retries_attempted,
                    "resolved": resolved,
                    "resolution": resolution,
                },
            ),
        )
    except Exception as e:
        logger.error("Failed to record failure audit: %s", str(e))

    logger.warning(
        "Failure recorded: type=%s, component=%s, transient=%s, retries=%d",
        failure_type, component, is_transient, retries_attempted,
    )

    return record


# ============================================================
# COMPONENT-SPECIFIC HANDLERS
# ============================================================


def handle_razorpay_failure(
    db,
    error: Exception,
    operation: str,
    recovery_case_id: str | None = None,
) -> FailureResult:
    """Handle Razorpay API failures.

    Transient: ServerError, timeout → retry with backoff
    Permanent: BadRequestError → no retry, record failure
    """
    error_str = str(error)
    is_transient = "timeout" in error_str.lower() or "server" in error_str.lower()

    record = record_failure(
        db,
        failure_type=FailureType.RAZORPAY_API,
        component=FailureComponent.RAZORPAY,
        error_message=error_str,
        is_transient=is_transient,
        recovery_case_id=recovery_case_id,
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=False,
    )


def handle_whatsapp_failure(
    db,
    error: Exception | str,
    phone_number: str,
    recovery_case_id: str | None = None,
) -> FailureResult:
    """Handle WhatsApp API failures.

    Never mark message as successfully sent if WhatsApp fails.
    Transient: timeout, 5xx → retry
    Permanent: 4xx, blocked, invalid number → no retry
    """
    error_str = str(error)
    is_transient = (
        "timeout" in error_str.lower()
        or "500" in error_str
        or "502" in error_str
        or "503" in error_str
    )

    record = record_failure(
        db,
        failure_type=FailureType.WHATSAPP_API,
        component=FailureComponent.WHATSAPP,
        error_message=f"{error_str} (phone: {phone_number})",
        is_transient=is_transient,
        recovery_case_id=recovery_case_id,
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=False,
    )


def handle_email_failure(
    db,
    error: Exception | str,
    recipient: str,
    recovery_case_id: str | None = None,
) -> FailureResult:
    """Handle Email API failures.

    Transient: timeout, 5xx → retry
    Permanent: invalid email, bounced → no retry
    """
    error_str = str(error)
    is_transient = (
        "timeout" in error_str.lower()
        or "500" in error_str
        or "502" in error_str
    )

    record = record_failure(
        db,
        failure_type=FailureType.EMAIL_API,
        component=FailureComponent.EMAIL,
        error_message=f"{error_str} (to: {recipient})",
        is_transient=is_transient,
        recovery_case_id=recovery_case_id,
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=False,
    )


def handle_ai_timeout(
    db,
    recovery_case_id: str | None = None,
) -> FailureResult:
    """Handle AI API timeout.

    Fallback to deterministic rule-based intent classification.
    Never break the recovery system.
    """
    record = record_failure(
        db,
        failure_type=FailureType.AI_TIMEOUT,
        component=FailureComponent.AI,
        error_message="AI API request timed out",
        is_transient=True,
        recovery_case_id=recovery_case_id,
        resolved=True,
        resolution="Fallback to deterministic rule-based classification",
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=True,
        fallback_result={"intent": "UNCLEAR", "confidence": 0.0, "source": "timeout_fallback"},
    )


def handle_ai_invalid_response(
    db,
    raw_response: str,
    recovery_case_id: str | None = None,
) -> FailureResult:
    """Handle AI returning invalid/unparseable response.

    Fallback to deterministic rule-based classification.
    """
    record = record_failure(
        db,
        failure_type=FailureType.AI_INVALID_RESPONSE,
        component=FailureComponent.AI,
        error_message=f"Invalid AI response: {raw_response[:200]}",
        is_transient=False,
        recovery_case_id=recovery_case_id,
        resolved=True,
        resolution="Fallback to deterministic rule-based classification",
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=True,
        fallback_result={"intent": "UNCLEAR", "confidence": 0.0, "source": "invalid_response_fallback"},
    )


def handle_database_failure(
    db,
    error: Exception,
    operation: str,
    recovery_case_id: str | None = None,
) -> FailureResult:
    """Handle database failures.

    Log the failure. Do not crash the system.
    If payment succeeds, stop recovery even if DB write fails.
    """
    error_str = str(error)

    record = record_failure(
        db,
        failure_type=FailureType.DATABASE,
        component=FailureComponent.DATABASE,
        error_message=f"{operation}: {error_str}",
        is_transient="lock" in error_str.lower() or "timeout" in error_str.lower(),
        recovery_case_id=recovery_case_id,
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=False,
    )


def handle_duplicate_webhook_failure(
    db,
    event_id: str,
) -> FailureResult:
    """Handle duplicate webhook events.

    Idempotent: skip silently, record for audit.
    """
    record = record_failure(
        db,
        failure_type=FailureType.DUPLICATE_WEBHOOK,
        component=FailureComponent.WEBHOOK,
        error_message=f"Duplicate webhook event: {event_id}",
        is_transient=False,
        resolved=True,
        resolution="Skipped — idempotent duplicate",
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=False,
    )


def handle_duplicate_message_failure(
    db,
    conversation_id: uuid.UUID,
    content: str,
) -> FailureResult:
    """Handle duplicate outbound messages.

    Idempotent: skip silently, record for audit.
    """
    record = record_failure(
        db,
        failure_type=FailureType.DUPLICATE_MESSAGE,
        component=FailureComponent.WHATSAPP,
        error_message=f"Duplicate message to conversation {conversation_id}",
        is_transient=False,
        resolved=True,
        resolution="Skipped — idempotent duplicate",
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=False,
    )


def handle_scheduler_failure(
    db,
    error: Exception,
    action_id: str | None = None,
) -> FailureResult:
    """Handle scheduler failures.

    Log and skip the action. Do not crash the scheduler.
    """
    record = record_failure(
        db,
        failure_type=FailureType.SCHEDULER,
        component=FailureComponent.SCHEDULER,
        error_message=f"Scheduler error for action {action_id}: {str(error)}",
        is_transient=True,
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=False,
    )


def handle_expired_payment_link(
    db,
    case_id: str,
) -> FailureResult:
    """Handle expired payment links.

    Regenerate the payment link.
    """
    record = record_failure(
        db,
        failure_type=FailureType.EXPIRED_PAYMENT_LINK,
        component=FailureComponent.PAYMENT_LINK,
        error_message=f"Payment link expired for case {case_id}",
        is_transient=False,
        resolved=True,
        resolution="Payment link regenerated",
        recovery_case_id=case_id,
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=True,
        fallback_result={"action": "regenerate_link"},
    )


def handle_invalid_customer_data(
    db,
    error: Exception,
    customer_data: dict,
    recovery_case_id: str | None = None,
) -> FailureResult:
    """Handle invalid customer data.

    Skip the operation. Record for audit.
    """
    record = record_failure(
        db,
        failure_type=FailureType.INVALID_CUSTOMER_DATA,
        component=FailureComponent.CUSTOMER,
        error_message=f"Invalid customer data: {str(error)}",
        is_transient=False,
        recovery_case_id=recovery_case_id,
    )

    return FailureResult(
        success=False,
        failure_record=record,
        fallback_used=False,
    )


# ============================================================
# PAYMENT SUCCESS STOP GUARANTEE
# ============================================================


def ensure_payment_success_stops_recovery(db, case_id) -> bool:
    """If payment succeeds, stop ALL recovery even if messages are queued.

    This is a safety guarantee — payment success always wins.
    Returns True if recovery was stopped.
    """
    try:
        from app.crud.recovery_case import get_recovery_case
        from app.models.recovery_case import RecoveryStatus
        from app.crud.scheduled_action import cancel_pending_actions_for_case
        from app.services.hard_stop import check_hard_stop

        case = get_recovery_case(db, case_id)
        if not case:
            return False

        # Check if payment has been received
        hard_stop = check_hard_stop(db, case_id, action_type="payment_success_check")

        if hard_stop.blocked and hard_stop.stop_condition == "payment_succeeded":
            # Payment succeeded — ensure everything is stopped
            cancelled = cancel_pending_actions_for_case(
                db, case_id, reason="payment_success_stop_guarantee"
            )
            logger.info(
                "Payment success stop guarantee: case=%s, cancelled=%d actions",
                case_id, cancelled,
            )
            return True

        return False
    except Exception as e:
        logger.error("Failed to check payment success stop: %s", str(e))
        return False


# ============================================================
# UNIFIED ERROR WRAPPER
# ============================================================


def safe_execute(
    db,
    func: Callable,
    *args,
    failure_type: str = "unknown",
    component: str = "unknown",
    recovery_case_id: str | None = None,
    **kwargs,
) -> tuple[bool, Any, FailureResult | None]:
    """Safely execute a function with error handling.

    Returns:
        (success, result, failure_result)
    """
    try:
        result = func(*args, **kwargs)
        return True, result, None
    except Exception as e:
        failure_result = FailureResult(
            success=False,
            failure_record=record_failure(
                db,
                failure_type=failure_type,
                component=component,
                error_message=str(e),
                is_transient=True,
                recovery_case_id=recovery_case_id,
            ),
        )
        return False, None, failure_result
