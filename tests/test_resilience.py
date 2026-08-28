"""Tests for Resilient Error Handling Framework.

Covers:
- All 11 failure types
- Bounded retries with exponential backoff
- Idempotency checks (webhook, message)
- AI timeout fallback to deterministic
- AI invalid response fallback
- Payment success stop guarantee
- Failure recording in audit trail
- Component-specific handlers
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.audit_event import AuditEvent
from app.models.webhook_event import WebhookEvent


# ============ Helpers ============

def _create_customer(db, ext_id="cust_res_1"):
    c = Customer(external_id=ext_id, email=f"{ext_id}@test.com", name="Test User")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _create_case(db, customer, amount=120000, status=RecoveryStatus.RECOVERY_IN_PROGRESS):
    ev = RevenueEvent(
        customer_id=customer.id,
        external_event_id=f"evt_{uuid.uuid4().hex[:8]}",
        event_type="payment_failed", amount=amount, status="failed", source="razorpay",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    case = RecoveryCase(
        customer_id=customer.id, revenue_event_id=ev.id, risk_level="high",
        original_amount=amount, remaining_amount=amount, status=status,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _create_conversation(db, case):
    conv = Conversation(recovery_case_id=case.id, channel="whatsapp")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _create_message(db, conversation, content, direction="outbound"):
    msg = ConversationMessage(
        conversation_id=conversation.id, direction=direction,
        content=content, message_type="text",
    )
    db.add(msg)
    db.commit()
    return msg


# ============ Bounded Retries ============

class TestBoundedRetries:
    def test_succeeds_on_first_attempt(self):
        from app.services.resilience import retry_with_backoff, RetryConfig

        call_count = 0
        def succeeds():
            nonlocal call_count
            call_count += 1
            return "success"

        result = retry_with_backoff(succeeds, RetryConfig(max_retries=3, base_delay_seconds=0.01))
        assert result == "success"
        assert call_count == 1

    def test_retries_on_transient_failure(self):
        from app.services.resilience import retry_with_backoff, RetryConfig

        call_count = 0
        def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient error")
            return "success"

        result = retry_with_backoff(fails_then_succeeds, RetryConfig(max_retries=3, base_delay_seconds=0.01))
        assert result == "success"
        assert call_count == 3

    def test_exhausts_retries(self):
        from app.services.resilience import retry_with_backoff, RetryConfig

        def always_fails():
            raise ConnectionError("always fails")

        with pytest.raises(ConnectionError):
            retry_with_backoff(always_fails, RetryConfig(max_retries=2, base_delay_seconds=0.01))

    def test_does_not_retry_permanent_errors(self):
        from app.services.resilience import retry_with_backoff, RetryConfig

        call_count = 0
        def permanent_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent")

        config = RetryConfig(
            max_retries=3, base_delay_seconds=0.01,
            retryable_exceptions=(ConnectionError,),
        )
        with pytest.raises(ValueError):
            retry_with_backoff(permanent_error, config)
        assert call_count == 1  # Only called once


# ============ Idempotency Checks ============

class TestIdempotencyChecks:
    def test_duplicate_webhook_detected(self, db_session):
        from app.services.resilience import check_duplicate_webhook

        event_id = f"evt_{uuid.uuid4().hex[:8]}"

        # Not duplicate yet
        assert check_duplicate_webhook(db_session, event_id) is False

        # Store it
        webhook = WebhookEvent(event_id=event_id, event_type="payment.failed")
        db_session.add(webhook)
        db_session.commit()

        # Now it's a duplicate
        assert check_duplicate_webhook(db_session, event_id) is True

    def test_duplicate_message_detected(self, db_session):
        from app.services.resilience import check_duplicate_message

        c = _create_customer(db_session, "cust_idem_1")
        case = _create_case(db_session, c)
        conv = _create_conversation(db_session, case)

        # Not duplicate yet
        assert check_duplicate_message(db_session, conv.id, "Hello") is False

        # Send it
        _create_message(db_session, conv, "Hello", "outbound")

        # Now it's a duplicate
        assert check_duplicate_message(db_session, conv.id, "Hello", "outbound") is True

    def test_different_content_not_duplicate(self, db_session):
        from app.services.resilience import check_duplicate_message

        c = _create_customer(db_session, "cust_idem_2")
        case = _create_case(db_session, c)
        conv = _create_conversation(db_session, case)

        _create_message(db_session, conv, "Hello", "outbound")

        # Different content is not a duplicate
        assert check_duplicate_message(db_session, conv.id, "Different message", "outbound") is False


# ============ AI Timeout Fallback ============

class TestAITimeoutFallback:
    def test_ai_timeout_returns_unclear(self, db_session):
        from app.services.resilience import handle_ai_timeout

        result = handle_ai_timeout(db_session)

        assert result.fallback_used is True
        assert result.fallback_result["intent"] == "UNCLEAR"
        assert result.fallback_result["source"] == "timeout_fallback"

    def test_ai_timeout_records_failure(self, db_session):
        from app.services.resilience import handle_ai_timeout
        from app.models.audit_event import AuditEvent
        from sqlalchemy import select

        handle_ai_timeout(db_session, recovery_case_id=None)

        # Check audit event was created
        audit = db_session.execute(
            select(AuditEvent).where(
                AuditEvent.entity_type == "system_failure",
                AuditEvent.action == "failure_ai_api_timeout",
            )
        ).scalar_one_or_none()
        assert audit is not None

    def test_ai_timeout_does_not_crash(self, db_session):
        from app.services.resilience import handle_ai_timeout

        # Should never raise
        result = handle_ai_timeout(db_session)
        assert result is not None


# ============ AI Invalid Response Fallback ============

class TestAIInvalidResponseFallback:
    def test_invalid_response_returns_unclear(self, db_session):
        from app.services.resilience import handle_ai_invalid_response

        result = handle_ai_invalid_response(db_session, "not valid json {{{")

        assert result.fallback_used is True
        assert result.fallback_result["intent"] == "UNCLEAR"
        assert result.fallback_result["source"] == "invalid_response_fallback"

    def test_invalid_response_records_failure(self, db_session):
        from app.services.resilience import handle_ai_invalid_response
        from app.models.audit_event import AuditEvent
        from sqlalchemy import select

        handle_ai_invalid_response(db_session, "random garbage")

        audit = db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "failure_ai_invalid_response",
            )
        ).scalar_one_or_none()
        assert audit is not None

    def test_malicious_json_fallback(self, db_session):
        from app.services.resilience import handle_ai_invalid_response

        malicious = '{"intent": "__import__(\\"os\\").system(\\"rm -rf /\\")}'
        result = handle_ai_invalid_response(db_session, malicious)

        assert result.fallback_used is True
        assert result.fallback_result["intent"] == "UNCLEAR"


# ============ WhatsApp Failure ============

class TestWhatsAppFailure:
    def test_transient_whatsapp_failure(self, db_session):
        from app.services.resilience import handle_whatsapp_failure

        result = handle_whatsapp_failure(
            db_session, Exception("Connection timeout"), "+911234567890"
        )

        assert result.success is False
        assert result.failure_record.is_transient is True

    def test_permanent_whatsapp_failure(self, db_session):
        from app.services.resilience import handle_whatsapp_failure

        result = handle_whatsapp_failure(
            db_session, Exception("403 Forbidden: number blocked"), "+911234567890"
        )

        assert result.success is False
        assert result.failure_record.is_transient is False

    def test_whatsapp_failure_records_audit(self, db_session):
        from app.services.resilience import handle_whatsapp_failure
        from app.models.audit_event import AuditEvent
        from sqlalchemy import select

        handle_whatsapp_failure(db_session, Exception("API error 500"), "+911234567890")

        audit = db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "failure_whatsapp_api_failure",
            )
        ).scalar_one_or_none()
        assert audit is not None


# ============ Email Failure ============

class TestEmailFailure:
    def test_transient_email_failure(self, db_session):
        from app.services.resilience import handle_email_failure

        result = handle_email_failure(
            db_session, Exception("SMTP timeout"), "test@example.com"
        )

        assert result.success is False
        assert result.failure_record.is_transient is True

    def test_permanent_email_failure(self, db_session):
        from app.services.resilience import handle_email_failure

        result = handle_email_failure(
            db_session, Exception("550 User unknown"), "bad@example.com"
        )

        assert result.success is False
        assert result.failure_record.is_transient is False


# ============ Razorpay Failure ============

class TestRazorpayFailure:
    def test_transient_razorpay_failure(self, db_session):
        from app.services.resilience import handle_razorpay_failure

        result = handle_razorpay_failure(
            db_session, Exception("Razorpay server error 500"), "create_order"
        )

        assert result.success is False
        assert result.failure_record.is_transient is True

    def test_permanent_razorpay_failure(self, db_session):
        from app.services.resilience import handle_razorpay_failure

        result = handle_razorpay_failure(
            db_session, Exception("Razorpay bad request: invalid amount"), "create_order"
        )

        assert result.success is False
        assert result.failure_record.is_transient is False


# ============ Duplicate Webhook ============

class TestDuplicateWebhookHandling:
    def test_duplicate_webhook_skipped(self, db_session):
        from app.services.resilience import handle_duplicate_webhook_failure

        result = handle_duplicate_webhook_failure(db_session, "evt_123")

        assert result.success is False
        assert result.failure_record.resolved is True
        assert "duplicate" in result.failure_record.resolution.lower()

    def test_duplicate_webhook_records_audit(self, db_session):
        from app.services.resilience import handle_duplicate_webhook_failure
        from app.models.audit_event import AuditEvent
        from sqlalchemy import select

        handle_duplicate_webhook_failure(db_session, "evt_duplicate_1")

        audit = db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "failure_duplicate_webhook",
            )
        ).scalar_one_or_none()
        assert audit is not None


# ============ Duplicate Message ============

class TestDuplicateMessageHandling:
    def test_duplicate_message_skipped(self, db_session):
        from app.services.resilience import handle_duplicate_message_failure

        result = handle_duplicate_message_failure(db_session, uuid.uuid4(), "Hello")

        assert result.success is False
        assert result.failure_record.resolved is True
        assert "duplicate" in result.failure_record.resolution.lower()


# ============ Scheduler Failure ============

class TestSchedulerFailure:
    def test_scheduler_failure_recorded(self, db_session):
        from app.services.resilience import handle_scheduler_failure

        result = handle_scheduler_failure(
            db_session, Exception("action lookup failed"), str(uuid.uuid4())
        )

        assert result.success is False
        assert result.failure_record.is_transient is True


# ============ Database Failure ============

class TestDatabaseFailure:
    def test_database_lock_failure(self, db_session):
        from app.services.resilience import handle_database_failure

        result = handle_database_failure(
            db_session, Exception("database is locked"), "write_case"
        )

        assert result.success is False
        assert result.failure_record.is_transient is True

    def test_database_constraint_failure(self, db_session):
        from app.services.resilience import handle_database_failure

        result = handle_database_failure(
            db_session, Exception("UNIQUE constraint failed"), "insert_event"
        )

        assert result.success is False
        assert result.failure_record.is_transient is False


# ============ Invalid Customer Data ============

class TestInvalidCustomerData:
    def test_invalid_customer_data_recorded(self, db_session):
        from app.services.resilience import handle_invalid_customer_data

        result = handle_invalid_customer_data(
            db_session, Exception("missing required field"), {"email": ""}
        )

        assert result.success is False
        assert result.failure_record.is_transient is False


# ============ Expired Payment Link ============

class TestExpiredPaymentLink:
    def test_expired_link_triggers_regeneration(self, db_session):
        from app.services.resilience import handle_expired_payment_link

        c = _create_customer(db_session, "cust_exp_1")
        case = _create_case(db_session, c)

        result = handle_expired_payment_link(db_session, str(case.id))

        assert result.fallback_used is True
        assert result.fallback_result["action"] == "regenerate_link"
        assert result.failure_record.resolved is True


# ============ Payment Success Stop Guarantee ============

class TestPaymentSuccessStopGuarantee:
    def test_stops_recovery_when_payment_received(self, db_session):
        from app.services.resilience import ensure_payment_success_stops_recovery

        c = _create_customer(db_session, "cust_stop_1")
        case = _create_case(db_session, c, amount=50000)

        # Simulate payment
        case.recovered_amount = 50000
        case.remaining_amount = 0
        db_session.commit()

        stopped = ensure_payment_success_stops_recovery(db_session, case.id)
        assert stopped is True

    def test_does_not_stop_when_payment_pending(self, db_session):
        from app.services.resilience import ensure_payment_success_stops_recovery

        c = _create_customer(db_session, "cust_stop_2")
        case = _create_case(db_session, c, amount=50000)
        # remaining_amount is still 50000

        stopped = ensure_payment_success_stops_recovery(db_session, case.id)
        assert stopped is False

    def test_handles_nonexistent_case(self, db_session):
        from app.services.resilience import ensure_payment_success_stops_recovery

        stopped = ensure_payment_success_stops_recovery(db_session, uuid.uuid4())
        assert stopped is False


# ============ Failure Recording ============

class TestFailureRecording:
    def test_records_failure_to_audit(self, db_session):
        from app.services.resilience import record_failure

        record = record_failure(
            db_session,
            failure_type="test_failure",
            component="test_component",
            error_message="test error message",
            is_transient=True,
        )

        assert record.failure_type == "test_failure"
        assert record.component == "test_component"
        assert record.is_transient is True
        assert record.timestamp is not None

    def test_records_failure_with_case_id(self, db_session):
        from app.services.resilience import record_failure

        c = _create_customer(db_session, "cust_rec_1")
        case = _create_case(db_session, c)

        record = record_failure(
            db_session,
            failure_type="test_with_case",
            component="test",
            error_message="error",
            is_transient=False,
            recovery_case_id=str(case.id),
        )

        assert record.recovery_case_id == str(case.id)

    def test_records_resolved_failure(self, db_session):
        from app.services.resilience import record_failure

        record = record_failure(
            db_session,
            failure_type="resolved_test",
            component="test",
            error_message="error",
            is_transient=True,
            resolved=True,
            resolution="Fixed by retry",
        )

        assert record.resolved is True
        assert record.resolution == "Fixed by retry"


# ============ Safe Execute ============

class TestSafeExecute:
    def test_successful_execution(self, db_session):
        from app.services.resilience import safe_execute

        def success_func():
            return "result"

        success, result, failure = safe_execute(
            db_session, success_func,
            failure_type="test", component="test",
        )

        assert success is True
        assert result == "result"
        assert failure is None

    def test_failed_execution(self, db_session):
        from app.services.resilience import safe_execute

        def fail_func():
            raise ValueError("boom")

        success, result, failure = safe_execute(
            db_session, fail_func,
            failure_type="test_failure", component="test",
        )

        assert success is False
        assert result is None
        assert failure is not None
        assert failure.failure_record.failure_type == "test_failure"


# ============ Failure Type Constants ============

class TestFailureTypeConstants:
    def test_all_11_failure_types_defined(self):
        from app.services.resilience import FailureType

        types = [
            FailureType.RAZORPAY_API,
            FailureType.WHATSAPP_API,
            FailureType.EMAIL_API,
            FailureType.AI_TIMEOUT,
            FailureType.AI_INVALID_RESPONSE,
            FailureType.DATABASE,
            FailureType.DUPLICATE_WEBHOOK,
            FailureType.DUPLICATE_MESSAGE,
            FailureType.SCHEDULER,
            FailureType.EXPIRED_PAYMENT_LINK,
            FailureType.INVALID_CUSTOMER_DATA,
        ]

        assert len(types) == 11
        assert len(set(types)) == 11  # All unique
