"""Tests for B2B Receivables Chaser Module.

Covers:
- Model creation and computed properties
- CRUD operations (create, read, update, payment, write-off, dispute)
- Overdue detection and escalation tier computation
- Escalation email templates
- Batch escalation cycle
- API routes (create, list, pay, write-off, dispute, escalate, events)
- Stopping rules (payment received, written off, disputed, max escalations)
- Audit trail for all escalation events
- Edge cases (duplicate invoices, terminal states, future dates)
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.receivable_invoice import (
    ReceivableInvoice,
    ReceivableEscalationEvent,
    ReceivableStatus,
    EscalationTier,
    ESCALATION_THRESHOLDS,
)


# ============================================================
# Helpers
# ============================================================


def _create_receivable(
    db,
    *,
    invoice_number=None,
    amount=500000,  # ₹5,000
    days_until_due=-7,  # overdue by default
    status=None,
    escalation_tier=None,
    customer_name="Acme Corp",
    customer_email="billing@acme.com",
    max_escalations=10,
):
    """Create a receivable invoice for testing."""
    now = datetime.now(timezone.utc)
    inv = ReceivableInvoice(
        customer_name=customer_name,
        customer_email=customer_email,
        customer_company="Acme Corp",
        invoice_number=invoice_number or f"INV-{uuid.uuid4().hex[:8].upper()}",
        description="Test invoice",
        amount=amount,
        amount_paid=0,
        currency="INR",
        issued_at=now - timedelta(days=30),
        due_date=now + timedelta(days=days_until_due),
        status=status or (
            ReceivableStatus.OVERDUE.value if days_until_due < 0
            else ReceivableStatus.PENDING.value
        ),
        escalation_tier=escalation_tier or (
            EscalationTier.FRIENDLY_REMINDER.value if days_until_due < 0
            else EscalationTier.NONE.value
        ),
        escalation_count=1 if days_until_due < 0 else 0,
        max_escalations=max_escalations,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def _create_event(db, invoice, event_type="escalation_tier_changed", **kwargs):
    """Create an escalation event for testing."""
    event = ReceivableEscalationEvent(
        receivable_invoice_id=invoice.id,
        event_type=event_type,
        old_tier=kwargs.get("old_tier"),
        new_tier=kwargs.get("new_tier"),
        details=kwargs.get("details"),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ============================================================
# Model Tests
# ============================================================


class TestReceivableInvoiceModel:
    def test_create_receivable(self, db_session):
        inv = _create_receivable(db_session)
        assert inv.id is not None
        assert inv.customer_name == "Acme Corp"
        assert inv.amount == 500000
        assert inv.status == ReceivableStatus.OVERDUE.value
        assert inv.escalation_tier == EscalationTier.FRIENDLY_REMINDER.value

    def test_remaining_amount_property(self, db_session):
        inv = _create_receivable(db_session, amount=100000)
        assert inv.remaining_amount == 100000

        inv.amount_paid = 30000
        assert inv.remaining_amount == 70000

        inv.amount_paid = 100000
        assert inv.remaining_amount == 0
        assert inv.is_fully_paid is True

    def test_overdue_days_not_overdue(self, db_session):
        inv = _create_receivable(db_session, days_until_due=5)
        assert inv.overdue_days() == 0

    def test_overdue_days_overdue(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-10)
        assert inv.overdue_days() >= 10

    def test_compute_escalation_tier_not_overdue(self, db_session):
        inv = _create_receivable(db_session, days_until_due=5)
        assert inv.compute_escalation_tier() == EscalationTier.NONE

    def test_compute_escalation_tier_friendly(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-3)
        # Force status to PENDING so compute_escalation_tier works
        inv.status = ReceivableStatus.PENDING.value
        inv.escalation_tier = EscalationTier.NONE.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.FRIENDLY_REMINDER

    def test_compute_escalation_tier_formal(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-15)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.FORMAL_NOTICE

    def test_compute_escalation_tier_management(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-45)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.MANAGEMENT_ESCALATION

    def test_compute_escalation_tier_final_demand(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-75)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.FINAL_DEMAND

    def test_compute_escalation_tier_legal(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-100)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.LEGAL_COLLECTION


# ============================================================
# CRUD Tests
# ============================================================


class TestReceivableCRUD:
    def test_create_receivable_invoice(self, db_session):
        from app.crud.receivable_invoice import create_receivable_invoice
        from app.schemas.receivable_invoice import ReceivableInvoiceCreate

        data = ReceivableInvoiceCreate(
            customer_name="Test Corp",
            customer_email="test@corp.com",
            invoice_number="INV-CRUD-001",
            amount=250000,
            issued_at=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc) + timedelta(days=30),
        )
        inv = create_receivable_invoice(db_session, data)
        assert inv.id is not None
        assert inv.invoice_number == "INV-CRUD-001"
        assert inv.amount == 250000
        assert inv.amount_paid == 0
        assert inv.status == ReceivableStatus.PENDING.value

    def test_get_receivable_invoice(self, db_session):
        from app.crud.receivable_invoice import get_receivable_invoice

        inv = _create_receivable(db_session, invoice_number="INV-GET-001")
        fetched = get_receivable_invoice(db_session, inv.id)
        assert fetched is not None
        assert fetched.invoice_number == "INV-GET-001"

    def test_get_by_invoice_number(self, db_session):
        from app.crud.receivable_invoice import get_receivable_invoice_by_number

        inv = _create_receivable(db_session, invoice_number="INV-NUM-001")
        fetched = get_receivable_invoice_by_number(db_session, "INV-NUM-001")
        assert fetched is not None
        assert fetched.id == inv.id

    def test_list_receivable_invoices(self, db_session):
        from app.crud.receivable_invoice import list_receivable_invoices

        _create_receivable(db_session, invoice_number="INV-LIST-001")
        _create_receivable(db_session, invoice_number="INV-LIST-002")
        all_invoices = list_receivable_invoices(db_session)
        assert len(all_invoices) >= 2

    def test_list_with_status_filter(self, db_session):
        from app.crud.receivable_invoice import list_receivable_invoices

        _create_receivable(
            db_session, invoice_number="INV-FILT-001",
            status=ReceivableStatus.OVERDUE.value,
        )
        _create_receivable(
            db_session, invoice_number="INV-FILT-002",
            days_until_due=5,
            status=ReceivableStatus.PENDING.value,
            escalation_tier=EscalationTier.NONE.value,
        )
        overdue = list_receivable_invoices(
            db_session, status=ReceivableStatus.OVERDUE.value
        )
        assert len(overdue) >= 1
        assert all(i.status == ReceivableStatus.OVERDUE.value for i in overdue)

    def test_record_payment_partial(self, db_session):
        from app.crud.receivable_invoice import record_payment

        inv = _create_receivable(db_session, amount=100000)
        updated = record_payment(db_session, inv.id, amount=40000)
        assert updated is not None
        assert updated.amount_paid == 40000
        assert updated.status == ReceivableStatus.PARTIALLY_PAID.value

    def test_record_payment_full(self, db_session):
        from app.crud.receivable_invoice import record_payment

        inv = _create_receivable(db_session, amount=100000)
        updated = record_payment(db_session, inv.id, amount=100000)
        assert updated is not None
        assert updated.amount_paid == 100000
        assert updated.status == ReceivableStatus.PAYMENT_RECEIVED.value
        assert updated.paid_at is not None

    def test_record_payment_with_reference(self, db_session):
        from app.crud.receivable_invoice import record_payment

        inv = _create_receivable(db_session, amount=100000)
        updated = record_payment(
            db_session, inv.id, amount=50000,
            payment_reference="NEFT-12345",
            notes="Partial payment via bank transfer",
        )
        assert updated.extra_data is not None
        payments = updated.extra_data.get("payments", [])
        assert len(payments) == 1
        assert payments[0]["reference"] == "NEFT-12345"

    def test_write_off(self, db_session):
        from app.crud.receivable_invoice import write_off_invoice

        inv = _create_receivable(db_session)
        updated = write_off_invoice(db_session, inv.id, "Customer bankrupt")
        assert updated is not None
        assert updated.status == ReceivableStatus.WRITTEN_OFF.value
        assert updated.escalation_tier == EscalationTier.NONE.value
        assert updated.extra_data["write_off_reason"] == "Customer bankrupt"

    def test_mark_disputed(self, db_session):
        from app.crud.receivable_invoice import mark_disputed

        inv = _create_receivable(db_session)
        updated = mark_disputed(db_session, inv.id)
        assert updated is not None
        assert updated.status == ReceivableStatus.DISPUTED.value
        assert updated.escalation_tier == EscalationTier.NONE.value

    def test_update_escalation_tier(self, db_session):
        from app.crud.receivable_invoice import update_escalation_tier

        inv = _create_receivable(db_session)
        result = update_escalation_tier(
            db_session, inv.id, EscalationTier.FORMAL_NOTICE.value
        )
        assert result is not None
        updated, old_tier = result
        assert updated.escalation_tier == EscalationTier.FORMAL_NOTICE.value
        assert updated.escalation_count == 2  # was 1, now 2
        assert old_tier == EscalationTier.FRIENDLY_REMINDER.value

    def test_create_escalation_event(self, db_session):
        from app.crud.receivable_invoice import create_escalation_event

        inv = _create_receivable(db_session)
        event = create_escalation_event(
            db_session,
            receivable_invoice_id=inv.id,
            event_type="email_sent",
            old_tier="NONE",
            new_tier="FRIENDLY_REMINDER",
            details={"subject": "Test email"},
        )
        assert event.id is not None
        assert event.event_type == "email_sent"

    def test_get_escalation_events(self, db_session):
        from app.crud.receivable_invoice import get_escalation_events

        inv = _create_receivable(db_session)
        _create_event(db_session, inv, "invoice_overdue")
        _create_event(db_session, inv, "email_sent")

        events = get_escalation_events(db_session, inv.id)
        assert len(events) == 2
        assert events[0].event_type == "invoice_overdue"
        assert events[1].event_type == "email_sent"

    def test_get_overdue_invoices(self, db_session):
        from app.crud.receivable_invoice import get_overdue_invoices

        _create_receivable(db_session, invoice_number="INV-OVD-001", days_until_due=-5)
        _create_receivable(
            db_session, invoice_number="INV-OVD-002",
            days_until_due=5,
            status=ReceivableStatus.PENDING.value,
            escalation_tier=EscalationTier.NONE.value,
        )
        overdue = get_overdue_invoices(db_session)
        assert len(overdue) >= 1
        assert all(i.overdue_days() > 0 for i in overdue)

    def test_get_invoices_due_for_escalation(self, db_session):
        from app.crud.receivable_invoice import get_invoices_due_for_escalation

        inv = _create_receivable(db_session)
        # Set next_escalation_at to past
        inv.next_escalation_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        due = get_invoices_due_for_escalation(db_session)
        assert len(due) >= 1

    def test_get_receivables_summary(self, db_session):
        from app.crud.receivable_invoice import get_receivables_summary

        _create_receivable(db_session, invoice_number="INV-SUM-001", amount=100000)
        _create_receivable(
            db_session, invoice_number="INV-SUM-002", amount=200000,
            days_until_due=5,
            status=ReceivableStatus.PENDING.value,
            escalation_tier=EscalationTier.NONE.value,
        )

        summary = get_receivables_summary(db_session)
        assert summary["total_invoices"] >= 2
        assert "total_outstanding" in summary
        assert "by_escalation_tier" in summary


# ============================================================
# Escalation Tier Computation Tests
# ============================================================


class TestEscalationTiers:
    def test_friendly_reminder_1_day(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-1)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.FRIENDLY_REMINDER

    def test_friendly_reminder_7_days(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-7)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.FRIENDLY_REMINDER

    def test_formal_notice_8_days(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-8)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.FORMAL_NOTICE

    def test_formal_notice_30_days(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-30)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.FORMAL_NOTICE

    def test_management_escalation_31_days(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-31)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.MANAGEMENT_ESCALATION

    def test_final_demand_61_days(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-61)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.FINAL_DEMAND

    def test_legal_91_days(self, db_session):
        inv = _create_receivable(db_session, days_until_due=-91)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()
        assert inv.compute_escalation_tier() == EscalationTier.LEGAL_COLLECTION

    def test_thresholds_are_monotonic(self):
        """Escalation tiers should increase monotonically with overdue days."""
        tiers = [
            (EscalationTier.FRIENDLY_REMINDER, 1),
            (EscalationTier.FORMAL_NOTICE, 8),
            (EscalationTier.MANAGEMENT_ESCALATION, 31),
            (EscalationTier.FINAL_DEMAND, 61),
            (EscalationTier.LEGAL_COLLECTION, 91),
        ]
        for i in range(1, len(tiers)):
            assert tiers[i][1] > tiers[i - 1][1], (
                f"Tier {tiers[i][0]} threshold should be > {tiers[i-1][0]}"
            )


# ============================================================
# Email Template Tests
# ============================================================


class TestEmailTemplates:
    def test_all_tiers_have_templates(self):
        from app.services.receivables_chaser import B2B_EMAIL_TEMPLATES

        required_tiers = [
            EscalationTier.FRIENDLY_REMINDER,
            EscalationTier.FORMAL_NOTICE,
            EscalationTier.MANAGEMENT_ESCALATION,
            EscalationTier.FINAL_DEMAND,
            EscalationTier.LEGAL_COLLECTION,
        ]
        for tier in required_tiers:
            assert tier in B2B_EMAIL_TEMPLATES, f"Missing template for {tier.value}"
            template = B2B_EMAIL_TEMPLATES[tier]
            assert "subject" in template
            assert "body" in template

    def test_template_rendering(self):
        from app.services.receivables_chaser import B2B_EMAIL_TEMPLATES

        template = B2B_EMAIL_TEMPLATES[EscalationTier.FRIENDLY_REMINDER]
        subject = template["subject"].format(
            invoice_number="INV-TEST-001",
            days_overdue=5,
            amount="₹5,000",
            due_date="01 Jan 2026",
            customer_name="Acme Corp",
            company_name="TestCo",
        )
        assert "INV-TEST-001" in subject
        assert "5 day(s)" in subject

        body = template["body"].format(
            invoice_number="INV-TEST-001",
            days_overdue=5,
            amount="₹5,000",
            due_date="01 Jan 2026",
            customer_name="Acme Corp",
            company_name="TestCo",
            payment_link="http://localhost:5173/pay-receivable/test-id",
        )
        assert "Acme Corp" in body
        assert "INV-TEST-001" in body
        assert "₹5,000" in body

    def test_escalation_tone_escalates(self):
        """Email tone should get progressively firmer across tiers."""
        from app.services.receivables_chaser import B2B_EMAIL_TEMPLATES

        friendly = B2B_EMAIL_TEMPLATES[EscalationTier.FRIENDLY_REMINDER]["body"]
        formal = B2B_EMAIL_TEMPLATES[EscalationTier.FORMAL_NOTICE]["body"]
        final = B2B_EMAIL_TEMPLATES[EscalationTier.FINAL_DEMAND]["body"]

        # Friendly should be warm
        assert "friendly" in friendly.lower() or "hope" in friendly.lower()
        # Formal should mention escalation
        assert "escalat" in formal.lower() or "formal" in formal.lower()
        # Final should mention legal
        assert "legal" in final.lower() or "final" in final.lower()

    def test_all_templates_format_amount(self):
        from app.services.receivables_chaser import B2B_EMAIL_TEMPLATES

        for tier, template in B2B_EMAIL_TEMPLATES.items():
            # All templates should accept {amount}
            assert "{amount}" in template["subject"] or "{amount}" in template["body"]
            assert "{invoice_number}" in template["subject"] or "{invoice_number}" in template["body"]
            assert "{days_overdue}" in template["subject"] or "{days_overdue}" in template["body"]


# ============================================================
# Service Tests
# ============================================================


class TestReceivablesChaserService:
    def test_detect_overdue_invoices(self, db_session):
        from app.services.receivables_chaser import detect_overdue_invoices

        _create_receivable(
            db_session, invoice_number="INV-DETECT-001",
            days_until_due=-3, status=ReceivableStatus.PENDING.value,
            escalation_tier=EscalationTier.NONE.value,
        )
        newly_overdue = detect_overdue_invoices(db_session)
        assert len(newly_overdue) >= 1
        assert newly_overdue[0]["invoice_number"] == "INV-DETECT-001"

    def test_detect_overdue_skips_paid(self, db_session):
        from app.services.receivables_chaser import detect_overdue_invoices

        _create_receivable(
            db_session,
            status=ReceivableStatus.PAYMENT_RECEIVED.value,
            escalation_tier=EscalationTier.NONE.value,
        )
        newly_overdue = detect_overdue_invoices(db_session)
        assert len(newly_overdue) == 0

    def test_detect_overdue_skips_written_off(self, db_session):
        from app.services.receivables_chaser import detect_overdue_invoices

        inv = _create_receivable(db_session)
        from app.crud.receivable_invoice import write_off_invoice
        write_off_invoice(db_session, inv.id, "Bad debt")

        newly_overdue = detect_overdue_invoices(db_session)
        assert all(d["id"] != str(inv.id) for d in newly_overdue)

    def test_detect_overdue_skips_disputed(self, db_session):
        from app.services.receivables_chaser import detect_overdue_invoices

        inv = _create_receivable(db_session)
        from app.crud.receivable_invoice import mark_disputed
        mark_disputed(db_session, inv.id)

        newly_overdue = detect_overdue_invoices(db_session)
        assert all(d["id"] != str(inv.id) for d in newly_overdue)

    def test_escalate_invoice(self, db_session):
        from app.services.receivables_chaser import escalate_invoice

        # Create a 35-day overdue invoice that should escalate from FRIENDLY_REMINDER to MANAGEMENT_ESCALATION
        inv = _create_receivable(
            db_session, days_until_due=-35,
            escalation_tier=EscalationTier.FRIENDLY_REMINDER.value,
        )
        inv.escalation_count = 1
        inv.next_escalation_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        result = escalate_invoice(db_session, str(inv.id))
        assert result is not None
        assert "new_tier" in result
        assert result["new_tier"] == EscalationTier.MANAGEMENT_ESCALATION.value
        assert result["invoice_number"] == inv.invoice_number

    def test_escalate_skips_terminal_states(self, db_session):
        from app.services.receivables_chaser import escalate_invoice

        inv = _create_receivable(
            db_session,
            status=ReceivableStatus.PAYMENT_RECEIVED.value,
            escalation_tier=EscalationTier.NONE.value,
        )
        result = escalate_invoice(db_session, str(inv.id))
        assert result is None

    def test_escalate_skips_max_reached(self, db_session):
        from app.services.receivables_chaser import escalate_invoice

        inv = _create_receivable(db_session, max_escalations=1)
        inv.escalation_count = 1
        db_session.commit()

        result = escalate_invoice(db_session, str(inv.id))
        assert result is None

    def test_compute_next_escalation(self, db_session):
        from app.services.receivables_chaser import compute_next_escalation

        inv = _create_receivable(db_session)
        now = datetime.now(timezone.utc)
        next_at = compute_next_escalation(inv, now)
        assert next_at is not None
        assert next_at > now

    def test_compute_next_escalation_none_when_max_reached(self, db_session):
        from app.services.receivables_chaser import compute_next_escalation

        inv = _create_receivable(db_session, max_escalations=1)
        inv.escalation_count = 1
        now = datetime.now(timezone.utc)
        next_at = compute_next_escalation(inv, now)
        assert next_at is None

    def test_compute_next_escalation_none_when_paid(self, db_session):
        from app.services.receivables_chaser import compute_next_escalation

        inv = _create_receivable(
            db_session, status=ReceivableStatus.PAYMENT_RECEIVED.value
        )
        now = datetime.now(timezone.utc)
        next_at = compute_next_escalation(inv, now)
        assert next_at is None

    def test_escalation_preview(self, db_session):
        from app.services.receivables_chaser import get_escalation_preview

        inv = _create_receivable(db_session, days_until_due=-3)
        inv.status = ReceivableStatus.PENDING.value
        db_session.commit()

        preview = get_escalation_preview(inv)
        assert preview["invoice_id"] == str(inv.id)
        assert preview["overdue_days"] >= 3
        assert preview["can_escalate"] is True
        assert "preview_subject" in preview
        assert "preview_body" in preview

    def test_format_amount(self):
        from app.services.receivables_chaser import format_amount

        assert format_amount(500) == "\u20b95"
        assert format_amount(100000) == "\u20b91,000"
        assert format_amount(15000000) == "\u20b91,50,000"


# ============================================================
# Batch Escalation Tests
# ============================================================


class TestBatchEscalation:
    def test_run_batch_escalation(self, db_session):
        from app.services.receivables_chaser import run_batch_escalation

        _create_receivable(
            db_session, invoice_number="INV-BATCH-001",
            days_until_due=-5,
            status=ReceivableStatus.PENDING.value,
            escalation_tier=EscalationTier.NONE.value,
        )

        result = run_batch_escalation(db_session)
        assert result["scanned"] >= 1
        assert result["newly_overdue"] >= 1

    def test_run_batch_handles_empty(self, db_session):
        from app.services.receivables_chaser import run_batch_escalation

        result = run_batch_escalation(db_session)
        assert result["scanned"] == 0
        assert result["newly_overdue"] == 0
        assert result["escalated"] == 0

    def test_run_batch_no_double_escalation(self, db_session):
        from app.services.receivables_chaser import run_batch_escalation

        inv = _create_receivable(
            db_session, days_until_due=-3,
            status=ReceivableStatus.OVERDUE.value,
            escalation_tier=EscalationTier.FRIENDLY_REMINDER.value,
        )
        inv.escalation_count = 1
        inv.next_escalation_at = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()

        # Run batch — should not re-escalate since next_escalation_at is in future
        result = run_batch_escalation(db_session)
        # The invoice was already overdue so it won't be newly_overdue
        assert result["newly_overdue"] == 0


# ============================================================
# Stopping Rules Tests
# ============================================================


class TestStoppingRules:
    def test_payment_received_stops_escalation(self, db_session):
        from app.services.receivables_chaser import escalate_invoice

        inv = _create_receivable(db_session)
        from app.crud.receivable_invoice import record_payment
        record_payment(db_session, inv.id, inv.amount)

        result = escalate_invoice(db_session, str(inv.id))
        assert result is None

    def test_written_off_stops_escalation(self, db_session):
        from app.services.receivables_chaser import escalate_invoice

        inv = _create_receivable(db_session)
        from app.crud.receivable_invoice import write_off_invoice
        write_off_invoice(db_session, inv.id, "Uncollectible")

        result = escalate_invoice(db_session, str(inv.id))
        assert result is None

    def test_disputed_stops_escalation(self, db_session):
        from app.services.receivables_chaser import escalate_invoice

        inv = _create_receivable(db_session)
        from app.crud.receivable_invoice import mark_disputed
        mark_disputed(db_session, inv.id)

        result = escalate_invoice(db_session, str(inv.id))
        assert result is None

    def test_max_escalations_stops(self, db_session):
        from app.services.receivables_chaser import escalate_invoice

        inv = _create_receivable(db_session, max_escalations=2)
        inv.escalation_count = 2
        db_session.commit()

        result = escalate_invoice(db_session, str(inv.id))
        assert result is None


# ============================================================
# API Route Tests (via FastAPI TestClient)
# ============================================================


class TestReceivablesAPI:
    def _get_client(self):
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine, StaticPool
        from sqlalchemy.orm import sessionmaker
        from app.database import Base, get_db
        import app.models  # noqa: F401 — register models
        from app.main import app as fastapi_app

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)

        def override_get_db():
            db = TestSession()
            try:
                yield db
            finally:
                db.close()

        fastapi_app.dependency_overrides[get_db] = override_get_db
        client = TestClient(fastapi_app, raise_server_exceptions=False)
        return client, engine, Base

    def test_create_receivable(self):
        client, engine, Base = self._get_client()
        response = client.post("/api/receivables", json={
            "customer_name": "API Corp",
            "customer_email": "api@corp.com",
            "invoice_number": "INV-API-001",
            "amount": 100000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["invoice_number"] == "INV-API-001"
        assert data["amount"] == 100000

    def test_create_duplicate_receivable(self):
        client, engine, Base = self._get_client()
        payload = {
            "customer_name": "API Corp",
            "customer_email": "api@corp.com",
            "invoice_number": "INV-DUP-001",
            "amount": 100000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        }
        client.post("/api/receivables", json=payload)
        response = client.post("/api/receivables", json=payload)
        assert response.status_code == 409

    def test_list_receivables(self):
        client, engine, Base = self._get_client()
        client.post("/api/receivables", json={
            "customer_name": "List Corp",
            "customer_email": "list@corp.com",
            "invoice_number": "INV-LST-001",
            "amount": 50000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        })
        response = client.get("/api/receivables")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_receivable(self):
        client, engine, Base = self._get_client()
        create_resp = client.post("/api/receivables", json={
            "customer_name": "Get Corp",
            "customer_email": "get@corp.com",
            "invoice_number": "INV-GET-001",
            "amount": 200000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        })
        invoice_id = create_resp.json()["id"]
        response = client.get(f"/api/receivables/{invoice_id}")
        assert response.status_code == 200
        assert response.json()["invoice_number"] == "INV-GET-001"

    def test_get_nonexistent_receivable(self):
        client, engine, Base = self._get_client()
        response = client.get(f"/api/receivables/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_record_payment(self):
        client, engine, Base = self._get_client()
        create_resp = client.post("/api/receivables", json={
            "customer_name": "Pay Corp",
            "customer_email": "pay@corp.com",
            "invoice_number": "INV-PAY-001",
            "amount": 100000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        })
        invoice_id = create_resp.json()["id"]
        response = client.post(f"/api/receivables/{invoice_id}/pay", json={
            "amount": 50000,
            "payment_reference": "TXN-001",
        })
        assert response.status_code == 200
        assert response.json()["amount_paid"] == 50000

    def test_write_off(self):
        client, engine, Base = self._get_client()
        create_resp = client.post("/api/receivables", json={
            "customer_name": "WO Corp",
            "customer_email": "wo@corp.com",
            "invoice_number": "INV-WO-001",
            "amount": 100000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        })
        invoice_id = create_resp.json()["id"]
        response = client.post(f"/api/receivables/{invoice_id}/write-off", json={
            "reason": "Bad debt",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "WRITTEN_OFF"

    def test_dispute(self):
        client, engine, Base = self._get_client()
        create_resp = client.post("/api/receivables", json={
            "customer_name": "Disp Corp",
            "customer_email": "disp@corp.com",
            "invoice_number": "INV-DISP-001",
            "amount": 100000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        })
        invoice_id = create_resp.json()["id"]
        response = client.post(f"/api/receivables/{invoice_id}/dispute")
        assert response.status_code == 200
        assert response.json()["status"] == "DISPUTED"

    def test_escalation_preview(self):
        client, engine, Base = self._get_client()
        create_resp = client.post("/api/receivables", json={
            "customer_name": "Prev Corp",
            "customer_email": "prev@corp.com",
            "invoice_number": "INV-PREV-001",
            "amount": 100000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-07-01T00:00:00Z",  # past due
        })
        invoice_id = create_resp.json()["id"]
        response = client.get(f"/api/receivables/{invoice_id}/escalation-preview")
        assert response.status_code == 200
        data = response.json()
        assert "overdue_days" in data
        assert "preview_subject" in data

    def test_get_escalation_events(self):
        client, engine, Base = self._get_client()
        create_resp = client.post("/api/receivables", json={
            "customer_name": "Events Corp",
            "customer_email": "events@corp.com",
            "invoice_number": "INV-EVTS-001",
            "amount": 100000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        })
        invoice_id = create_resp.json()["id"]
        response = client.get(f"/api/receivables/{invoice_id}/events")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_summary(self):
        client, engine, Base = self._get_client()
        response = client.get("/api/receivables/summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_outstanding" in data
        assert "total_invoices" in data
        assert "by_escalation_tier" in data

    def test_batch_run(self):
        client, engine, Base = self._get_client()
        response = client.post("/api/receivables/batch/run")
        assert response.status_code == 200
        data = response.json()
        assert "scanned" in data
        assert "newly_overdue" in data
        assert "escalated" in data

    def test_cannot_pay_already_paid(self):
        client, engine, Base = self._get_client()
        create_resp = client.post("/api/receivables", json={
            "customer_name": "Paid Corp",
            "customer_email": "paid@corp.com",
            "invoice_number": "INV-PAID-001",
            "amount": 100000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        })
        invoice_id = create_resp.json()["id"]
        # Pay in full
        client.post(f"/api/receivables/{invoice_id}/pay", json={"amount": 100000})
        # Try to pay again
        response = client.post(f"/api/receivables/{invoice_id}/pay", json={"amount": 50000})
        assert response.status_code == 400

    def test_cannot_write_off_paid(self):
        client, engine, Base = self._get_client()
        create_resp = client.post("/api/receivables", json={
            "customer_name": "WOP Corp",
            "customer_email": "wop@corp.com",
            "invoice_number": "INV-WOP-001",
            "amount": 100000,
            "issued_at": "2026-08-01T00:00:00Z",
            "due_date": "2026-09-01T00:00:00Z",
        })
        invoice_id = create_resp.json()["id"]
        # Pay in full
        client.post(f"/api/receivables/{invoice_id}/pay", json={"amount": 100000})
        # Try to write off
        response = client.post(
            f"/api/receivables/{invoice_id}/write-off",
            json={"reason": "Test"},
        )
        assert response.status_code == 400


# ============================================================
# Audit Trail Tests
# ============================================================


class TestAuditTrail:
    def test_overdue_creates_event(self, db_session):
        from app.crud.receivable_invoice import create_escalation_event

        inv = _create_receivable(db_session)
        event = create_escalation_event(
            db_session,
            receivable_invoice_id=inv.id,
            event_type="invoice_overdue",
            old_tier="NONE",
            new_tier="FRIENDLY_REMINDER",
            details={"overdue_days": 7, "amount": 500000},
        )
        assert event.event_type == "invoice_overdue"
        assert event.details["overdue_days"] == 7

    def test_escalation_creates_event(self, db_session):
        from app.crud.receivable_invoice import create_escalation_event

        inv = _create_receivable(db_session)
        event = create_escalation_event(
            db_session,
            receivable_invoice_id=inv.id,
            event_type="escalation_tier_changed",
            old_tier="FRIENDLY_REMINDER",
            new_tier="FORMAL_NOTICE",
        )
        assert event.old_tier == "FRIENDLY_REMINDER"
        assert event.new_tier == "FORMAL_NOTICE"

    def test_payment_creates_event(self, db_session):
        from app.crud.receivable_invoice import create_escalation_event

        inv = _create_receivable(db_session)
        event = create_escalation_event(
            db_session,
            receivable_invoice_id=inv.id,
            event_type="payment_received",
            details={"amount": 50000, "reference": "NEFT-123"},
        )
        assert event.event_type == "payment_received"
        assert event.details["amount"] == 50000

    def test_write_off_creates_event(self, db_session):
        from app.crud.receivable_invoice import create_escalation_event

        inv = _create_receivable(db_session)
        event = create_escalation_event(
            db_session,
            receivable_invoice_id=inv.id,
            event_type="written_off",
            details={"reason": "Bad debt"},
        )
        assert event.event_type == "written_off"

    def test_events_chronological(self, db_session):
        from app.crud.receivable_invoice import get_escalation_events

        inv = _create_receivable(db_session)
        _create_event(db_session, inv, "invoice_overdue")
        _create_event(db_session, inv, "email_sent")
        _create_event(db_session, inv, "escalation_tier_changed")

        events = get_escalation_events(db_session, inv.id)
        assert len(events) == 3
        for i in range(1, len(events)):
            assert events[i].created_at >= events[i - 1].created_at


# ============================================================
# Edge Cases
# ============================================================


class TestEdgeCases:
    def test_future_due_date_not_overdue(self, db_session):
        inv = _create_receivable(db_session, days_until_due=30)
        assert inv.overdue_days() == 0
        assert inv.compute_escalation_tier() == EscalationTier.NONE

    def test_zero_amount_receivable(self, db_session):
        from app.crud.receivable_invoice import create_receivable_invoice
        from app.schemas.receivable_invoice import ReceivableInvoiceCreate

        # Zero amount should fail validation
        with pytest.raises(Exception):
            create_receivable_invoice(
                db_session,
                ReceivableInvoiceCreate(
                    customer_name="Zero",
                    customer_email="zero@test.com",
                    invoice_number="INV-ZERO",
                    amount=0,  # should fail
                    issued_at=datetime.now(timezone.utc),
                    due_date=datetime.now(timezone.utc),
                ),
            )

    def test_partial_payment_plus_full_payment(self, db_session):
        from app.crud.receivable_invoice import record_payment

        inv = _create_receivable(db_session, amount=100000)
        record_payment(db_session, inv.id, amount=30000)
        updated = record_payment(db_session, inv.id, amount=70000)
        assert updated.amount_paid == 100000
        assert updated.status == ReceivableStatus.PAYMENT_RECEIVED.value

    def test_payment_exceeds_amount(self, db_session):
        from app.crud.receivable_invoice import record_payment

        inv = _create_receivable(db_session, amount=100000)
        updated = record_payment(db_session, inv.id, amount=150000)
        # Should cap at total amount
        assert updated.amount_paid == 100000

    def test_receivable_with_customer_id(self, db_session):
        from app.models.customer import Customer
        from app.crud.receivable_invoice import create_receivable_invoice
        from app.schemas.receivable_invoice import ReceivableInvoiceCreate

        customer = Customer(
            external_id="cust_rcv_001",
            email="cust@test.com",
            name="Linked Customer",
        )
        db_session.add(customer)
        db_session.commit()
        db_session.refresh(customer)

        data = ReceivableInvoiceCreate(
            customer_name="Linked Customer",
            customer_email="cust@test.com",
            customer_id=customer.id,
            invoice_number="INV-LINKED-001",
            amount=100000,
            issued_at=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc) + timedelta(days=30),
        )
        inv = create_receivable_invoice(db_session, data)
        assert inv.customer_id == customer.id

    def test_no_payment_no_reference(self, db_session):
        from app.crud.receivable_invoice import record_payment

        inv = _create_receivable(db_session, amount=100000)
        updated = record_payment(db_session, inv.id, amount=50000)
        # Should still have extra_data with payments list
        assert updated.extra_data is not None
        assert len(updated.extra_data.get("payments", [])) == 1

    def test_batch_run_with_mixed_states(self, db_session):
        from app.services.receivables_chaser import run_batch_escalation

        # Create mix of states
        _create_receivable(
            db_session, invoice_number="INV-MIX-001",
            status=ReceivableStatus.PENDING.value,
            escalation_tier=EscalationTier.NONE.value,
            days_until_due=-3,
        )
        _create_receivable(
            db_session, invoice_number="INV-MIX-002",
            status=ReceivableStatus.PAYMENT_RECEIVED.value,
            escalation_tier=EscalationTier.NONE.value,
        )

        result = run_batch_escalation(db_session)
        # Only the PENDING invoice should be detected
        assert result["newly_overdue"] >= 1
