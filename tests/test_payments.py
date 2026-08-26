from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# mock razorpay order response
MOCK_ORDER_RESPONSE = {
    "id": "order_test123",
    "amount": 50000,
    "currency": "INR",
    "receipt": "receipt_001",
    "status": "created",
}

# mock razorpay payment response
MOCK_PAYMENT_RESPONSE = {
    "id": "pay_test456",
    "order_id": "order_test123",
    "amount": 50000,
    "currency": "INR",
    "status": "captured",
    "method": "upi",
    "description": "Test payment",
}


class TestCreateOrder:
    @patch("app.routes.payments.create_order")
    def test_create_order_success(self, mock_create_order):
        mock_create_order.return_value = MOCK_ORDER_RESPONSE

        response = client.post(
            "/api/payments/orders",
            json={
                "amount": 50000,
                "currency": "INR",
                "receipt": "receipt_001",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["order_id"] == "order_test123"
        assert data["amount"] == 50000
        assert data["currency"] == "INR"
        assert data["status"] == "created"
        mock_create_order.assert_called_once_with(
            amount=50000, currency="INR", receipt="receipt_001"
        )

    @patch("app.routes.payments.create_order")
    def test_create_order_invalid_amount(self, mock_create_order):
        mock_create_order.side_effect = ValueError("Invalid amount")

        response = client.post(
            "/api/payments/orders",
            json={
                "amount": -100,
                "currency": "INR",
                "receipt": "receipt_002",
            },
        )

        assert response.status_code == 400

    @patch("app.routes.payments.create_order")
    def test_create_order_server_error(self, mock_create_order):
        mock_create_order.side_effect = RuntimeError("Razorpay server error")

        response = client.post(
            "/api/payments/orders",
            json={
                "amount": 50000,
                "currency": "INR",
                "receipt": "receipt_003",
            },
        )

        assert response.status_code == 502


class TestGetPayment:
    @patch("app.routes.payments.get_payment")
    def test_get_payment_success(self, mock_get_payment):
        mock_get_payment.return_value = MOCK_PAYMENT_RESPONSE

        response = client.get("/api/payments/pay_test456")

        assert response.status_code == 200
        data = response.json()
        assert data["payment_id"] == "pay_test456"
        assert data["order_id"] == "order_test123"
        assert data["amount"] == 50000
        assert data["status"] == "captured"
        assert data["method"] == "upi"

    @patch("app.routes.payments.get_payment")
    def test_get_payment_not_found(self, mock_get_payment):
        mock_get_payment.side_effect = ValueError("Payment not found")

        response = client.get("/api/payments/pay_nonexistent")

        assert response.status_code == 404

    @patch("app.routes.payments.get_payment")
    def test_get_payment_server_error(self, mock_get_payment):
        mock_get_payment.side_effect = RuntimeError("Razorpay server error")

        response = client.get("/api/payments/pay_test456")

        assert response.status_code == 502


class TestVerifyPayment:
    @patch("app.routes.payments.verify_payment_signature")
    def test_verify_payment_success(self, mock_verify):
        mock_verify.return_value = True

        response = client.post(
            "/api/payments/verify",
            json={
                "razorpay_order_id": "order_test123",
                "razorpay_payment_id": "pay_test456",
                "razorpay_signature": "valid_signature_here",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["verified"] is True
        assert "successfully" in data["message"]

    @patch("app.routes.payments.verify_payment_signature")
    def test_verify_payment_invalid_signature(self, mock_verify):
        mock_verify.return_value = False

        response = client.post(
            "/api/payments/verify",
            json={
                "razorpay_order_id": "order_test123",
                "razorpay_payment_id": "pay_test456",
                "razorpay_signature": "invalid_signature",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["verified"] is False
        assert "Invalid" in data["message"]
