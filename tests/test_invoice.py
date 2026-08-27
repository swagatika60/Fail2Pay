"""Tests for the Invoice Service.

Covers:
- Invoice creation and generation
- Secure token access and expiry
- Invoice delivery via WhatsApp and email
- Access tracking
- Edge cases: not found, expired token, invalid token
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
from app.models.invoice import Invoice, InvoiceStatus, generate_secure_token
from app.schemas.invoice import InvoiceCreate
from app.services.invoice import (
    generate_invoice_number,
    generate_secure_url,
    create_recovery_invoice,
    access_invoice_by_token,
    send_invoice_via_whatsapp,
    send_invoice_via_email,
    get_invoice_for_frontend,
    get_case_invoices,
    format_amount,
    TOKEN_EXPIRY_HOURS,
)
from app.crud.invoice import (
    create_invoice,
    get_invoice,
    get_invoice_by_token,
    get_invoices_by_case,
    mark_invoice_viewed,
    mark_invoice_paid,
    update_invoice_delivery,
    refresh_secure_token,
    invalidate_token,
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


def create_test_invoice(db, case, customer) -> Invoice:
    invoice = create_invoice(
        db,
        data=InvoiceCreate(
            recovery_case_id=case.id,
            customer_id=customer.id,
            invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
            amount=case.original_amount,
            currency="INR",
            description="Test invoice",
            customer_name=customer.name,
            customer_email=customer.email,
        ),
    )
    invoice.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
    db.commit()
    db.refresh(invoice)
    return invoice


# ============================================================
# FORMAT AMOUNT
# ============================================================


class TestFormatAmount:
    def test_small_amount(self):
        assert format_amount(10000) == "\u20b9100"

    def test_medium_amount(self):
        assert format_amount(50000) == "\u20b9500"

    def test_large_amount(self):
        assert format_amount(149900) == "\u20b91,499"

    def test_lakhs(self):
        assert format_amount(10000000) == "\u20b91,00,000"


# ============================================================
# INVOICE GENERATION
# ============================================================


class TestInvoiceGeneration:
    def test_generate_invoice_number(self):
        """Invoice number follows F2P-{short_id}-{timestamp}-{random} format."""
        number = generate_invoice_number(str(uuid.uuid4()))

        assert number.startswith("F2P-")
        parts = number.split("-")
        assert len(parts) == 4
        assert len(parts[1]) == 8  # short UUID
        assert len(parts[2]) == 14  # YYYYMMDDHHMMSS
        assert len(parts[3]) == 6  # random hex

    def test_generate_secure_token(self):
        """Secure token is cryptographically random."""
        token1 = generate_secure_token()
        token2 = generate_secure_token()

        assert len(token1) >= 32
        assert token1 != token2

    def test_generate_secure_url(self):
        """Secure URL contains the token."""
        token = generate_secure_token()
        url = generate_secure_url(token)

        assert token in url
        assert url.startswith("https://")


# ============================================================
# INVOICE CREATION
# ============================================================


class TestInvoiceCreation:
    def test_create_recovery_invoice(self, ):
        """Create an invoice for a recovery case."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = create_recovery_invoice(db, case.id)

        assert result["status"] == "created"
        assert result["invoice_number"].startswith("F2P-")
        assert result["amount"] == 50000
        assert result["secure_token"] is not None
        assert result["secure_url"] is not None
        assert result["expires_at"] is not None
        db.close()

    def test_invoice_has_secure_token(self):
        """Invoice has a unique secure token."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = create_recovery_invoice(db, case.id)

        invoice = get_invoice(db, uuid.UUID(result["invoice_id"]))
        assert invoice.secure_token is not None
        assert len(invoice.secure_token) >= 32

        # Token should be unique
        result2 = create_recovery_invoice(db, case.id)
        invoice2 = get_invoice(db, uuid.UUID(result2["invoice_id"]))
        assert invoice.secure_token != invoice2.secure_token
        db.close()

    def test_invoice_has_expiry(self):
        """Invoice token has an expiry time."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = create_recovery_invoice(db, case.id)

        invoice = get_invoice(db, uuid.UUID(result["invoice_id"]))
        assert invoice.token_expires_at is not None
        # Should be ~72 hours from now
        now = datetime.now(timezone.utc)
        expires = invoice.token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        hours_until_expiry = (expires - now).total_seconds() / 3600
        assert 71 <= hours_until_expiry <= 73
        db.close()

    def test_invoice_stores_customer_info(self):
        """Invoice snapshots customer name and email."""
        db = TestSessionLocal()
        customer = create_test_customer(db, name="Priya Patel")
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = create_recovery_invoice(db, case.id)

        invoice = get_invoice(db, uuid.UUID(result["invoice_id"]))
        assert invoice.customer_name == "Priya Patel"
        assert invoice.customer_email == "rahul@example.com"  # default email from helper
        db.close()

    def test_invoice_case_not_found(self):
        """Returns error for nonexistent case."""
        db = TestSessionLocal()

        result = create_recovery_invoice(db, uuid.uuid4())

        assert result["status"] == "error"
        assert result["reason"] == "case_not_found"
        db.close()


