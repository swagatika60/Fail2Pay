"""Tests for the agent refactor: N-installment calculator, Hinglish replies,
Pay-Now recovery, hard-stop blocking and attempts tracking."""

import uuid

import pytest

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.installment import Installment
from app.services import agent_engine


def _create_customer(db, ext_id="cust_ref_1", phone="919999700001"):
    c = Customer(
        external_id=ext_id,
        email=f"{ext_id}@test.com",
        name="Vinod Kumar",
        phone=phone,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _create_case(db, customer, amount=1999900):
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
        status=RecoveryStatus.RECOVERY_IN_PROGRESS, attempt_count=0, max_attempts=5,
        extra_data={"failure_reason": "bank_timeout"},
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ---------------------------------------------------------------
# 1. Installment calculator
# ---------------------------------------------------------------


class TestCalculator:
    def test_exact_total_no_remainder(self):
        amounts = agent_engine.calculate_installments(200000, 2)
        assert amounts == [100000, 100000]
        assert sum(amounts) == 200000

    def test_remainder_distributed_to_initial_tranches(self):
        # 19999 paise over 2 -> base 9999, remainder 1 -> [10000, 9999]
        amounts = agent_engine.calculate_installments(19999, 2)
        assert amounts[0] == 10000
        assert amounts[1] == 9999
        assert sum(amounts) == 19999

    def test_four_installments(self):
        # 10 paise over 4 -> base 2, remainder 2 -> [3,3,2,2]
        amounts = agent_engine.calculate_installments(10, 4)
        assert amounts == [3, 3, 2, 2]
        assert sum(amounts) == 10

    def test_invalid_count(self):
        with pytest.raises(ValueError):
            agent_engine.calculate_installments(100, 0)

    def test_split_summary_label(self):
        summary = agent_engine.split_summary(1999900, 2)
        assert "2 installments" in summary["label"]
        assert len(summary["amounts"]) == 2
        assert sum(summary["amounts"]) == 1999900


# ---------------------------------------------------------------
# 2. Hinglish replies + history context
# ---------------------------------------------------------------


class TestHinglishAndHistory:
    def test_hinglish_reply(self):
        payload = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Vinod Kumar",
            amount_paise=1999900, intent="PROMISE_TO_PAY", language="hi",
        )
        assert "Bilkul Vinodji" in payload["text"]
        assert "11:00" in payload["text"]

    def test_hinglish_payment_link(self):
        payload = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Vinod", amount_paise=1000000,
            intent="PAYMENT_LINK_REQUEST", language="hi-en",
        )
        assert "secure payment link" in payload["text"]

    def test_history_changes_acknowledgement(self):
        # First occurrence -> "Thanks for reaching out"
        first = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Vinod", amount_paise=1000000,
            intent="PROMISE_TO_PAY", history=[],
        )
        assert "Thanks" in first["text"]
        # Repeat the same intent -> engine acknowledges dynamically ("Got it")
        repeat = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Vinod", amount_paise=1000000,
            intent="PROMISE_TO_PAY", history=["PROMISE_TO_PAY"],
        )
        assert "Got it" in repeat["text"]


# ---------------------------------------------------------------
# 3. Pay Now -> RECOVERED + metrics
# ---------------------------------------------------------------


class TestPayNowRecovery:
    def test_pay_link_recovers_case_and_updates_metrics(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_pay_1")
        case = _create_case(db_session, c, amount=1999900)

        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="pay_link"), db_session
        )

        assert resp["recovered"] is True
        assert resp["case_status"] == "RECOVERED"
        assert resp["remaining_amount"] == 0
        assert resp["recovered_amount"] == 1999900
        assert resp["recovery_rate"] == 100.0

    def test_pay_now_recovers(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_pay_2", phone="919999700003")
        case = _create_case(db_session, c, amount=1999900)

        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="pay_now"), db_session
        )
        assert resp["recovered"] is True
        assert resp["case_status"] == "RECOVERED"


# ---------------------------------------------------------------
# 4. Stop -> hard stop + block further outreach
# ---------------------------------------------------------------


class TestHardStop:
    def test_stop_marks_hard_stopped(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_stop_1", phone="919999700004")
        case = _create_case(db_session, c)

        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="stop"), db_session
        )
        assert resp["hard_stopped"] is True
        assert resp["case_status"] == "STOPPED"
        assert resp["opt_out_triggered"] is True

    def test_further_outreach_blocked_after_stop(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_stop_2", phone="919999700005")
        case = _create_case(db_session, c)

        simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="stop"), db_session
        )
        # Any subsequent non-stop message must be blocked
        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="promise"), db_session
        )
        assert resp["case_status"] == "STOPPED"
        assert resp["hard_stopped"] is True
        assert "HARD-STOPPED" in resp["guardrail_note"]


# ---------------------------------------------------------------
# 5. N-installment split plans
# ---------------------------------------------------------------


