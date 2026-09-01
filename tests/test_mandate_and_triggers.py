"""Tests for the revenue-trigger ingestion layer.

Exercises the service layer directly against an isolated DB session so these
tests are deterministic regardless of how other test modules share the global
FastAPI app / dependency overrides.

Covers:
- subscription.auth.failed (mandate drop) webhook handler
- checkout-abandonment / aging-invoice / mandate-drop trigger ingestion
- Idempotency (duplicate external_event_id is skipped)
- Reasoning-chain ordering: TRIGGER → DIAGNOSIS → POLICY → ACTION
- First audit event for a new case is the "created" lifecycle event
"""

from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.recovery_case import RecoveryCase
from app.models.revenue_event import RevenueEvent
from app.services.agent_steps import AgentStage, get_case_steps
from app.services import trigger_ingest
from app.services.webhook_handler import process_mandate_auth_failed

MANDATE_AUTH_FAILED_PAYLOAD = {
    "id": "evt_mandate_001",
    "event": "subscription.auth.failed",
    "payload": {
        "authorization": {
            "entity": {
                "id": "auth_mandate_001",
                "subscription_id": "sub_001",
                "amount": 25000,
                "contact": "+911234567890",
                "email": "test@example.com",
                "customer_id": "cust_mandate_001",
            }
        },
        "failure": {
            "entity": {
                "id": "auth_mandate_001",
                "amount": 25000,
                "failure_reason": "Mandate declined by customer bank",
                "failure_code": "mandate_declined",
                "customer_id": "cust_mandate_001",
            }
        },
    },
}


def _last_case(db) -> RecoveryCase:
    return db.execute(
        select(RecoveryCase).order_by(RecoveryCase.created_at.desc())
    ).scalars().first()


def _audit_actions(db, case_id):
    return list(
        db.execute(
            select(AuditEvent.action)
            .where(AuditEvent.recovery_case_id == case_id)
            .order_by(AuditEvent.created_at.asc())
        ).scalars().all()
    )


class TestMandateAuthFailedWebhook:
    def test_mandate_drop_creates_case_with_root_cause(self, db_session):
        result = process_mandate_auth_failed(db_session, MANDATE_AUTH_FAILED_PAYLOAD)
        assert result["status"] == "processed"
        assert result["diagnosis"]["root_cause"] == "MANDATE_EXPIRY"
        assert result["diagnosis"]["recommended_intervention"] in (
            "SMART_MANDATE_RETRY",
            "HUMAN_ESCALATION",
        )

        case = _last_case(db_session)
        assert case is not None
        assert case.extra_data.get("trigger") == "mandate_drop"
        assert case.remaining_amount == 25000

        actions = _audit_actions(db_session, case.id)
        assert actions[0] == "created"

        steps = get_case_steps(db_session, case.id)
        stages = [s["stage"] for s in steps]
        assert stages[:4] == [AgentStage.TRIGGER, AgentStage.DIAGNOSIS, AgentStage.POLICY, AgentStage.ACTION]

        events = db_session.execute(
            select(RevenueEvent).where(RevenueEvent.event_type == "mandate_drop")
        ).scalars().all()
        assert len(events) == 1

    def test_mandate_drop_is_idempotent(self, db_session):
        first = process_mandate_auth_failed(db_session, MANDATE_AUTH_FAILED_PAYLOAD)
        assert first["status"] == "processed"
        second = process_mandate_auth_failed(db_session, MANDATE_AUTH_FAILED_PAYLOAD)
        assert second["status"] == "skipped"
        assert second["reason"] == "duplicate_webhook"
        assert db_session.execute(select(func.count(RecoveryCase.id))).scalar() == 1
        assert db_session.execute(select(func.count(RevenueEvent.id))).scalar() == 1


class TestTriggerIngestion:
    def test_checkout_abandoned(self, db_session):
        result = trigger_ingest.ingest_checkout_abandonment(
            db_session,
            {
                "external_event_id": "cart_0001",
                "amount": 45000,
                "customer_id": "cust_shop_1",
                "email": "buyer@example.com",
                "abandonment_count": 2,
            },
        )
        assert result["status"] == "processed"
        assert result["trigger_type"] == "checkout_abandonment"
        assert result["is_recoverable"] is True

        case = _last_case(db_session)
        assert case is not None
        assert case.extra_data.get("trigger") == "checkout_abandonment"
        actions = _audit_actions(db_session, case.id)
        assert actions[0] == "created"

        stages = [s["stage"] for s in get_case_steps(db_session, case.id)]
        assert stages[:4] == [AgentStage.TRIGGER, AgentStage.DIAGNOSIS, AgentStage.POLICY, AgentStage.ACTION]

    def test_aging_invoice(self, db_session):
        result = trigger_ingest.ingest_aging_invoice(
            db_session,
            {
                "external_event_id": "inv_0009",
                "invoice_id": "INV-009",
                "amount": 120000,
                "customer_id": "cust_biz_2",
                "due_date": "2026-08-01T00:00:00+00:00",
                "overdue_days": 29,
            },
        )
        assert result["status"] == "processed"

        case = _last_case(db_session)
        assert case.extra_data.get("trigger") == "aging_invoice"
        assert case.extra_data.get("root_cause") == "USER_HESITATION"

    def test_mandate_drop_trigger(self, db_session):
        result = trigger_ingest.ingest_mandate_drop(
            db_session,
            {
                "external_event_id": "mandate_0771",
                "mandate_id": "mandate_0771",
                "subscription_id": "sub_0771",
                "amount": 30000,
                "customer_id": "cust_sub_3",
                "failure_code": "upi_mandate_failed",
            },
        )
        assert result["status"] == "processed"
        assert result["diagnosis"]["root_cause"] == "MANDATE_EXPIRY"

    def test_duplicate_trigger_skipped(self, db_session):
        payload = {
            "external_event_id": "cart_dup_1",
            "amount": 5000,
            "customer_id": "cust_dup_1",
        }
        first = trigger_ingest.ingest_checkout_abandonment(db_session, payload)
        assert first["status"] == "processed"
        second = trigger_ingest.ingest_checkout_abandonment(db_session, payload)
        assert second["status"] == "skipped"
        assert second["reason"] == "duplicate_trigger"
        assert db_session.execute(select(func.count(RecoveryCase.id))).scalar() == 1

    def test_triggers_routes_registered(self):
        from app.main import app

        paths = {route.path for route in app.routes}
        assert "/api/triggers/checkout-abandoned" in paths
        assert "/api/triggers/aging-invoice" in paths
        assert "/api/triggers/mandate-drop" in paths
        assert "/api/cases/{case_id}/agent-steps" in paths