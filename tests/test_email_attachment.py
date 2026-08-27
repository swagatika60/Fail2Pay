"""Tests for Email with PDF Attachment Support.

Covers:
- Sending email with PDF attachment
- Attachment is base64 encoded in provider request
- Mock provider receives attachment info
- Invoice email includes PDF attachment
- Edge cases: no attachment, empty bytes
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
from app.models.email import EmailType
from app.services.email import send_recovery_email, _send_via_provider
from app.services.invoice_pdf import generate_invoice_pdf

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


def create_test_recovery_case(db, customer, revenue_event) -> RecoveryCase:
    case = RecoveryCase(
        customer_id=customer.id,
        revenue_event_id=revenue_event.id,
        risk_level="high",
        risk_reason="Payment failed",
        status=RecoveryStatus.RECOVERY_IN_PROGRESS,
        original_amount=50000,
        recovered_amount=0,
        remaining_amount=50000,
        attempt_count=1,
        max_attempts=5,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ============================================================
# PROVIDER ATTACHMENT HANDLING
# ============================================================


class TestProviderAttachment:
    @patch("app.services.email.get_settings")
    def test_mock_provider_receives_attachment_info(self, mock_settings):
        """Mock provider response includes attachment info."""
        mock_settings.return_value.email_api_key = ""  # force mock path

        pdf_bytes = generate_invoice_pdf(
            invoice_number="INV-001",
            amount_paise=50000,
            customer_name="Test",
        )

        result = _send_via_provider(
            to_email="test@example.com",
            subject="Test",
            body="Test body",
            attachment_bytes=pdf_bytes,
            attachment_filename="invoice.pdf",
        )

        assert result["status"] == "sent"
        assert result["provider_response"]["attachment"] is not None
        assert result["provider_response"]["attachment"]["filename"] == "invoice.pdf"
        assert result["provider_response"]["attachment"]["size_bytes"] == len(pdf_bytes)

    @patch("app.services.email.get_settings")
    def test_no_attachment_when_none_provided(self, mock_settings):
        """No attachment info when attachment_bytes is None."""
        mock_settings.return_value.email_api_key = ""  # force mock path

        result = _send_via_provider(
            to_email="test@example.com",
            subject="Test",
            body="Test body",
        )

        assert result["status"] == "sent"
        assert result["provider_response"]["attachment"] is None

    @patch("app.services.email.httpx.Client")
    def test_api_provider_sends_base64_attachment(self, mock_client_cls):
        """API provider encodes attachment as base64."""
        import base64

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "msg_123"}
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(post=MagicMock(return_value=mock_response))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.email.get_settings") as mock_settings:
            mock_settings.return_value.email_api_key = "test_key"
            mock_settings.return_value.email_from_address = "noreply@fail2pay.com"

            pdf_bytes = b"%PDF-1.4 fake content"
            result = _send_via_provider(
                to_email="test@example.com",
                subject="Invoice",
                body="Body",
                attachment_bytes=pdf_bytes,
                attachment_filename="invoice.pdf",
            )

        assert result["status"] == "sent"

        # Verify the post call included attachment
        call_args = mock_client_cls.return_value.__enter__.return_value.post
        call_kwargs = call_args.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]

        assert "attachments" in payload
        assert len(payload["attachments"]) == 1
        assert payload["attachments"][0]["filename"] == "invoice.pdf"
        assert payload["attachments"][0]["type"] == "application/pdf"
        # Verify base64 encoding
        decoded = base64.b64decode(payload["attachments"][0]["content"])
        assert decoded == pdf_bytes


# ============================================================
# EMAIL WITH ATTACHMENT
# ============================================================


class TestEmailWithAttachment:
    @patch("app.services.email._send_via_provider")
    def test_send_email_with_pdf_attachment(self, mock_send):
        """Send email with PDF attachment."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "msg_abc",
            "provider_response": {"id": "msg_abc"},
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        pdf_bytes = generate_invoice_pdf(
            invoice_number="INV-001",
            amount_paise=50000,
            customer_name="Rahul",
        )

        result = send_recovery_email(
            db=db,
            case_id=case.id,
            email_type=EmailType.INVOICE.value,
            invoice_link="https://example.com/inv/123",
            attachment_bytes=pdf_bytes,
            attachment_filename="invoice_F2P-001.pdf",
        )

        assert result["status"] == "sent"

        # Verify provider was called with attachment
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["attachment_bytes"] == pdf_bytes
        assert call_kwargs["attachment_filename"] == "invoice_F2P-001.pdf"
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_send_email_without_attachment(self, mock_send):
        """Send email without attachment works normally."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "msg_def",
            "provider_response": {"id": "msg_def"},
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_recovery_email(
            db=db,
            case_id=case.id,
            email_type=EmailType.FAILED_PAYMENT.value,
            payment_link="https://pay.example.com/123",
        )

        assert result["status"] == "sent"

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["attachment_bytes"] is None
        assert call_kwargs["attachment_filename"] is None
        db.close()


# ============================================================
# INVOICE EMAIL WITH PDF
# ============================================================


class TestInvoiceEmailWithPDF:
    @patch("app.services.email._send_via_provider")
    def test_invoice_email_includes_pdf(self, mock_send):
        """Invoice email includes PDF attachment."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "msg_inv",
            "provider_response": {"id": "msg_inv"},
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        from app.services.invoice import send_invoice_via_email
        result = send_invoice_via_email(db, case.id)

        assert result["status"] == "sent"

        # Verify provider was called with PDF attachment
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["attachment_bytes"] is not None
        assert call_kwargs["attachment_bytes"][:5] == b"%PDF-"
        assert call_kwargs["attachment_filename"].startswith("invoice_")
        assert call_kwargs["attachment_filename"].endswith(".pdf")
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_invoice_pdf_is_valid(self, mock_send):
        """Attached PDF is a valid PDF file."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "msg_valid",
            "provider_response": {"id": "msg_valid"},
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        from app.services.invoice import send_invoice_via_email
        result = send_invoice_via_email(db, case.id)

        call_kwargs = mock_send.call_args[1]
        pdf = call_kwargs["attachment_bytes"]

        # Verify it's a valid PDF
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 500
        db.close()


# ============================================================
# EDGE CASES
# ============================================================


class TestAttachmentEdgeCases:
    @patch("app.services.email._send_via_provider")
    def test_empty_attachment_bytes(self, mock_send):
        """Empty attachment bytes are passed through."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "msg_empty",
            "provider_response": {"id": "msg_empty"},
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_recovery_email(
            db=db,
            case_id=case.id,
            email_type=EmailType.INVOICE.value,
            invoice_link="https://example.com/inv",
            attachment_bytes=b"",
            attachment_filename="empty.pdf",
        )

        assert result["status"] == "sent"
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["attachment_bytes"] == b""
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_attachment_with_filename_only(self, mock_send):
        """Attachment with filename but no bytes is ignored."""
        mock_send.return_value = {
            "status": "sent",
            "message_id": "msg_fn",
            "provider_response": {"id": "msg_fn"},
        }

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_recovery_email(
            db=db,
            case_id=case.id,
            email_type=EmailType.INVOICE.value,
            invoice_link="https://example.com/inv",
            attachment_filename="invoice.pdf",
            # No attachment_bytes
        )

        assert result["status"] == "sent"
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["attachment_bytes"] is None
        db.close()

    def test_pdf_generation_with_large_amount(self):
        """PDF with large amount works for attachment."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-LARGE",
            amount_paise=100000000,  # 10 lakhs
            customer_name="Big Customer",
        )

        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1000
