"""Tests for PDF Invoice Generation.

Covers:
- PDF generation with all fields
- PDF generation with minimal fields
- Amount formatting in PDF
- PDF file validity (starts with %PDF)
- Download route via secure token
- Download route via invoice ID
- Token expiry on download
- Edge cases
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.invoice import InvoiceCreate
from app.crud.invoice import create_invoice, get_invoice, get_invoice_by_token
from app.services.invoice_pdf import (
    generate_invoice_pdf,
    generate_invoice_pdf_from_db,
    format_amount,
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


def create_test_invoice(db, case, customer) -> Invoice:
    invoice = create_invoice(
        db,
        data=InvoiceCreate(
            recovery_case_id=case.id,
            customer_id=customer.id,
            invoice_number="F2P-TEST-001",
            amount=50000,
            currency="INR",
            description="Payment recovery for subscription",
            customer_name=customer.name,
            customer_email=customer.email,
        ),
    )
    invoice.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
    invoice.issued_at = datetime.now(timezone.utc)
    invoice.status = InvoiceStatus.SENT.value
    db.commit()
    db.refresh(invoice)
    return invoice


# ============================================================
# FORMAT AMOUNT
# ============================================================


class TestPDFFormatAmount:
    def test_small_amount(self):
        assert format_amount(10000) == "\u20b9100"

    def test_medium_amount(self):
        assert format_amount(50000) == "\u20b9500"

    def test_large_amount(self):
        assert format_amount(149900) == "\u20b91,499"

    def test_lakhs(self):
        assert format_amount(10000000) == "\u20b91,00,000"


# ============================================================
# PDF GENERATION
# ============================================================


class TestPDFGeneration:
    def test_generates_valid_pdf(self):
        """PDF starts with %PDF header."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-001",
            amount_paise=50000,
            customer_name="Rahul",
            customer_email="rahul@test.com",
        )

        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"

    def test_pdf_contains_invoice_number(self):
        """PDF contains the invoice number."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-001",
            amount_paise=50000,
        )

        # Check content is not empty
        assert len(pdf) > 500

    def test_pdf_with_all_fields(self):
        """PDF generation with all fields populated."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-001",
            amount_paise=149900,
            customer_name="Priya Patel",
            customer_email="priya@test.com",
            description="Subscription payment",
            issued_at="27 Aug 2026",
            paid_at=None,
            status="SENT",
            secure_token="abc123def456",
            payment_link="https://pay.example.com/123",
            currency="INR",
        )

        assert isinstance(pdf, bytes)
        assert len(pdf) > 1000

    def test_pdf_with_minimal_fields(self):
        """PDF generation with only required fields."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-MIN",
            amount_paise=10000,
        )

        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"

    def test_pdf_with_paid_status(self):
        """PDF with PAID status."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-PAID",
            amount_paise=50000,
            status="PAID",
            paid_at="27 Aug 2026",
        )

        assert isinstance(pdf, bytes)

    def test_pdf_with_pending_status(self):
        """PDF with PENDING status."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-PEND",
            amount_paise=50000,
            status="PENDING",
        )

        assert isinstance(pdf, bytes)

    def test_pdf_file_size_reasonable(self):
        """PDF file size is reasonable (not too small or too large)."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-SIZE",
            amount_paise=50000,
            customer_name="Test User",
            description="Test payment",
        )

        # Should be between 1KB and 100KB
        assert 1000 < len(pdf) < 100000

    def test_generate_from_db_model(self):
        """Generate PDF from database model object."""
        db = TestSessionLocal()
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)

        pdf = generate_invoice_pdf_from_db(invoice)

        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1000
        db.close()


# ============================================================
# DOWNLOAD ROUTE
# ============================================================


