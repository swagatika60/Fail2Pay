"""Tests for the Email Service.

Covers:
- All 6 email types (failed_payment, payment_retry, invoice, payment_plan, promise_to_pay, payment_success)
- Email template rendering
- Opt-out / communication preference checks
- Email sending with mocked provider
- Delivery status tracking
- Duplicate email prevention
- Edge cases: no email, case not found, customer not found
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.audit_event import AuditEvent
from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.email import SentEmail, EmailDeliveryStatus, EmailType
from app.schemas.email import SentEmailCreate
from app.services.email import (
    EMAIL_TEMPLATES,
    render_email,
    format_amount,
    is_opted_out,
    send_recovery_email,
    get_email_history,
)
from app.crud.email import (
    create_sent_email,
    get_sent_email,
    get_emails_by_case,
    count_emails_by_case_and_type,
)

# --- SQLite in-memory DB ---

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    """Create all tables before each test, drop after."""
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# --- Helpers ---


def create_test_customer(db, email="rahul@example.com", name="Rahul Sharma") -> Customer:
    customer = Customer(
        external_id=f"cust_{uuid.uuid4().hex[:8]}",
        email=email,
        phone="+911234567890",
        name=name,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def create_test_revenue_event(db, customer: Customer) -> RevenueEvent:
    event = RevenueEvent(
        customer_id=customer.id,
        event_type="payment_failed",
        amount=50000,
        currency="INR",
        source="razorpay",
        status="failed",
        external_event_id=f"pay_{uuid.uuid4().hex[:8]}",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_test_recovery_case(
    db,
    customer: Customer,
    revenue_event: RevenueEvent,
    status: RecoveryStatus = RecoveryStatus.RECOVERY_IN_PROGRESS,
    original_amount: int = 50000,
) -> RecoveryCase:
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=revenue_event.id,
        risk_level="high",
        risk_reason="Payment failed",
        status=status,
        original_amount=original_amount,
        recovered_amount=0,
        remaining_amount=original_amount,
        attempt_count=1,
        max_attempts=5,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ============================================================
# FORMAT AMOUNT
# ============================================================


class TestFormatAmount:
    def test_small_amount(self):
        assert format_amount(10000) == "₹100"

    def test_medium_amount(self):
        assert format_amount(50000) == "₹500"

    def test_large_amount(self):
        assert format_amount(149900) == "₹1,499"

    def test_very_large_amount(self):
        assert format_amount(1000000) == "₹10,000"

    def test_lakhs(self):
        assert format_amount(10000000) == "₹1,00,000"


# ============================================================
# EMAIL TEMPLATES
# ============================================================


class TestEmailTemplates:
    def test_all_6_types_exist(self):
        """All 6 email types have templates."""
        expected = [
            EmailType.FAILED_PAYMENT.value,
            EmailType.PAYMENT_RETRY.value,
            EmailType.INVOICE.value,
            EmailType.PAYMENT_PLAN_CONFIRMATION.value,
            EmailType.PROMISE_TO_PAY_REMINDER.value,
            EmailType.PAYMENT_SUCCESS.value,
        ]
        for email_type in expected:
            assert email_type in EMAIL_TEMPLATES, f"Missing template: {email_type}"

    def test_all_templates_have_subject_and_body(self):
        """Every template has both subject and body."""
        for email_type, template in EMAIL_TEMPLATES.items():
            assert "subject" in template, f"Missing subject in {email_type}"
            assert "body" in template, f"Missing body in {email_type}"
            assert len(template["subject"]) > 0
            assert len(template["body"]) > 0

    def test_templates_are_professional(self):
        """No threatening or aggressive language in templates."""
        import re
        # Use word boundaries to avoid false positives (e.g., "issue" contains "sue")
        aggressive_words = [
            r"\bsue\b", "legal action", "court", "penalty", r"\bfine\b",
            "punish", "consequence", "threaten", "demand",
        ]
        for email_type, template in EMAIL_TEMPLATES.items():
            body_lower = template["body"].lower()
            for word in aggressive_words:
                if word.startswith(r"\b"):
                    assert not re.search(word, body_lower), (
                        f"Aggressive word '{word}' found in {email_type}"
                    )
                else:
                    assert word not in body_lower, (
                        f"Aggressive word '{word}' found in {email_type}"
                    )

    def test_templates_include_payment_link(self):
        """Payment-related templates include payment_link placeholder."""
        payment_types = [
            EmailType.FAILED_PAYMENT.value,
            EmailType.PAYMENT_RETRY.value,
            EmailType.PROMISE_TO_PAY_REMINDER.value,
        ]
        for email_type in payment_types:
            assert "{payment_link}" in EMAIL_TEMPLATES[email_type]["body"]

    def test_templates_include_amount(self):
        """All templates include {amount} placeholder."""
        for email_type, template in EMAIL_TEMPLATES.items():
            assert "{amount}" in template["subject"] or "{amount}" in template["body"]

    def test_templates_include_customer_name(self):
        """All templates include {customer_name} placeholder."""
        for email_type, template in EMAIL_TEMPLATES.items():
            assert "{customer_name}" in template["body"]


# ============================================================
# RENDER EMAIL
# ============================================================


class TestRenderEmail:
    def test_render_failed_payment(self):
        result = render_email(
            email_type=EmailType.FAILED_PAYMENT.value,
            customer_name="Rahul",
            amount_paise=50000,
            payment_link="https://pay.example.com/123",
        )

        # Subject contains amount but not necessarily customer name
        assert "₹500" in result["subject"]
        assert "Rahul" in result["body"]
        assert "₹500" in result["body"]
        assert "https://pay.example.com/123" in result["body"]

    def test_render_invoice(self):
        result = render_email(
            email_type=EmailType.INVOICE.value,
            customer_name="Priya",
            amount_paise=149900,
            invoice_link="https://invoice.example.com/456",
        )

        assert "Priya" in result["body"]
        assert "₹1,499" in result["body"]
        assert "https://invoice.example.com/456" in result["body"]

    def test_render_payment_plan(self):
        result = render_email(
            email_type=EmailType.PAYMENT_PLAN_CONFIRMATION.value,
            customer_name="Amit",
            amount_paise=100000,
            payment_plan_details="3 installments of ₹3,334 each",
        )

        assert "Amit" in result["body"]
        assert "3 installments" in result["body"]

    def test_render_payment_success(self):
        result = render_email(
            email_type=EmailType.PAYMENT_SUCCESS.value,
            customer_name="Neha",
            amount_paise=50000,
        )

        assert "Neha" in result["body"]
        assert "successfully received" in result["body"]

    def test_render_unknown_type_returns_empty(self):
        result = render_email(
            email_type="unknown_type",
            customer_name="Test",
            amount_paise=100,
        )

        assert result["subject"] == ""
        assert result["body"] == ""

    def test_render_default_customer_name(self):
        result = render_email(
            email_type=EmailType.FAILED_PAYMENT.value,
            customer_name=None,
            amount_paise=50000,
        )

        assert "Customer" in result["body"]


# ============================================================
# EMAIL SENDING (MOCKED)
# ============================================================


class TestSendRecoveryEmail:
    def _setup_case(self, db):
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        return case, customer

    @patch("app.services.email._send_via_provider")
    def test_send_failed_payment_email(self, mock_send):
        """Send a failed payment email."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "msg_abc123",
            "provider_response": {"id": "msg_abc123"},
        }

        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        result = send_recovery_email(
            db, case.id, EmailType.FAILED_PAYMENT.value,
            payment_link="https://pay.example.com/123",
        )

        assert result["status"] == "sent"
        assert result["email_id"] is not None
        assert result["recipient"] == "rahul@example.com"

        # Verify email was persisted
        email = get_sent_email(db, uuid.UUID(result["email_id"]))
        assert email is not None
        assert email.recipient_email == "rahul@example.com"
        assert email.email_type == EmailType.FAILED_PAYMENT.value
        assert email.delivery_status == EmailDeliveryStatus.SENT.value
        assert email.provider_message_id == "msg_abc123"
        assert email.sent_at is not None
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_send_payment_retry_email(self, mock_send):
        """Send a payment retry email."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_retry1"}

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = send_recovery_email(
            db, case.id, EmailType.PAYMENT_RETRY.value,
            payment_link="https://pay.example.com/456",
        )

        assert result["status"] == "sent"
        assert result["email_type"] == EmailType.PAYMENT_RETRY.value
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_send_invoice_email(self, mock_send):
        """Send an invoice email."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_inv1"}

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = send_recovery_email(
            db, case.id, EmailType.INVOICE.value,
            invoice_link="https://invoice.example.com/789",
        )

        assert result["status"] == "sent"
        assert result["email_type"] == EmailType.INVOICE.value
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_send_payment_plan_email(self, mock_send):
        """Send a payment plan confirmation email."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_plan1"}

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = send_recovery_email(
            db, case.id, EmailType.PAYMENT_PLAN_CONFIRMATION.value,
            payment_plan_details="3 installments of ₹167",
        )

        assert result["status"] == "sent"
        assert result["email_type"] == EmailType.PAYMENT_PLAN_CONFIRMATION.value
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_send_promise_reminder_email(self, mock_send):
        """Send a promise-to-pay reminder email."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_promise1"}

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = send_recovery_email(
            db, case.id, EmailType.PROMISE_TO_PAY_REMINDER.value,
            payment_link="https://pay.example.com/prom1",
        )

        assert result["status"] == "sent"
        assert result["email_type"] == EmailType.PROMISE_TO_PAY_REMINDER.value
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_send_payment_success_email(self, mock_send):
        """Send a payment success email."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_success1"}

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = send_recovery_email(
            db, case.id, EmailType.PAYMENT_SUCCESS.value,
        )

        assert result["status"] == "sent"
        assert result["email_type"] == EmailType.PAYMENT_SUCCESS.value
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_send_failure_records_error(self, mock_send):
        """Failed send records error in database."""
        mock_send.return_value = {"status": "error", "error": "SMTP connection failed"}

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = send_recovery_email(
            db, case.id, EmailType.FAILED_PAYMENT.value,
        )

        assert result["status"] == "error"

        email = get_sent_email(db, uuid.UUID(result["email_id"]))
        assert email.delivery_status == EmailDeliveryStatus.FAILED.value
        assert "SMTP" in email.error_message
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_send_stores_provider_response(self, mock_send):
        """Provider response is stored in the email record."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "msg_abc",
            "provider_response": {"id": "msg_abc", "status": "queued"},
        }

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result = send_recovery_email(
            db, case.id, EmailType.FAILED_PAYMENT.value,
        )

        email = get_sent_email(db, uuid.UUID(result["email_id"]))
        assert email.provider_response == {"id": "msg_abc", "status": "queued"}
        db.close()