class TestNSplitPlan:
    def test_split_2_creates_two_installments_matching_calculator(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_split_1", phone="919999700006")
        case = _create_case(db_session, c, amount=1999900)

        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="split_2"), db_session
        )
        assert resp["detected_intent"] == "PAYMENT_PLAN_REQUEST"
        split = resp["split_plan"]
        assert split["split_count"] == 2
        assert split["amounts"] == agent_engine.calculate_installments(1999900, 2)

        insts = db_session.query(Installment).filter(
            Installment.recovery_case_id == case.id
        ).order_by(Installment.installment_number).all()
        assert [i.amount for i in insts] == agent_engine.calculate_installments(1999900, 2)
        assert sum(i.amount for i in insts) == 1999900

    def test_split_4_creates_four_installments(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_split_2", phone="919999700007")
        case = _create_case(db_session, c, amount=1999900)

        resp = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="split_4"), db_session
        )
        split = resp["split_plan"]
        assert split["split_count"] == 4
        assert len(split["amounts"]) == 4
        assert sum(split["amounts"]) == 1999900

        insts = db_session.query(Installment).filter(
            Installment.recovery_case_id == case.id
        ).order_by(Installment.installment_number).all()
        assert [i.amount for i in insts] == split["amounts"]


# ---------------------------------------------------------------
# 6. Attempts counter
# ---------------------------------------------------------------


class TestAttemptsCounter:
    def test_attempts_increment_per_turn(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_att_1", phone="919999700008")
        case = _create_case(db_session, c)

        r1 = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="promise"), db_session
        )
        assert r1["attempt_count"] == 1
        r2 = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="installments"), db_session
        )
        assert r2["attempt_count"] == 2


# ---------------------------------------------------------------
# 7. Language persistence + localized Hinglish reply/quick-replies
# ---------------------------------------------------------------


class TestLanguagePersistence:
    def test_language_hi_persists_across_turns(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_lang_1", phone="919999710001")
        case = _create_case(db_session, c)

        first = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="language_hi"), db_session
        )
        assert first["language"] == "hi"

        # A subsequent turn (promise) stays in Hinglish.
        second = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="promise"), db_session
        )
        assert second["language"] == "hi"
        assert "Bilkul" in second["reply_text"]

    def test_repeated_hindi_request_does_not_revert(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_lang_2", phone="919999710002")
        case = _create_case(db_session, c)

        simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="language_hi"), db_session
        )
        # Repeating the Hindi request must NOT toggle back to English.
        again = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="language_hi"), db_session
        )
        assert again["language"] == "hi"
        assert "Namaste" not in again["reply_text"]

    def test_free_text_hindi_request_switches_to_hi(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_lang_3", phone="919999710003")
        case = _create_case(db_session, c)

        resp = simulate_customer_message(
            case.id,
            SimulateMessageRequest(trigger="free_text", message="Hindi mein baat karein"),
            db_session,
        )
        assert resp["language"] == "hi"

    def test_explicit_english_switch_reverts(self, db_session):
        from app.routes.case_detail import simulate_customer_message, SimulateMessageRequest

        c = _create_customer(db_session, ext_id="cust_lang_4", phone="919999710004")
        case = _create_case(db_session, c)

        simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="language_hi"), db_session
        )
        back = simulate_customer_message(
            case.id, SimulateMessageRequest(trigger="language_en"), db_session
        )
        assert back["language"] == "en"
        # English template re-engaged (not the Hinglish "Bilkul ..." copy).
        assert "Bilkul" not in back["reply_text"]
        assert "paused reminders" in back["reply_text"]


class TestLocalizedHinglish:
    def test_support_text_has_no_garbled_phrase(self):
        payload = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Vinod", amount_paise=1999900,
            intent="SUPPORT", language="hi",
        )
        assert "Taaq-hur" not in payload["text"]
        assert "human support team ko connect" in payload["text"]
        assert "2-3 minute" in payload["text"]

    def test_split_breakdown_localized_no_english_label(self):
        details = agent_engine.split_plan_payload(1999900, count=2)
        payload = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Vinod", amount_paise=1999900,
            intent="PAYMENT_PLAN_REQUEST", language="hi",
            split_details=details, split_count=2,
        )
        text = payload["text"]
        # Localized Hinglish breakdown, no verbatim English "installments of...
        # today and ... after 15 days" sentence.
        assert "aaj aur" in text
        assert "agle 15 dinon mein" in text
        assert "installments of" not in text
        assert "after 15 days" not in text

    def test_hinglish_quick_reply_labels_localized(self):
        payload = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Vinod", amount_paise=1999900,
            intent="PAYMENT_LINK_REQUEST", language="hi",
        )
        labels = {qr["id"]: qr["label"] for qr in payload["quick_replies"]}
        assert labels["pay_now"] == "Abhi Pay Karein ₹19,999"
        assert labels["split_2"] == "2 Kishton mein baantein"
        assert labels["support"] == "Support Se Baat Karein"

        plan_payload = agent_engine.build_reply(
            case_id=str(uuid.uuid4()), customer_name="Vinod", amount_paise=1999900,
            intent="PAYMENT_PLAN_REQUEST", language="hi", split_count=2,
        )
        plan_labels = {qr["id"]: qr["label"] for qr in plan_payload["quick_replies"]}
        assert plan_labels["activate_plan"] == "EMI Plan Activate Karein"

    def test_initial_outbound_localized(self):
        payload = agent_engine.build_initial_outbound(
            case_id=str(uuid.uuid4()), customer_name="Mukesh", amount_paise=1999900,
            language="hi", failure_reason="bank_timeout",
        )
        assert "Namaste Mukeshji" in payload["text"]
        labels = {qr["id"]: qr["label"] for qr in payload["quick_replies"]}
        assert labels["pay_now"] == "Abhi Pay Karein ₹19,999"
        assert labels["split_2"] == "2 Kishton mein baantein"
        assert labels["split_4"] == "4 Kishton mein baantein"
        assert labels["support"] == "Support Se Baat Karein"