# ============================================================
# SECURE ACCESS
# ============================================================


class TestSecureAccess:
    def test_access_with_valid_token(self):
        """Valid token returns invoice data."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        result = access_invoice_by_token(db, invoice.secure_token)

        assert result["status"] == "success"
        assert result["invoice"]["invoice_number"] == invoice.invoice_number
        assert result["invoice"]["amount"] == 50000
        assert result["invoice"]["payment_link"] is not None
        db.close()

    def test_access_with_invalid_token(self):
        """Invalid token returns error."""
        db = TestSessionLocal()

        result = access_invoice_by_token(db, "invalid_token_123")

        assert result["status"] == "error"
        assert result["reason"] == "invalid_token"
        db.close()

    def test_access_with_expired_token(self):
        """Expired token returns error."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        # Expire the token
        invoice.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

        result = access_invoice_by_token(db, invoice.secure_token)

        assert result["status"] == "error"
        assert result["reason"] == "token_expired"
        db.close()

    def test_access_increments_count(self):
        """Each access increments the access count."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        assert invoice.access_count == 0

        access_invoice_by_token(db, invoice.secure_token)
        access_invoice_by_token(db, invoice.secure_token)

        db.refresh(invoice)
        assert invoice.access_count == 2
        db.close()

    def test_access_marks_viewed(self):
        """First access marks invoice as VIEWED."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)
        invoice.status = InvoiceStatus.SENT.value
        db.commit()

        access_invoice_by_token(db, invoice.secure_token)

        db.refresh(invoice)
        assert invoice.status == InvoiceStatus.VIEWED.value
        assert invoice.viewed_at is not None
        db.close()


# ============================================================
# INVOICE DELIVERY
# ============================================================