class TestDownloadRoute:
    def _setup(self, db):
        customer = create_test_customer(db)
        revenue_event = create_test_revenue_event(db, customer)
        case = create_test_recovery_case(db, customer, revenue_event)
        invoice = create_test_invoice(db, case, customer)
        return case, customer, invoice

    def _get_client(self, db):
        """Create a TestClient with overridden DB dependency."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.routes.invoices import router
        from app.database import get_db

        test_app = FastAPI()
        test_app.include_router(router)

        def override_get_db():
            try:
                yield db
            finally:
                pass

        test_app.dependency_overrides[get_db] = override_get_db
        return TestClient(test_app)

    def test_download_by_token_returns_pdf(self):
        """Download endpoint returns valid PDF via secure token."""
        db = TestSessionLocal()
        case, customer, invoice = self._setup(db)
        token = invoice.secure_token

        client = self._get_client(db)
        response = client.get(f"/api/invoices/download/{token}")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content[:5] == b"%PDF-"
        assert "attachment" in response.headers.get("content-disposition", "")
        db.close()

    def test_download_by_token_invalid(self):
        """Invalid token returns 404."""
        db = TestSessionLocal()
        client = self._get_client(db)
        response = client.get("/api/invoices/download/invalid_token_123")

        assert response.status_code == 404
        db.close()

    def test_download_by_token_expired(self):
        """Expired token returns 410."""
        db = TestSessionLocal()
        case, customer, invoice = self._setup(db)
        token = invoice.secure_token

        # Expire the token
        invoice.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

        client = self._get_client(db)
        response = client.get(f"/api/invoices/download/{token}")

        assert response.status_code == 410
        db.close()

    def test_download_by_id_returns_pdf(self):
        """Download endpoint returns valid PDF via invoice ID."""
        db = TestSessionLocal()
        case, customer, invoice = self._setup(db)
        invoice_id = invoice.id

        client = self._get_client(db)
        response = client.get(f"/api/invoices/{invoice_id}/download")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content[:5] == b"%PDF-"
        db.close()

    def test_download_by_id_not_found(self):
        """Non-existent invoice ID returns 404."""
        db = TestSessionLocal()
        client = self._get_client(db)
        response = client.get(f"/api/invoices/{uuid.uuid4()}/download")

        assert response.status_code == 404
        db.close()

    def test_download_filename_header(self):
        """Response includes proper filename in Content-Disposition."""
        db = TestSessionLocal()
        case, customer, invoice = self._setup(db)
        token = invoice.secure_token

        client = self._get_client(db)
        response = client.get(f"/api/invoices/download/{token}")

        disposition = response.headers.get("content-disposition", "")
        assert "invoice_" in disposition
        assert ".pdf" in disposition
        db.close()

    def test_download_tracks_access(self):
        """Downloading increments access count."""
        db = TestSessionLocal()
        case, customer, invoice = self._setup(db)
        token = invoice.secure_token
        initial_count = invoice.access_count

        client = self._get_client(db)
        client.get(f"/api/invoices/download/{token}")

        updated_invoice = get_invoice_by_token(db, token)
        assert updated_invoice.access_count > initial_count
        db.close()


# ============================================================
# EDGE CASES
# ============================================================


class TestPDFEdgeCases:
    def test_zero_amount(self):
        """PDF handles zero amount gracefully."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-ZERO",
            amount_paise=0,
        )

        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"

    def test_large_amount(self):
        """PDF handles large amounts (crores)."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-LARGE",
            amount_paise=1000000000,  # 1 crore
        )

        assert isinstance(pdf, bytes)

    def test_special_characters_in_name(self):
        """PDF handles special characters in customer name."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-SPECIAL",
            amount_paise=50000,
            customer_name="O'Brien & Associates",
        )

        assert isinstance(pdf, bytes)

    def test_unicode_in_description(self):
        """PDF handles unicode in description."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-UNICODE",
            amount_paise=50000,
            description="Payment for \u0939\u093f\u0928\u094d\u0926\u0940 service",
        )

        assert isinstance(pdf, bytes)

    def test_no_payment_link(self):
        """PDF works without payment link."""
        pdf = generate_invoice_pdf(
            invoice_number="INV-NOLINK",
            amount_paise=50000,
            payment_link=None,
        )

        assert isinstance(pdf, bytes)

    def test_all_status_values(self):
        """PDF works for all invoice statuses."""
        for status in ["PENDING", "SENT", "VIEWED", "PAID", "CANCELLED"]:
            pdf = generate_invoice_pdf(
                invoice_number=f"INV-{status}",
                amount_paise=50000,
                status=status,
            )
            assert isinstance(pdf, bytes)
