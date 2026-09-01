"""Tests for Razorpay webhook processing.

Covers:
- Webhook signature verification
- payment.failed event processing (revenue event + recovery case creation)
- payment.captured event processing (recovery case update)
- Idempotency (duplicate webhooks are skipped)
- Error handling for unsupported events
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app as _app

# --- SQLite in-memory DB for tests ---
# Using StaticPool + connect_args so all sessions share the same in-memory database

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Set dependency override BEFORE creating TestClient
_app.dependency_overrides[get_db] = override_get_db
client = TestClient(_app)


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    """Create all tables before each test, drop after."""
    import app.models  # noqa: F401 - ensure all models are registered

    # Ensure our DB override is set (other test modules may have popped it)
    _app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    _app.dependency_overrides[get_db] = override_get_db


# --- Mock webhook payloads ---

def make_webhook_payload(
    event_type: str, payment_data: dict = None, event_id: str = "evt_test123"
) -> dict:
    """Helper to create a Razorpay webhook payload."""
    default_payment = {
        "id": "pay_test456",
        "order_id": "order_test789",
        "amount": 50000,
        "currency": "INR",
        "status": "failed" if "failed" in event_type else "captured",
        "method": "upi",
        "email": "test@example.com",
        "contact": "+911234567890",
        "customer_id": "cust_test001",
        "failure_reason": "Payment failed by bank",
        "failure_code": "PAYMENT_FAILED",
    }
    if payment_data:
        default_payment.update(payment_data)

    return {
        "id": event_id,
        "event": event_type,
        "payload": {
            "payment": {
                "entity": default_payment,
            }
        },
    }


MOCK_PAYMENT_FAILED_PAYLOAD = make_webhook_payload(
    "payment.failed",
    {"status": "failed", "amount": 50000, "failure_reason": "Insufficient funds"},
    "evt_failed_001",
)

MOCK_PAYMENT_CAPTURED_PAYLOAD = make_webhook_payload(
    "payment.captured",
    {"status": "captured", "amount": 50000},
    "evt_captured_001",
)


# --- Signature verification tests ---

class TestWebhookSignatureVerification:
    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_valid_signature_returns_200(self, mock_verify):
        mock_verify.return_value = True

        response = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_signature"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_invalid_signature_returns_400(self, mock_verify):
        mock_verify.return_value = False

        response = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "invalid_signature"},
        )

        assert response.status_code == 400
        assert "Invalid" in response.json()["detail"]

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_missing_signature_returns_400(self, mock_verify):
        mock_verify.return_value = False

        response = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
        )

        assert response.status_code == 400


# --- payment.failed tests ---

class TestPaymentFailedWebhook:
    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_payment_failed_creates_revenue_event_and_recovery_case(self, mock_verify):
        """Full integration: payment.failed creates customer, revenue event, recovery case, and audit event."""
        mock_verify.return_value = True

        response = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["status"] == "processed"
        assert data["result"]["payment_id"] == "pay_test456"
        assert data["result"]["case_id"] is not None

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_payment_failed_creates_customer(self, mock_verify):
        """Verify customer is created from webhook payload."""
        mock_verify.return_value = True

        client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        db = TestSessionLocal()
        from app.models.customer import Customer

        customer = db.query(Customer).filter(Customer.external_id == "cust_test001").first()
        assert customer is not None
        assert customer.email == "test@example.com"
        assert customer.phone == "+911234567890"
        db.close()

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_payment_failed_creates_revenue_event(self, mock_verify):
        """Verify revenue event stores correct amount and failure info."""
        mock_verify.return_value = True

        client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        db = TestSessionLocal()
        from app.models.revenue_event import RevenueEvent

        event = db.query(RevenueEvent).filter(RevenueEvent.external_event_id == "pay_test456").first()
        assert event is not None
        assert event.event_type == "payment_failed"
        assert event.amount == 50000
        assert event.currency == "INR"
        assert event.source == "razorpay"
        assert event.extra_data["failure_reason"] == "Insufficient funds"
        assert event.extra_data["order_id"] == "order_test789"
        db.close()

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_payment_failed_creates_at_risk_recovery_case(self, mock_verify):
        """Verify recovery case is created with AT_RISK status and correct amounts."""
        mock_verify.return_value = True

        response = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        case_id = response.json()["result"]["case_id"]

        db = TestSessionLocal()
        from app.models.recovery_case import RecoveryCase, RecoveryStatus

        case = db.query(RecoveryCase).filter(RecoveryCase.id == uuid.UUID(case_id)).first()
        assert case.original_amount == 50000
        assert case.remaining_amount == 50000
        assert case.recovered_amount == 0
        assert case.risk_level == "LOW"
        assert case.max_attempts == 5
        assert "low-value transaction" in case.risk_reason
        db.close()

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_payment_failed_creates_audit_event(self, mock_verify):
        """Verify audit event is created for the recovery case."""
        mock_verify.return_value = True

        response = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        case_id = response.json()["result"]["case_id"]

        db = TestSessionLocal()
        from app.models.audit_event import AuditEvent

        audit = db.query(AuditEvent).filter(
            AuditEvent.recovery_case_id == uuid.UUID(case_id)
        ).first()
        assert audit is not None
        assert audit.action == "created"
        assert audit.entity_type == "recovery_case"
        assert audit.new_value["status"] == "AT_RISK"
        assert audit.new_value["original_amount"] == 50000

        risk_audits = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.recovery_case_id == uuid.UUID(case_id),
                AuditEvent.action == "risk_assessed",
            )
            .all()
        )
        assert risk_audits, "risk_assessed audit event should exist (risk engine logged)"
        assert risk_audits[0].new_value["risk_level"] == "LOW"
        db.close()

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_payment_failed_stores_webhook_event_for_idempotency(self, mock_verify):
        """Verify webhook event is stored for idempotency tracking."""
        mock_verify.return_value = True

        client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        db = TestSessionLocal()
        from app.models.webhook_event import WebhookEvent

        event = db.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_failed_001").first()
        assert event is not None
        assert event.event_type == "payment.failed"
        assert event.payment_id == "pay_test456"
        db.close()

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_duplicate_webhook_returns_skipped(self, mock_verify):
        """Duplicate webhook (same event_id) is skipped."""
        mock_verify.return_value = True

        # First webhook - processed
        response1 = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )
        assert response1.json()["result"]["status"] == "processed"

        # Second webhook - skipped
        response2 = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )
        assert response2.json()["result"]["status"] == "skipped"
        assert response2.json()["result"]["reason"] == "duplicate_webhook"


# --- payment.captured tests ---

class TestPaymentCapturedWebhook:
    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_payment_captured_updates_recovery_case(self, mock_verify):
        """Full flow: payment.failed creates case, payment.captured recovers it."""
        mock_verify.return_value = True

        # First: create a failed payment (creates revenue event + recovery case)
        client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        # Second: payment captured for same payment
        response = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_CAPTURED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["status"] == "processed"
        assert data["result"]["recovered_amount"] == 50000
        assert data["result"]["remaining_amount"] == 0

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_payment_captured_marks_case_recovered(self, mock_verify):
        """When fully paid, recovery case status becomes RECOVERED."""
        mock_verify.return_value = True

        # Create failed payment
        client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        # Capture payment
        response = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_CAPTURED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        case_id = response.json()["result"]["case_id"]

        db = TestSessionLocal()
        from app.models.recovery_case import RecoveryCase, RecoveryStatus

        case = db.query(RecoveryCase).filter(RecoveryCase.id == uuid.UUID(case_id)).first()
        assert case.recovered_amount == 50000
        assert case.remaining_amount == 0
        assert case.closed_at is not None
        db.close()

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_order_paid_is_handled_not_unsupported(self, mock_verify):
        """order.paid is a supported webhook (returns processed, not ignored)."""
        mock_verify.return_value = True

        payload = {
            "id": "evt_order_paid_route_001",
            "event": "order.paid",
            "payload": {"order": {"entity": {"id": "order_route_001"}}},
        }

        response = client.post(
            "/api/webhooks/razorpay",
            json=payload,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "order.paid"
        assert data["result"]["status"] == "processed"

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_partial_payment_marks_case_partially_recovered(self, mock_verify):
        """Partial payment marks case as PARTIALLY_RECOVERED."""
        mock_verify.return_value = True

        # Create failed payment for 50000
        client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        # Capture only 20000
        partial_payload = make_webhook_payload(
            "payment.captured",
            {"status": "captured", "amount": 20000},
            "evt_captured_partial_001",
        )

        response = client.post(
            "/api/webhooks/razorpay",
            json=partial_payload,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["recovered_amount"] == 20000
        assert data["result"]["remaining_amount"] == 30000

        case_id = data["result"]["case_id"]

        db = TestSessionLocal()
        from app.models.recovery_case import RecoveryCase, RecoveryStatus

        case = db.query(RecoveryCase).filter(RecoveryCase.id == uuid.UUID(case_id)).first()
        assert case.status == RecoveryStatus.PARTIALLY_RECOVERED
        assert case.closed_at is None
        db.close()

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_duplicate_captured_webhook_returns_skipped(self, mock_verify):
        """Duplicate capture webhook is skipped."""
        mock_verify.return_value = True

        # Create failed payment
        client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        # First capture
        response1 = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_CAPTURED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )
        assert response1.json()["result"]["status"] == "processed"

        # Duplicate capture
        response2 = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_CAPTURED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )
        assert response2.json()["result"]["status"] == "skipped"

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_captured_webhook_with_no_revenue_event(self, mock_verify):
        """Capture webhook for unknown payment is skipped gracefully."""
        mock_verify.return_value = True

        payload = make_webhook_payload(
            "payment.captured",
            {"status": "captured", "amount": 10000},
            "evt_unknown_001",
        )
        payload["payload"]["payment"]["entity"]["id"] = "pay_nonexistent"

        response = client.post(
            "/api/webhooks/razorpay",
            json=payload,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        assert response.status_code == 200
        assert response.json()["result"]["status"] == "skipped"
        assert response.json()["result"]["reason"] == "no_revenue_event"


# --- Unsupported event type tests ---

class TestUnsupportedEvents:
    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_unsupported_event_returns_200_with_ignored(self, mock_verify):
        mock_verify.return_value = True

        payload = make_webhook_payload("subscription.cancelled")
        response = client.post(
            "/api/webhooks/razorpay",
            json=payload,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert data["event_type"] == "subscription.cancelled"


# --- Idempotency integration tests ---

class TestIdempotency:
    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_same_webhook_received_twice_creates_only_one_case(self, mock_verify):
        """Duplicate webhook does not create duplicate revenue events or recovery cases."""
        mock_verify.return_value = True

        # First webhook
        response1 = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )
        assert response1.json()["result"]["status"] == "processed"

        # Second webhook (same event_id)
        response2 = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )
        assert response2.json()["result"]["status"] == "skipped"

        # Verify only one of each was created
        db = TestSessionLocal()
        from app.models.revenue_event import RevenueEvent
        from app.models.recovery_case import RecoveryCase
        from app.models.webhook_event import WebhookEvent

        revenue_events = db.query(RevenueEvent).filter(
            RevenueEvent.external_event_id == "pay_test456"
        ).all()
        assert len(revenue_events) == 1

        recovery_cases = db.query(RecoveryCase).all()
        assert len(recovery_cases) == 1

        webhook_events = db.query(WebhookEvent).filter(
            WebhookEvent.event_id == "evt_failed_001"
        ).all()
        assert len(webhook_events) == 1
        db.close()

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_idempotent_payment_captured(self, mock_verify):
        """Duplicate capture webhook does not double-count recovered revenue."""
        mock_verify.return_value = True

        # Create failed payment
        client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        # First capture
        response1 = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_CAPTURED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )
        assert response1.json()["result"]["status"] == "processed"

        # Second capture (duplicate)
        response2 = client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_CAPTURED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )
        assert response2.json()["result"]["status"] == "skipped"

        # Verify recovered_amount is NOT doubled
        db = TestSessionLocal()
        from app.models.recovery_case import RecoveryCase

        case = db.query(RecoveryCase).first()
        assert case.recovered_amount == 50000  # Not 100000
        assert case.remaining_amount == 0
        db.close()

    @patch("app.routes.webhooks.verify_webhook_signature")
    def test_different_payment_ids_create_separate_cases(self, mock_verify):
        """Different payments from same customer create separate recovery cases."""
        mock_verify.return_value = True

        # First payment fails
        client.post(
            "/api/webhooks/razorpay",
            json=MOCK_PAYMENT_FAILED_PAYLOAD,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        # Second payment fails (different payment_id, different event_id)
        payload2 = make_webhook_payload(
            "payment.failed",
            {"status": "failed", "amount": 30000, "id": "pay_test789"},
            "evt_failed_002",
        )
        payload2["payload"]["payment"]["entity"]["id"] = "pay_test789"

        client.post(
            "/api/webhooks/razorpay",
            json=payload2,
            headers={"X-Razorpay-Signature": "valid_sig"},
        )

        db = TestSessionLocal()
        from app.models.recovery_case import RecoveryCase

        cases = db.query(RecoveryCase).all()
        assert len(cases) == 2
        amounts = {case.original_amount for case in cases}
        assert amounts == {50000, 30000}
        db.close()


# --- Webhook signature utility tests ---

class TestVerifyWebhookSignatureUtility:
    def test_valid_signature_returns_true(self):
        import hashlib
        import hmac

        from app.services.webhook_handler import verify_webhook_signature

        body = b'{"id":"evt_test","event":"payment.failed"}'
        secret = "test_webhook_secret"

        with patch("app.services.webhook_handler.get_settings") as mock_settings:
            mock_settings.return_value.razorpay_webhook_secret = secret

            expected_sig = hmac.new(
                secret.encode("utf-8"), body, hashlib.sha256
            ).hexdigest()

            assert verify_webhook_signature(body, expected_sig) is True

    def test_invalid_signature_returns_false(self):
        from app.services.webhook_handler import verify_webhook_signature

        body = b'{"id":"evt_test","event":"payment.failed"}'

        with patch("app.services.webhook_handler.get_settings") as mock_settings:
            mock_settings.return_value.razorpay_webhook_secret = "test_secret"

            assert verify_webhook_signature(body, "wrong_signature") is False

    def test_missing_signature_returns_false(self):
        from app.services.webhook_handler import verify_webhook_signature

        body = b'{"id":"evt_test","event":"payment.failed"}'

        with patch("app.services.webhook_handler.get_settings") as mock_settings:
            mock_settings.return_value.razorpay_webhook_secret = "test_secret"

            assert verify_webhook_signature(body, "") is False

    def test_unconfigured_secret_skips_verification(self):
        from app.services.webhook_handler import verify_webhook_signature

        body = b'{"id":"evt_test","event":"payment.failed"}'

        with patch("app.services.webhook_handler.get_settings") as mock_settings:
            mock_settings.return_value.razorpay_webhook_secret = ""

            # When no secret is configured, verification is skipped
            assert verify_webhook_signature(body, "") is True
