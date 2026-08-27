"""Tests for Centralized Hard Stop Service.

Covers:
- All 10 hard stop conditions
- Intent-based stop handling (STOP_REQUEST, ALREADY_PAID, NEGATIVE)
- Integration with WhatsApp, Email, Scheduler
- Audit trail creation
- Promise cancellation on stop
- Multi-language stop keywords
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.recovery_attempt import RecoveryAttempt
from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.payment_plan import PaymentPlan, PaymentPlanStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.audit_event import AuditEvent
from app.models.scheduled_action import ScheduledAction
from app.models.promise import Promise, PromiseStatus
from app.schemas.audit_event import AuditEventCreate
from app.schemas.scheduled_action import ScheduledActionCreate
from app.crud.audit_event import create_audit_event


# ============ Helpers ============

def _create_customer(db, ext_id="cust_hs_1"):
    c = Customer(external_id=ext_id, email=f"{ext_id}@test.com", name="Test User", phone="+911234567890")
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


def _create_attempt(db, case, channel="whatsapp", result="sent"):
    attempt = RecoveryAttempt(
        recovery_case_id=case.id, attempt_number=1,
        channel=channel, status="sent", result=result,
    )
    db.add(attempt)
    db.commit()
    return attempt


def _create_conversation(db, case, channel="whatsapp"):
    conv = Conversation(recovery_case_id=case.id, channel=channel)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _create_inbound_message(db, conversation, content):
    msg = ConversationMessage(
        conversation_id=conversation.id, direction="inbound",
        content=content, message_type="text",
    )
    db.add(msg)
    db.commit()
    return msg


def _create_scheduled_action(db, case, action_type="reminder_1"):
    action = ScheduledAction(
        recovery_case_id=case.id, action_type=action_type,
        attempt_number=1, channel="whatsapp",
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=4),
        status="pending",
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


# ============ Condition 1: Payment Succeeded ============

class TestPaymentSucceeded:
    def test_not_blocked_when_payment_pending(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c1")
        case = _create_case(db_session, c, amount=120000)
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False

    def test_blocked_when_fully_paid(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c2")
        case = _create_case(db_session, c, amount=120000)
        case.remaining_amount = 0
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        assert result.stop_condition == "payment_succeeded"

    def test_blocked_when_status_recovered(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c3")
        case = _create_case(db_session, c)
        case.status = RecoveryStatus.RECOVERED
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        assert result.stop_condition == "payment_succeeded"


# ============ Condition 2: Customer Requested Stop ============

class TestCustomerStopped:
    def test_blocked_when_case_stopped(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c4")
        case = _create_case(db_session, c)
        case.status = RecoveryStatus.STOPPED
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        assert result.stop_condition == "customer_stopped"


# ============ Condition 3: Customer Opted Out ============

class TestCustomerOptedOut:
    def test_not_blocked_without_opt_out(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c5")
        case = _create_case(db_session, c)
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False

    def test_blocked_when_stop_keyword_in_message(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c6")
        case = _create_case(db_session, c)
        conv = _create_conversation(db_session, case)
        _create_inbound_message(db_session, conv, "Please stop messaging me")
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        assert result.stop_condition == "customer_opted_out"

    def test_blocked_hindi_stop_keyword(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c7")
        case = _create_case(db_session, c)
        conv = _create_conversation(db_session, case)
        _create_inbound_message(db_session, conv, "मत भेजो")
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True

    def test_blocked_hinglish_stop_keyword(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c8")
        case = _create_case(db_session, c)
        conv = _create_conversation(db_session, case)
        _create_inbound_message(db_session, conv, "Band karo please")
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True

    def test_not_blocked_with_normal_message(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c9")
        case = _create_case(db_session, c)
        conv = _create_conversation(db_session, case)
        _create_inbound_message(db_session, conv, "Can I pay next week?")
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False


# ============ Condition 4: Case Closed ============

class TestCaseClosed:
    def test_blocked_when_closed(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c10")
        case = _create_case(db_session, c)
        case.closed_at = datetime.now(timezone.utc)
        case.status = RecoveryStatus.LOST
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        assert result.stop_condition == "case_closed"


# ============ Condition 5: Max Attempts Reached ============

class TestMaxAttempts:
    def test_not_blocked_below_max(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c11")
        case = _create_case(db_session, c)
        case.attempt_count = 3
        case.max_attempts = 5
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False

    def test_blocked_at_max(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c12")
        case = _create_case(db_session, c)
        case.attempt_count = 5
        case.max_attempts = 5
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        assert result.stop_condition == "max_attempts_reached"


# ============ Condition 6: Deadline Expired ============

class TestDeadlineExpired:
    def test_not_blocked_without_deadline(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c13")
        case = _create_case(db_session, c)
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False

    def test_not_blocked_with_future_deadline(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c14")
        case = _create_case(db_session, c)
        case.recovery_deadline = datetime.now(timezone.utc) + timedelta(days=7)
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False

    def test_blocked_with_past_deadline(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c15")
        case = _create_case(db_session, c)
        case.recovery_deadline = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        assert result.stop_condition == "deadline_expired"


# ============ Condition 7: Plan Cancelled ============

class TestPlanCancelled:
    def test_not_blocked_without_plan(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c16")
        case = _create_case(db_session, c)
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False

    def test_not_blocked_with_active_plan(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c17")
        case = _create_case(db_session, c)
        plan = PaymentPlan(
            recovery_case_id=case.id, customer_id=c.id,
            total_amount=120000, installment_amount=30000,
            number_of_installments=4, frequency="weekly",
            status=PaymentPlanStatus.ACTIVE.value,
        )
        db_session.add(plan)
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False

    def test_blocked_with_cancelled_plan(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c18")
        case = _create_case(db_session, c)
        plan = PaymentPlan(
            recovery_case_id=case.id, customer_id=c.id,
            total_amount=120000, installment_amount=30000,
            number_of_installments=4, frequency="weekly",
            status=PaymentPlanStatus.CANCELLED.value,
        )
        db_session.add(plan)
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        assert result.stop_condition == "plan_cancelled"


# ============ Condition 8: Invoice Paid ============

class TestInvoicePaid:
    def test_not_blocked_without_invoice(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c19")
        case = _create_case(db_session, c)
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False

    def test_not_blocked_with_pending_invoice(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c20")
        case = _create_case(db_session, c)
        inv = Invoice(
            recovery_case_id=case.id, customer_id=c.id,
            invoice_number="INV-001", amount=120000,
            status=InvoiceStatus.PENDING.value, secure_token="tok1",
        )
        db_session.add(inv)
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False

    def test_blocked_with_paid_invoice(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c21")
        case = _create_case(db_session, c)
        inv = Invoice(
            recovery_case_id=case.id, customer_id=c.id,
            invoice_number="INV-002", amount=120000,
            status=InvoiceStatus.PAID.value, secure_token="tok2",
        )
        db_session.add(inv)
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        assert result.stop_condition == "invoice_paid"


# ============ Condition 10: Conflicting Action ============

class TestConflictingAction:
    def test_blocked_when_case_terminal(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c22")
        case = _create_case(db_session, c)
        case.status = RecoveryStatus.RECOVERED
        db_session.commit()
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True

    def test_not_blocked_for_active_case(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c23")
        case = _create_case(db_session, c)
        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False


# ============ Intent-Based Stop Handling ============

class TestStopRequestIntent:
    def test_stop_request_stops_case(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c24")
        case = _create_case(db_session, c)

        result = handle_stop_intent(
            db_session, case.id, "STOP_REQUEST", "Stop messaging me"
        )

        assert result.blocked is True
        assert result.stop_condition == "customer_stopped"
        assert result.status_updated is True
        assert result.audit_created is True

        db_session.refresh(case)
        assert case.status == RecoveryStatus.STOPPED
        assert case.closed_at is not None

    def test_stop_request_cancels_actions(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c25")
        case = _create_case(db_session, c)

        # Create pending actions
        _create_scheduled_action(db_session, case, "reminder_1")
        _create_scheduled_action(db_session, case, "reminder_2")
        _create_scheduled_action(db_session, case, "reminder_3")

        result = handle_stop_intent(
            db_session, case.id, "STOP_REQUEST", "मत भेजो"
        )

        assert result.actions_cancelled == 3

    def test_stop_request_cancels_promise(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c26")
        case = _create_case(db_session, c)

        promise = Promise(
            recovery_case_id=case.id, customer_id=c.id,
            amount_promised=50000,
            promised_date=datetime.now(timezone.utc) + timedelta(days=3),
            status=PromiseStatus.ACTIVE.value,
        )
        db_session.add(promise)
        db_session.commit()

        handle_stop_intent(db_session, case.id, "STOP_REQUEST", "Leave me alone")

        db_session.refresh(promise)
        assert promise.status == PromiseStatus.CANCELLED.value

    def test_stop_request_creates_audit(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c27")
        case = _create_case(db_session, c)

        handle_stop_intent(db_session, case.id, "STOP_REQUEST", "Stop")

        audit = db_session.execute(
            __import__("sqlalchemy").select(AuditEvent).where(
                AuditEvent.recovery_case_id == case.id,
                AuditEvent.action == "hard_stop_customer_stopped",
            )
        ).scalar_one_or_none()
        assert audit is not None


class TestAlreadyPaidIntent:
    def test_already_paid_verified(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c28")
        case = _create_case(db_session, c, amount=120000)
        case.remaining_amount = 0
        db_session.commit()

        result = handle_stop_intent(
            db_session, case.id, "ALREADY_PAID", "I already paid"
        )

        assert result.blocked is True
        assert result.stop_condition == "payment_succeeded"
        assert result.status_updated is True

        db_session.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED

    def test_already_paid_not_verified(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c29")
        case = _create_case(db_session, c, amount=120000)
        # remaining_amount is still 120000

        result = handle_stop_intent(
            db_session, case.id, "ALREADY_PAID", "I already paid"
        )

        assert result.blocked is False
        assert "not verified" in result.reason.lower()

    def test_already_paid_does_not_falsely_claim(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c30")
        case = _create_case(db_session, c, amount=120000)
        # Payment is NOT complete
        case.remaining_amount = 60000
        db_session.commit()

        result = handle_stop_intent(
            db_session, case.id, "ALREADY_PAID", "Payment kar diya"
        )

        # Should NOT claim success
        assert result.blocked is False
        assert result.stop_condition != "payment_succeeded"

        db_session.refresh(case)
        assert case.status != RecoveryStatus.RECOVERED


class TestNegativeIntent:
    def test_negative_stops_case(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c31")
        case = _create_case(db_session, c)

        result = handle_stop_intent(
            db_session, case.id, "NEGATIVE", "No, I don't want this"
        )

        assert result.blocked is True
        assert result.stop_condition == "customer_opted_out"
        assert result.status_updated is True

        db_session.refresh(case)
        assert case.status == RecoveryStatus.STOPPED

    def test_negative_cancels_actions(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c32")
        case = _create_case(db_session, c)
        _create_scheduled_action(db_session, case)

        result = handle_stop_intent(
            db_session, case.id, "NEGATIVE", "I don't want this"
        )

        assert result.actions_cancelled >= 1


class TestOtherIntents:
    def test_question_does_not_trigger_stop(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c33")
        case = _create_case(db_session, c)

        result = handle_stop_intent(
            db_session, case.id, "QUESTION", "What is this for?"
        )

        assert result.blocked is False

    def test_promise_to_pay_does_not_trigger_stop(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        c = _create_customer(db_session, "c34")
        case = _create_case(db_session, c)

        result = handle_stop_intent(
            db_session, case.id, "PROMISE_TO_PAY", "I'll pay tomorrow"
        )

        assert result.blocked is False


# ============ WhatsApp Integration ============

class TestWhatsAppIntegration:
    def test_whatsapp_blocked_by_hard_stop(self, db_session):
        """WhatsApp message is blocked when hard stop condition is met."""
        from app.services.whatsapp import send_text_message

        c = _create_customer(db_session, "c35")
        case = _create_case(db_session, c)
        case.status = RecoveryStatus.STOPPED
        db_session.commit()

        result = send_text_message(
            db_session, "+911234567890", "Test message", case.id
        )

        assert result["status"] == "blocked"
        assert "stop" in result.get("reason", "").lower() or "stop" in result.get("stop_condition", "").lower()


class TestEmailIntegration:
    def test_email_blocked_by_hard_stop(self, db_session):
        """Email is blocked when hard stop condition is met."""
        from app.services.email import send_recovery_email

        c = _create_customer(db_session, "c36")
        case = _create_case(db_session, c)
        case.status = RecoveryStatus.STOPPED
        db_session.commit()

        result = send_recovery_email(
            db_session, case.id, "failed_payment"
        )

        assert result["status"] == "blocked"


# ============ Edge Cases ============

class TestEdgeCases:
    def test_nonexistent_case(self, db_session):
        from app.services.hard_stop import check_hard_stop
        result = check_hard_stop(db_session, uuid.uuid4())
        assert result.blocked is True
        assert "not found" in result.reason.lower()

    def test_nonexistent_case_handle_stop(self, db_session):
        from app.services.hard_stop import handle_stop_intent
        result = handle_stop_intent(
            db_session, uuid.uuid4(), "STOP_REQUEST", "Stop"
        )
        assert result.blocked is True

    def test_multiple_conditions_met(self, db_session):
        """When multiple conditions are met, the first one found wins."""
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c37")
        case = _create_case(db_session, c)
        # Both stopped AND past deadline
        case.status = RecoveryStatus.STOPPED
        case.recovery_deadline = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.commit()

        result = check_hard_stop(db_session, case.id)
        assert result.blocked is True
        # customer_stopped is checked before deadline_expired
        assert result.stop_condition == "customer_stopped"

    def test_all_checks_pass_for_active_case(self, db_session):
        from app.services.hard_stop import check_hard_stop
        c = _create_customer(db_session, "c38")
        case = _create_case(db_session, c)
        case.recovery_deadline = datetime.now(timezone.utc) + timedelta(days=30)
        db_session.commit()

        result = check_hard_stop(db_session, case.id)
        assert result.blocked is False
        assert result.reason == "All checks passed"
