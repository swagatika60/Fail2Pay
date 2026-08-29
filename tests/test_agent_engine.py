"""Tests for the Contextual Agent Engine & multi-turn flow.

Validates:
  - build_initial_outbound produces empathetic, contextual copy + action payload
  - build_reply produces contextual replies per intent
  - split-plan handler creates a real 2-EMI plan and contextual reply
  - wrong-bill escalates to human (no hard stop)
  - promise schedules a tomorrow-11AM reminder
  - synchronized HTML email generation for the Emails tab
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.services import agent_engine


def _create_customer(db, ext_id="cust_agent_1", phone="919999400001", email="agent@test.com"):
    c = Customer(
        external_id=ext_id, email=email, name="Mukesh Sharma", phone=phone,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _create_case(db, customer, amount=1999900, failure_reason="bank_timeout", status=RecoveryStatus.RECOVERY_IN_PROGRESS):
    ev = RevenueEvent(
        customer_id=customer.id,
        external_event_id=f"evt_{uuid.uuid4().hex[:8]}",
        event_type="payment_failed", amount=amount, status="failed", source="razorpay",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    case = RecoveryCase(
        customer_id=customer.id, revenue_event_id=ev.id, risk_level="medium",
        original_amount=amount, remaining_amount=amount,
        status=status, extra_data={"failure_reason": failure_reason},
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


class TestInitialOutbound:
    def test_contextual_copy_has_failure_reason_and_amount(self):
        payload = agent_engine.build_initial_outbound(
            case_id="060c3f91efeb4bb2a2e1cdf4e99e301d",
            customer_name="Mukesh Sharma",
            amount_paise=1999900,
            failure_reason="bank_timeout",
        )
        text = payload["text"]
        assert "Mukesh" in text
        assert "₹19,999" in text
        assert "a bank timeout" in text
        assert "060C3F91" in text  # invoice id INV-060C3F91
        assert "https://pay.fail2pay.com/inv/060c3f91efeb4bb2a2e1cdf4e99e301d" in text

    def test_payload_has_quick_replies_payment_card_language(self):
        payload = agent_engine.build_initial_outbound(
            case_id=str(uuid.uuid4()), customer_name="Mukesh", amount_paise=1999900,
        )
        labels = {qr["id"]: qr["label"] for qr in payload["quick_replies"]}
        assert "pay_now" in labels
        assert "₹19,999" in labels["pay_now"]
        assert "split_2" in labels
        assert "split_4" in labels
        assert payload["payment_card"]["gateway"] == "Razorpay"
        assert payload["payment_card"]["label"].startswith("Pay ₹")
        split_ids = {s["id"] for s in payload["split_options"]}
        assert {"split_2", "split_4"} <= split_ids
        langs = {o["code"] for o in payload["language_options"]}
        assert {"en", "hi"} <= langs


class TestReply:
    def test_split_plan_reply(self):
        payload = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Mukesh", amount_paise=1999900,
            intent="PAYMENT_PLAN_REQUEST",
            split_details={"pay_today": "₹10,000", "pay_later": "₹9,999", "later_hint": "after 15 days"},
        )
        assert "Absolutely" in payload["text"]
        assert "₹10,000" in payload["text"]
        assert "after 15 days" in payload["text"]
        assert payload["quick_replies"][0]["id"] == "activate_plan"

    def test_promise_reply_pauses_and_schedules(self):
        payload = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Mukesh", amount_paise=1999900,
            intent="PROMISE_TO_PAY",
        )
        assert "paused reminders" in payload["text"]
        assert "11:00 AM" in payload["text"]

    def test_wrong_bill_reply_escalates(self):
        payload = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Mukesh", amount_paise=1999900,
            intent="QUESTION",
        )
        assert "billing desk" in payload["text"]


class TestEmail:
    def test_subject_format(self):
        subject = agent_engine.build_email_subject(1999900, "INV-060C3F91")
        assert subject == "Action Required: Payment failed for Invoice #INV-060C3F91 (₹19,999)"

    def test_html_email_has_cta_and_dnd_footer(self):
        html = agent_engine.render_payment_failed_email_html(
            customer_name="Mukesh Sharma",
            amount_paise=1999900,
            invoice_id="INV-060C3F91",
            case_id="060c3f91efeb4bb2a2e1cdf4e99e301d",
        )
        assert "Pay Now ₹19,999" in html
        assert "INV-060C3F91" in html
        assert "bank timeout" not in html  # default reason
        assert "Unsubscribe" in html
        assert "DND" in html
        assert "pay.fail2pay.com/inv/060c3f91efeb4bb2a2e1cdf4e99e301d" in html


class TestMultiTurnFlow:
    def test_installments_creates_split_plan_and_reply(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_ins_1")
        case = _create_case(db_session, c, amount=1999900)
        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="installments"), db_session
        )
        assert resp["detected_intent"] == "PAYMENT_PLAN_REQUEST"
        assert resp["split_plan"]["plan_status"] == "created"
        assert resp["reply_text"]
        assert resp["agent_payload"]["quick_replies"][0]["id"] == "activate_plan"

        from app.models.payment_plan import PaymentPlan
        db_session.expire_all()
        plan = db_session.query(PaymentPlan).filter(
            PaymentPlan.recovery_case_id == case.id
        ).first()
        assert plan is not None
        assert plan.number_of_installments == 2

    def test_wrong_bill_escalates_to_human(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_wb_1")
        case = _create_case(db_session, c)
        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="wrong_bill"), db_session
        )
        assert resp["escalated_to_human"] is True
        assert resp["opt_out_triggered"] is False
        assert resp["case_status"] != "STOPPED"
        db_session.expire_all()
        assert case.extra_data.get("escalated_to_human") is True
        assert "billing desk" in resp["reply_text"]

    def test_promise_schedules_reminder_tomorrow(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_prom_1")
        case = _create_case(db_session, c)
        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="promise"), db_session
        )
        assert resp["case_status"] == "PROMISED"
        assert resp["promise_scheduled"] is not None
        assert resp["promise_scheduled"]["reminder_label"] == "reminder for tomorrow at 11:00 AM"
        assert "11:00 AM" in resp["reply_text"]

        from app.models.scheduled_action import ScheduledAction
        db_session.expire_all()
        actions = db_session.query(ScheduledAction).filter(
            ScheduledAction.recovery_case_id == case.id
        ).all()
        assert any(a.action_type == "reminder" for a in actions)

    def test_reply_payload_persisted_in_conversation(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest
        from app.models.conversation import Conversation
        from app.models.conversation_message import ConversationMessage

        c = _create_customer(db_session, ext_id="cust_persist_1")
        case = _create_case(db_session, c)
        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="promise"), db_session
        )

        db_session.expire_all()
        conv = db_session.query(Conversation).filter(
            Conversation.recovery_case_id == case.id, Conversation.channel == "whatsapp"
        ).first()
        assert conv is not None
        outbound = db_session.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conv.id,
            ConversationMessage.direction == "outbound",
        ).all()
        assert len(outbound) >= 1
        last = outbound[-1]
        assert last.content == resp["reply_text"]
        assert last.extra_data["agent_payload"]["text"] == resp["reply_text"]


class TestSynchronizedEmail:
    def test_generate_email_endpoint_creates_html_email(self, db_session):
        from app.routes.case_detail import generate_case_email
        from app.models.email import SentEmail

        c = _create_customer(db_session, ext_id="cust_email_1")
        case = _create_case(db_session, c)
        result = generate_case_email(case.id, db_session)
        assert result["email"] is not None
        assert "Payment failed for Invoice" in result["email"]["subject"]

        db_session.expire_all()
        email = db_session.query(SentEmail).filter(
            SentEmail.recovery_case_id == case.id
        ).first()
        assert email is not None
        assert "Pay Now" in email.body
        assert "Unsubscribe" in email.body

    def test_initial_trigger_persists_bubble_and_email(self, db_session):
        from app.routes.case_detail import generate_agent_initial
        from app.models.conversation import Conversation
        from app.models.conversation_message import ConversationMessage
        from app.models.email import SentEmail

        c = _create_customer(db_session, ext_id="cust_init_1")
        case = _create_case(db_session, c, failure_reason="bank_timeout")
        result = generate_agent_initial(case.id, db_session)
        assert result["message"]
        assert result["email"] is not None

        db_session.expire_all()
        conv = db_session.query(Conversation).filter(
            Conversation.recovery_case_id == case.id, Conversation.channel == "whatsapp"
        ).first()
        outbound = db_session.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conv.id,
            ConversationMessage.direction == "outbound",
        ).all()
        assert outbound and "bank timeout" in outbound[0].content
        email = db_session.query(SentEmail).filter(
            SentEmail.recovery_case_id == case.id
        ).first()
        assert email is not None