class TestInvoiceDelivery:
    @patch("app.services.whatsapp.send_text_message")
    def test_send_via_whatsapp(self, mock_send):
        """Send invoice link via WhatsApp."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_abc"}

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_invoice_via_whatsapp(db, case.id)

        assert result["status"] == "sent"
        assert result["invoice_id"] is not None
        assert result["invoice_number"] is not None
        assert result["secure_url"] is not None
        assert "/access/" in result["secure_url"]
        db.close()

    def test_send_via_whatsapp_no_phone(self):
        """Fails gracefully when customer has no phone."""
        db = TestSessionLocal()
        customer = create_test_customer(db, email="test@test.com")
        customer.phone = None
        db.commit()
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_invoice_via_whatsapp(db, case.id)

        assert result["status"] == "error"
        assert result["reason"] == "no_phone_number"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_send_via_whatsapp_updates_delivery(self, mock_send):
        """Successful WhatsApp send updates invoice delivery status."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_abc"}

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_invoice_via_whatsapp(db, case.id)

        invoice = get_invoice(db, uuid.UUID(result["invoice_id"]))
        assert invoice.delivered_via == "whatsapp"
        assert invoice.delivered_at is not None
        assert invoice.status == InvoiceStatus.SENT.value
        db.close()

    @patch("app.services.email._send_via_provider")
    def test_send_via_email(self, mock_send):
        """Send invoice via email."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_email"}

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_invoice_via_email(db, case.id)

        assert result["status"] == "sent"
        assert result["invoice_id"] is not None
        assert result["secure_url"] is not None
        db.close()

    def test_send_via_email_no_email(self):
        """Fails gracefully when customer has no email."""
        db = TestSessionLocal()
        customer = create_test_customer(db, email=None)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result = send_invoice_via_email(db, case.id)

        assert result["status"] == "error"
        assert result["reason"] == "no_email_address"
        db.close()

    @patch("app.services.whatsapp.send_text_message")
    def test_send_existing_invoice(self, mock_send):
        """Send an existing invoice by ID."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_abc"}

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        result = send_invoice_via_whatsapp(db, case.id, invoice_id=invoice.id)

        assert result["status"] == "sent"
        assert result["invoice_id"] == str(invoice.id)
        db.close()


# ============================================================
# INVOICE CRUD
# ============================================================


