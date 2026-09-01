"""Automatic transactional emails fire from the agent's settlement flows.

- A ``payment.failed`` event automatically sends a FAILED_PAYMENT email to the
  customer (with the retry payment link) as soon as the recovery case is created.
- A full ``payment.captured`` event (case fully settled) automatically sends a
  PAYMENT_SUCCESS confirmation email to the customer.
- An installment/pay-later plan completing in full also sends the PAYMENT_SUCCESS
  email (the plan path does not traverse the webhook finalizer).
- A customer who has opted out does NOT receive even the success email.
"""

import uuid

from sqlalchemy import select

from app.models.email import EmailType, SentEmail
from app.services import webhook_handler


def _failed_payload() -> dict:
    return {
        "id": "ev_auto_failed",
        "payload": {"payment": {"entity": {
            "id": "pay_auto_1", "order_id": "ord_auto_1", "amount": 50000,
            "currency": "INR", "status": "failed", "failure_reason": "bank_timeout",
            "method": "card", "email": "auto@example.com", "contact": "919999999990",
        }}},
    }


def _captured_payload() -> dict:
    return {
        "id": "ev_auto_captured",
        "payload": {"payment": {"entity": {
            "id": "pay_auto_1", "order_id": "ord_auto_1", "amount": 50000,
            "currency": "INR", "status": "captured", "method": "card",
        }}},
    }


def _emails_for(db, case_id) -> dict:
    case_id = uuid.UUID(str(case_id))
    rows = db.execute(
        select(SentEmail).where(SentEmail.recovery_case_id == case_id)
    ).scalars().all()
    return {e.email_type: e for e in rows}


def _new_case(db, *, amount=50000):
    from app.models.customer import Customer
    from app.models.recovery_case import RecoveryCase

    c = Customer(
        external_id=f"auto_{uuid.uuid4().hex[:8]}", email="inst@example.com",
        name="Inst", phone="919999999991",
    )
    db.add(c)
    db.flush()
    case = RecoveryCase(
        customer_id=c.id, revenue_event_id=uuid.uuid4(),
        original_amount=amount, remaining_amount=amount,
        status="AT_RISK", risk_level="MEDIUM", risk_reason="test",
    )
    db.add(case)
    db.commit()
    return case


class TestAutoEmails:
    def test_failed_payment_auto_sends_failed_email(self, db_session):
        failed = webhook_handler.process_payment_failed(db_session, _failed_payload())
        emails = _emails_for(db_session, failed["case_id"])
        assert EmailType.FAILED_PAYMENT.value in emails, emails.keys()
        assert emails[EmailType.FAILED_PAYMENT.value].delivery_status == "sent"

    def test_capture_auto_sends_success_email(self, db_session):
        failed = webhook_handler.process_payment_failed(db_session, _failed_payload())
        captured = webhook_handler.process_payment_captured(
            db_session, _captured_payload()
        )
        case_id = captured.get("case_id") or failed["case_id"]
        assert captured["status"] == "processed"
        emails = _emails_for(db_session, case_id)
        assert EmailType.FAILED_PAYMENT.value in emails, emails.keys()
        assert EmailType.PAYMENT_SUCCESS.value in emails, emails.keys()
        assert emails[EmailType.PAYMENT_SUCCESS.value].delivery_status == "sent"

    def test_installment_completion_auto_sends_success_email(self, db_session):
        """A plan-finalizing installment capture also sends the success email."""
        from app.models.recovery_case import RecoveryStatus
        from app.services.payment_plan import (
            create_payment_plan_for_case,
            record_installment_payment,
        )
        from app.crud.payment_plan import get_payment_plan, get_installments_for_plan

        case = _new_case(db_session, amount=500000)
        created = create_payment_plan_for_case(
            db_session, case.id, installment_amount=200000,
            frequency="weekly", customer_message="pay later",
        )
        assert created["status"] == "created"

        plan = get_payment_plan(db_session, uuid.UUID(created["plan_id"]))
        installments = get_installments_for_plan(db_session, plan.id)
        assert installments
        for inst in installments:
            res = record_installment_payment(
                db_session, inst.id, inst.amount, f"rp_{inst.id.hex[:6]}"
            )
            assert res["status"] == "paid"

        db_session.refresh(case)
        assert case.status == RecoveryStatus.RECOVERED
        emails = _emails_for(db_session, case.id)
        assert EmailType.PAYMENT_SUCCESS.value in emails, emails.keys()
        assert emails[EmailType.PAYMENT_SUCCESS.value].delivery_status == "sent"

    def test_opt_out_still_blocks_success_email(self, db_session):
        """A customer who opted out does NOT receive even the success email."""
        from app.models.conversation import Conversation
        from app.models.conversation_message import ConversationMessage

        failed = webhook_handler.process_payment_failed(db_session, _failed_payload())
        case_id = uuid.UUID(str(failed["case_id"]))
        conv = Conversation(recovery_case_id=case_id, channel="whatsapp")
        db_session.add(conv)
        db_session.flush()
        db_session.add(ConversationMessage(
            conversation_id=conv.id, direction="inbound", content="stop",
            message_type="text",
        ))
        db_session.commit()

        webhook_handler.process_payment_captured(db_session, _captured_payload())
        emails = _emails_for(db_session, case_id)
        assert EmailType.FAILED_PAYMENT.value in emails, emails.keys()
        assert EmailType.PAYMENT_SUCCESS.value not in emails, emails.keys()
