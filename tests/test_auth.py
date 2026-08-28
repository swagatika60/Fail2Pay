"""Tests for API key authentication middleware."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import APIKeyMiddleware, _is_public


# --- Unit tests for path matching ---


class TestIsPublic:
    def test_health_is_public(self):
        assert _is_public("/health") is True

    def test_api_health_is_public(self):
        assert _is_public("/api/health") is True

    def test_webhook_razorpay_is_public(self):
        assert _is_public("/api/webhooks/razorpay") is True

    def test_webhook_whatsapp_is_public(self):
        assert _is_public("/api/webhooks/whatsapp") is True

    def test_invoice_access_by_token_is_public(self):
        assert _is_public("/api/invoices/access/abc123_token") is True

    def test_invoice_download_by_token_is_public(self):
        assert _is_public("/api/invoices/download/abc123_token") is True

    def test_analytics_requires_auth(self):
        assert _is_public("/api/analytics/summary") is False

    def test_payments_requires_auth(self):
        assert _is_public("/api/payments/orders") is False

    def test_settings_requires_auth(self):
        assert _is_public("/api/settings/recovery") is False

    def test_simulation_requires_auth(self):
        assert _is_public("/api/simulation/run") is False

    def test_cases_requires_auth(self):
        assert _is_public("/api/cases/some-id/promises") is False

    def test_invoices_management_requires_auth(self):
        assert _is_public("/api/invoices") is False

    def test_unknown_route_requires_auth(self):
        assert _is_public("/api/something-else") is False


# --- Integration tests with FastAPI test client ---


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app for testing the middleware."""
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware, api_key="test-secret-key")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/health")
    def api_health():
        return {"status": "ok"}

    @app.post("/api/webhooks/razorpay")
    def razorpay_webhook():
        return {"received": True}

    @app.get("/api/webhooks/whatsapp")
    def whatsapp_verify():
        return {"verified": True}

    @app.get("/api/analytics/summary")
    def analytics_summary():
        return {"data": "secret"}

    @app.get("/api/invoices/access/{token}")
    def invoice_access(token: str):
        return {"invoice": "public"}

    @app.get("/api/invoices")
    def invoice_list():
        return {"invoices": "private"}

    return app


class TestAuthMiddleware:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.app = _make_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_health_without_key(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_api_health_without_key(self):
        resp = self.client.get("/api/health")
        assert resp.status_code == 200

    def test_razorpay_webhook_without_key(self):
        resp = self.client.post("/api/webhooks/razorpay")
        assert resp.status_code == 200

    def test_whatsapp_webhook_without_key(self):
        resp = self.client.get("/api/webhooks/whatsapp")
        assert resp.status_code == 200

    def test_invoice_access_without_key(self):
        resp = self.client.get("/api/invoices/access/some_token")
        assert resp.status_code == 200

    def test_protected_route_returns_401_without_key(self):
        resp = self.client.get("/api/analytics/summary")
        assert resp.status_code == 401
        assert "Missing API key" in resp.json()["detail"]

    def test_protected_route_returns_403_with_wrong_key(self):
        resp = self.client.get(
            "/api/analytics/summary",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 403
        assert "Invalid API key" in resp.json()["detail"]

    def test_protected_route_works_with_correct_key(self):
        resp = self.client.get(
            "/api/analytics/summary",
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == "secret"

    def test_protected_route_rejects_bearer_prefix_only(self):
        resp = self.client.get(
            "/api/analytics/summary",
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 403

    def test_invoice_list_requires_auth(self):
        resp = self.client.get("/api/invoices")
        assert resp.status_code == 401

    def test_invoice_list_works_with_key(self):
        resp = self.client.get(
            "/api/invoices",
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert resp.status_code == 200


class TestAuthDisabled:
    """When API_KEY is empty, all routes are open."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        app = FastAPI()
        app.add_middleware(APIKeyMiddleware, api_key="")

        @app.get("/api/analytics/summary")
        def analytics_summary():
            return {"data": "open"}

        self.client = TestClient(app, raise_server_exceptions=False)

    def test_protected_route_without_key_when_auth_disabled(self):
        resp = self.client.get("/api/analytics/summary")
        assert resp.status_code == 200