class TestInvoiceCRUD:
    def test_create_and_get(self):
        """Create and retrieve an invoice."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        invoice = create_invoice(
            db,
            data=InvoiceCreate(
                recovery_case_id=case.id,
                customer_id=customer.id,
                invoice_number="INV-001",
                amount=50000,
            ),
        )

        retrieved = get_invoice(db, invoice.id)
        assert retrieved is not None
        assert retrieved.invoice_number == "INV-001"
        assert retrieved.amount == 50000
        db.close()

    def test_get_by_token(self):
        """Retrieve invoice by secure token."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        retrieved = get_invoice_by_token(db, invoice.secure_token)
        assert retrieved is not None
        assert retrieved.id == invoice.id
        db.close()

    def test_get_by_case(self):
        """Get all invoices for a case."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        for i in range(3):
            create_invoice(
                db,
                data=InvoiceCreate(
                    recovery_case_id=case.id,
                    customer_id=customer.id,
                    invoice_number=f"INV-{i:03d}",
                    amount=50000,
                ),
            )

        invoices = get_invoices_by_case(db, case.id)
        assert len(invoices) == 3
        db.close()

    def test_mark_viewed(self):
        """Mark invoice as viewed."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)
        invoice.status = InvoiceStatus.SENT.value
        db.commit()

        mark_invoice_viewed(db, invoice.id)

        db.refresh(invoice)
        assert invoice.status == InvoiceStatus.VIEWED.value
        assert invoice.viewed_at is not None
        assert invoice.access_count == 1
        db.close()

    def test_mark_paid(self):
        """Mark invoice as paid."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        mark_invoice_paid(db, invoice.id)

        db.refresh(invoice)
        assert invoice.status == InvoiceStatus.PAID.value
        assert invoice.paid_at is not None
        db.close()

    def test_refresh_token(self):
        """Refresh generates a new token."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        old_token = invoice.secure_token
        refresh_secure_token(db, invoice.id)

        db.refresh(invoice)
        assert invoice.secure_token != old_token
        assert invoice.token_expires_at is not None
        db.close()

    def test_invalidate_token(self):
        """Invalidate sets expiry to now."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        invalidate_token(db, invoice.id)

        db.refresh(invoice)
        assert invoice.token_expires_at is not None
        # Token should be expired now
        now = datetime.now(timezone.utc)
        expires = invoice.token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert expires <= now
        db.close()


# ============================================================
# FRONTEND DATA
# ============================================================


class TestFrontendData:
    def test_get_invoice_for_frontend(self):
        """Returns formatted invoice data."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        data = get_invoice_for_frontend(db, invoice.id)

        assert data is not None
        assert data["id"] == str(invoice.id)
        assert data["invoice_number"] == invoice.invoice_number
        assert data["amount"] == 50000
        assert data["secure_token"] is not None
        assert "access_count" in data
        db.close()

    def test_get_invoice_for_frontend_not_found(self):
        """Returns None for nonexistent invoice."""
        db = TestSessionLocal()

        data = get_invoice_for_frontend(db, uuid.uuid4())

        assert data is None
        db.close()

    def test_get_case_invoices(self):
        """Returns list of invoices for a case."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        for i in range(2):
            create_invoice(
                db,
                data=InvoiceCreate(
                    recovery_case_id=case.id,
                    customer_id=customer.id,
                    invoice_number=f"INV-{i:03d}",
                    amount=50000,
                ),
            )

        invoices = get_case_invoices(db, case.id)

        assert len(invoices) == 2
        assert all("id" in inv for inv in invoices)
        assert all("invoice_number" in inv for inv in invoices)
        db.close()


# ============================================================
# INTEGRATION WITH INTENT
# ============================================================


class TestIntentIntegration:
    def test_invoice_request_action(self):
        """INVOICE_REQUEST intent maps to send_invoice action."""
        from app.schemas.intent import CustomerIntent
        from app.services.intent_action_mapper import get_action_for_intent

        action = get_action_for_intent(CustomerIntent.INVOICE_REQUEST)

        assert action.action_type == "send_invoice"
        assert action.requires_invoice is True
        assert action.record_attempt_result == "invoice_sent"

    @patch("app.services.whatsapp.send_text_message")
    def test_full_invoice_flow(self, mock_send):
        """Full flow: create invoice → send via WhatsApp → access via token."""
        mock_send.return_value = {"status": "sent", "message_id": "msg_abc"}

        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        # Step 1: Create and send invoice
        result = send_invoice_via_whatsapp(db, case.id)
        assert result["status"] == "sent"

        # Step 2: Access invoice via secure token
        token = result["secure_url"].split("/")[-1]
        access_result = access_invoice_by_token(db, token)

        assert access_result["status"] == "success"
        assert access_result["invoice"]["amount"] == 50000
        assert access_result["invoice"]["customer_name"] == "Rahul Sharma"
        db.close()


# ============================================================
# EDGE CASES
# ============================================================


class TestEdgeCases:
    def test_multiple_invoices_per_case(self):
        """Multiple invoices can exist for one case."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        result1 = create_recovery_invoice(db, case.id)
        result2 = create_recovery_invoice(db, case.id)

        assert result1["invoice_number"] != result2["invoice_number"]
        assert result1["secure_token"] != result2["secure_token"]

        invoices = get_invoices_by_case(db, case.id)
        assert len(invoices) == 2
        db.close()

    def test_invoice_number_uniqueness(self):
        """Invoice numbers are unique."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        numbers = set()
        for _ in range(10):
            result = create_recovery_invoice(db, case.id)
            numbers.add(result["invoice_number"])

        # All 10 should be unique (very high probability with timestamp)
        assert len(numbers) == 10
        db.close()

    def test_recovered_case_can_have_invoice(self):
        """RECOVERED case can still have invoices (for records)."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(
            db, customer, revenue_event, status=RecoveryStatus.RECOVERED
        )

        result = create_recovery_invoice(db, case.id)

        assert result["status"] == "created"
        db.close()

    def test_invoice_with_custom_description(self):
        """Invoice can have a custom description."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)

        invoice = create_invoice(
            db,
            data=InvoiceCreate(
                recovery_case_id=case.id,
                customer_id=customer.id,
                invoice_number="INV-CUSTOM",
                amount=50000,
                description="Custom invoice description",
            ),
        )

        assert invoice.description == "Custom invoice description"
        db.close()