# ============================================================
# OPT-OUT CHECKS
# ============================================================


class TestOptOutChecks:
    def _setup_case(self, db):
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        return case, customer

    def test_not_opted_out_by_default(self):
        """Customer is not opted out by default."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        assert is_opted_out(db, case.id) is False
        db.close()

    def test_opted_out_when_case_stopped(self):
        """Customer is opted out when case is STOPPED."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, status=RecoveryStatus.STOPPED
        )

        assert is_opted_out(db, case.id) is True
        db.close()

    def test_opted_out_when_audit_has_stop(self):
        """Customer is opted out when last audit is a stop request."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        audit = AuditEvent(
            recovery_case_id=case.id,
            entity_type="recovery_case",
            entity_id=case.id,
            action="stop_customer_requested_stop",
        )
        db.add(audit)
        db.commit()

        assert is_opted_out(db, case.id) is True
        db.close()

    def test_opted_out_when_message_has_stop(self):
        """Customer is opted out when recent message contains stop keyword."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        conv = Conversation(
            recovery_case_id=case.id,
            channel="whatsapp",
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

        msg = ConversationMessage(
            conversation_id=conv.id,
            direction="inbound",
            content="Please stop messaging me",
            message_type="text",
        )
        db.add(msg)
        db.commit()

        assert is_opted_out(db, case.id) is True
        db.close()

    def test_not_opted_out_with_normal_message(self):
        """Normal messages don't trigger opt-out."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        conv = Conversation(
            recovery_case_id=case.id,
            channel="whatsapp",
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

        msg = ConversationMessage(
            conversation_id=conv.id,
            direction="inbound",
            content="I will pay tomorrow",
            message_type="text",
        )
        db.add(msg)
        db.commit()

        assert is_opted_out(db, case.id) is False
        db.close()

    def test_opted_out_blocks_email(self):
        """Opted out customer does not receive email."""
        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        # Stop the case
        case.status = RecoveryStatus.STOPPED
        db.commit()

        result = send_recovery_email(
            db, case.id, EmailType.FAILED_PAYMENT.value,
        )

        assert result["status"] == "blocked"
        assert result["reason"] == "customer_opted_out"
        db.close()

    def test_unsubscribe_keyword_blocks_email(self):
        """'unsubscribe' in message blocks email."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        conv = Conversation(recovery_case_id=case.id, channel="whatsapp")
        db.add(conv)
        db.commit()
        db.refresh(conv)

        msg = ConversationMessage(
            conversation_id=conv.id,
            direction="inbound",
            content="Please unsubscribe me",
            message_type="text",
        )
        db.add(msg)
        db.commit()

        result = send_recovery_email(
            db, case.id, EmailType.PAYMENT_RETRY.value,
        )

        assert result["status"] == "blocked"
        db.close()

    def test_opt_out_keyword_unsubscribe(self):
        """'unsubscribe' triggers opt-out."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        conv = Conversation(recovery_case_id=case.id, channel="whatsapp")
        db.add(conv)
        db.commit()
        db.refresh(conv)

        msg = ConversationMessage(
            conversation_id=conv.id,
            direction="inbound",
            content="unsubscribe",
            message_type="text",
        )
        db.add(msg)
        db.commit()

        assert is_opted_out(db, case.id) is True
        db.close()

    def test_opt_out_keyword_remove_me(self):
        """'remove me' triggers opt-out."""
        db = TestSessionLocal()
        case, customer = self._setup_case(db)

        conv = Conversation(recovery_case_id=case.id, channel="whatsapp")
        db.add(conv)
        db.commit()
        db.refresh(conv)

        msg = ConversationMessage(
            conversation_id=conv.id,
            direction="inbound",
            content="remove me from your list",
            message_type="text",
        )
        db.add(msg)
        db.commit()

        assert is_opted_out(db, case.id) is True
        db.close()


# ============================================================
# DUPLICATE EMAIL PREVENTION
# ============================================================


class TestDuplicatePrevention:
    def _setup_case(self, db):
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        return case, customer

    @patch("app.services.email._send_via_provider")
    def test_prevents_duplicate_failed_payment(self, mock_send):
        """Cannot send the same failed_payment email twice."""
        mock_send.return_value = {"status": "sent", "message_id": "msg1"}

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        # First send
        result1 = send_recovery_email(
            db, case.id, EmailType.FAILED_PAYMENT.value,
        )
        assert result1["status"] == "sent"

        # Second send — should be skipped
        result2 = send_recovery_email(
            db, case.id, EmailType.FAILED_PAYMENT.value,
        )
        assert result2["status"] == "skipped"
        assert result2["reason"] == "already_sent"

        # Only one email should exist
        emails = get_emails_by_case(db, case.id)
        assert len(emails) == 1
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_allows_multiple_payment_success(self, mock_send):
        """Payment success emails can be sent multiple times."""
        mock_send.return_value = {"status": "sent", "message_id": "msg1"}

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        result1 = send_recovery_email(
            db, case.id, EmailType.PAYMENT_SUCCESS.value,
        )
        assert result1["status"] == "sent"

        result2 = send_recovery_email(
            db, case.id, EmailType.PAYMENT_SUCCESS.value,
        )
        assert result2["status"] == "sent"

        emails = get_emails_by_case(db, case.id)
        assert len(emails) == 2
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_different_types_can_coexist(self, mock_send):
        """Different email types can be sent for the same case."""
        mock_send.return_value = {"status": "sent", "message_id": "msg1"}

        db = TestSessionLocal()
        case, _ = self._setup_case(db)

        send_recovery_email(db, case.id, EmailType.FAILED_PAYMENT.value)
        send_recovery_email(db, case.id, EmailType.PAYMENT_RETRY.value)
        send_recovery_email(db, case.id, EmailType.INVOICE.value)

        emails = get_emails_by_case(db, case.id)
        assert len(emails) == 3

        types = [e.email_type for e in emails]
        assert EmailType.FAILED_PAYMENT.value in types
        assert EmailType.PAYMENT_RETRY.value in types
        assert EmailType.INVOICE.value in types
        db.close()


# ============================================================
# EDGE CASES
# ============================================================


class TestEdgeCases:
    def test_case_not_found(self):
        """Returns error for nonexistent case."""
        db = TestSessionLocal()

        result = send_recovery_email(
            db, uuid.uuid4(), EmailType.FAILED_PAYMENT.value,
        )

        assert result["status"] == "error"
        assert result["reason"] == "case_not_found"
        db.close()

    def test_customer_not_found(self):
        """Returns error when customer is missing."""
        db = TestSessionLocal()
        # Create a case with a customer_id that doesn't exist
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # Override the customer_id to a non-existent UUID
        case.customer_id = uuid.uuid4()
        db.commit()

        result = send_recovery_email(
            db, case.id, EmailType.FAILED_PAYMENT.value,
        )

        assert result["status"] == "error"
        assert result["reason"] == "customer_not_found"
        db.close()

    def test_no_email_address(self):
        """Returns error when customer has no email."""
        db = TestSessionLocal()
        customer = create_test_customer(db, email=None)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_recovery_email(
            db, case.id, EmailType.FAILED_PAYMENT.value,
        )

        assert result["status"] == "error"
        assert result["reason"] == "no_email_address"
        db.close()

    def test_email_history_empty(self):
        """Email history is empty for new case."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        history = get_email_history(db, case.id)

        assert len(history) == 0
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_email_history_populated(self, mock_send):
        """Email history shows sent emails."""
        mock_send.return_value = {"status": "sent", "message_id": "msg1"}

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        send_recovery_email(db, case.id, EmailType.FAILED_PAYMENT.value)
        send_recovery_email(db, case.id, EmailType.PAYMENT_RETRY.value)

        history = get_email_history(db, case.id)

        assert len(history) == 2
        types = [h["email_type"] for h in history]
        assert EmailType.FAILED_PAYMENT.value in types
        assert EmailType.PAYMENT_RETRY.value in types
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_email_recorded_even_on_failure(self, mock_send):
        """Email is recorded in DB even when sending fails."""
        mock_send.return_value = {"status": "error", "error": "Connection refused"}

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_recovery_email(
            db, case.id, EmailType.FAILED_PAYMENT.value,
        )

        assert result["status"] == "error"
        email = get_sent_email(db, uuid.UUID(result["email_id"]))
        assert email is not None
        assert email.delivery_status == EmailDeliveryStatus.FAILED.value
        assert email.error_message == "Connection refused"
        db.close()

    def test_count_emails_by_type(self):
        """Count emails correctly by type."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # Create some email records manually
        for _ in range(3):
            create_sent_email(
                db,
                data=SentEmailCreate(
                    recovery_case_id=case.id,
                    recipient_email="test@example.com",
                    subject="Test",
                    body="Test body",
                    email_type=EmailType.FAILED_PAYMENT.value,
                    provider_message_id="msg1",
                ),
            )
            # Update status to sent
            emails = get_emails_by_case(db, case.id)
            emails[-1].delivery_status = "sent"
            db.commit()

        count = count_emails_by_case_and_type(
            db, case.id, EmailType.FAILED_PAYMENT.value
        )
        assert count == 3

        count = count_emails_by_case_and_type(
            db, case.id, EmailType.PAYMENT_RETRY.value
        )
        assert count == 0
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_recovered_case_can_receive_success_email(self, mock_send):
        """RECOVERED case can receive payment success email."""
        mock_send.return_value = {"status": "sent", "message_id": "msg1"}

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, status=RecoveryStatus.RECOVERED
        )

        result = send_recovery_email(
            db, case.id, EmailType.PAYMENT_SUCCESS.value,
        )

        assert result["status"] == "sent"
        db.close()


# ============================================================
# PROVIDER ABSTRACTION
# ============================================================


class TestProviderAbstraction:
    @patch("app.services.email.httpx.Client")
    def test_send_via_provider_success(self, mock_client_cls):
        """Provider sends email successfully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "prov_msg_123"}
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        from app.services.email import _send_via_provider

        # Mock settings
        with patch("app.services.email.get_settings") as mock_settings:
            mock_settings.return_value.email_api_key = "test_key"
            result = _send_via_provider(
                to_email="test@example.com",
                subject="Test Subject",
                body="Test Body",
            )

        assert result["status"] == "sent"
        assert result["message_id"] == "prov_msg_123"

    def test_send_via_provider_no_api_key(self):
        """Without API key, email is logged but not sent."""
        from app.services.email import _send_via_provider

        with patch("app.services.email.get_settings") as mock_settings:
            mock_settings.return_value.email_api_key = ""
            result = _send_via_provider(
                to_email="test@example.com",
                subject="Test",
                body="Test",
            )

        assert result["status"] == "sent"
        assert "mock" in result["message_id"]

    @patch("app.services.email.httpx.Client")
    def test_send_via_provider_timeout(self, mock_client_cls):
        """Provider timeout returns error."""
        import httpx
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        from app.services.email import _send_via_provider

        with patch("app.services.email.get_settings") as mock_settings:
            mock_settings.return_value.email_api_key = "test_key"
            result = _send_via_provider(
                to_email="test@example.com",
                subject="Test",
                body="Test",
            )

        assert result["status"] == "error"
        assert "timeout" in result["error"].lower()
