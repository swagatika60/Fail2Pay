import uuid
from datetime import datetime, timedelta, timezone

from app.models.customer import Customer
from app.models.revenue_event import RevenueEvent
from app.models.recovery_case import RecoveryCase, RecoveryStatus
from app.models.recovery_attempt import RecoveryAttempt
from app.models.conversation import Conversation, ConversationStatus
from app.models.conversation_message import ConversationMessage
from app.models.payment_plan import PaymentPlan, PaymentPlanStatus
from app.models.installment import Installment, InstallmentStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.audit_event import AuditEvent


# ============ Customer Tests ============

class TestCustomer:
    def test_create_customer(self, db_session):
        # basic customer creation
        customer = Customer(
            external_id="cust_123",
            email="test@example.com",
            phone="+911234567890",
            name="Test User",
        )
        db_session.add(customer)
        db_session.commit()

        # check if it was created properly
        assert customer.id is not None
        assert customer.external_id == "cust_123"
        assert customer.email == "test@example.com"

    def test_customer_unique_external_id(self, db_session):
        # external_id should be unique
        c1 = Customer(external_id="cust_123", email="a@test.com")
        c2 = Customer(external_id="cust_123", email="b@test.com")
        db_session.add(c1)
        db_session.commit()

        db_session.add(c2)
        try:
            db_session.commit()
            assert False, "Should have raised IntegrityError"
        except Exception:
            db_session.rollback()

    def test_customer_optional_fields(self, db_session):
        # email, phone, name should be optional
        customer = Customer(external_id="cust_min")
        db_session.add(customer)
        db_session.commit()

        assert customer.email is None
        assert customer.phone is None
        assert customer.name is None


# ============ RevenueEvent Tests ============

class TestRevenueEvent:
    def test_create_revenue_event(self, db_session):
        # first create a customer
        customer = Customer(external_id="cust_1", email="a@test.com")
        db_session.add(customer)
        db_session.commit()

        # then create revenue event
        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_123",
            event_type="payment_failed",
            amount=50000,
            currency="INR",
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        assert event.id is not None
        assert event.amount == 50000
        assert event.currency == "INR"

    def test_revenue_event_with_metadata(self, db_session):
        customer = Customer(external_id="cust_2", email="b@test.com")
        db_session.add(customer)
        db_session.commit()

        # extra_data stores additional info
        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_456",
            event_type="subscription_cancelled",
            amount=10000,
            status="cancelled",
            source="razorpay",
            extra_data={"reason": "user_request"},
        )
        db_session.add(event)
        db_session.commit()

        assert event.extra_data == {"reason": "user_request"}


# ============ RecoveryCase Tests ============

class TestRecoveryCase:
    def test_create_recovery_case(self, db_session):
        customer = Customer(external_id="cust_3", email="c@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_789",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        # create recovery case with defaults
        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="high",
            risk_reason="High-value payment failure",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        assert case.id is not None
        # check default values
        assert case.status == RecoveryStatus.AT_RISK
        assert case.attempt_count == 0
        assert case.max_attempts == 5
        assert case.recovered_amount == 0

    def test_recovery_case_status_enum(self, db_session):
        # make sure all status values are valid
        for status in RecoveryStatus:
            assert status.value in [
                "AT_RISK", "RECOVERY_IN_PROGRESS", "ENGAGED", "PROMISED",
                "PAYMENT_PLAN",
                "SCHEDULED", "PARTIALLY_RECOVERED", "RECOVERED", "LOST", "STOPPED",
            ]


# ============ RecoveryAttempt Tests ============

class TestRecoveryAttempt:
    def test_create_recovery_attempt(self, db_session):
        # setup - customer + event + case
        customer = Customer(external_id="cust_4", email="d@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_101",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="high",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        # create attempt
        attempt = RecoveryAttempt(
            recovery_case_id=case.id,
            attempt_number=1,
            channel="whatsapp",
            status="sent",
        )
        db_session.add(attempt)
        db_session.commit()

        assert attempt.id is not None
        assert attempt.attempt_number == 1


# ============ Conversation Tests ============

class TestConversation:
    def test_create_conversation(self, db_session):
        # setup
        customer = Customer(external_id="cust_5", email="e@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_102",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="medium",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        # create conversation
        conversation = Conversation(
            recovery_case_id=case.id,
            channel="whatsapp",
        )
        db_session.add(conversation)
        db_session.commit()

        assert conversation.id is not None
        assert conversation.status == ConversationStatus.ACTIVE


# ============ ConversationMessage Tests ============

class TestConversationMessage:
    def test_create_conversation_message(self, db_session):
        # setup
        customer = Customer(external_id="cust_6", email="f@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_103",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="low",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        conversation = Conversation(
            recovery_case_id=case.id,
            channel="whatsapp",
        )
        db_session.add(conversation)
        db_session.commit()

        # create message
        message = ConversationMessage(
            conversation_id=conversation.id,
            direction="outbound",
            content="Hello, your payment is due.",
            message_type="text",
        )
        db_session.add(message)
        db_session.commit()

        assert message.id is not None
        assert message.direction == "outbound"


# ============ PaymentPlan Tests ============

class TestPaymentPlan:
    def test_create_payment_plan(self, db_session):
        # setup
        customer = Customer(external_id="cust_7", email="g@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_104",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="high",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        # create payment plan
        plan = PaymentPlan(
            recovery_case_id=case.id,
            total_amount=50000,
            installment_amount=10000,
            number_of_installments=5,
            frequency="monthly",
        )
        db_session.add(plan)
        db_session.commit()

        assert plan.id is not None
        assert plan.status == PaymentPlanStatus.PROPOSED

    def test_payment_plan_status_enum(self, db_session):
        for status in PaymentPlanStatus:
            assert status.value in [
                "PROPOSED", "ACCEPTED", "ACTIVE", "COMPLETED", "CANCELLED", "DEFAULTED"
            ]


# ============ Installment Tests ============

class TestInstallment:
    def test_create_installment(self, db_session):
        # setup
        customer = Customer(external_id="cust_8", email="h@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_105",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="medium",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        plan = PaymentPlan(
            recovery_case_id=case.id,
            total_amount=50000,
            installment_amount=10000,
            number_of_installments=5,
            frequency="monthly",
        )
        db_session.add(plan)
        db_session.commit()

        # create installment
        installment = Installment(
            payment_plan_id=plan.id,
            installment_number=1,
            amount=10000,
            due_date=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(installment)
        db_session.commit()

        assert installment.id is not None
        assert installment.status == InstallmentStatus.SCHEDULED


# ============ Invoice Tests ============

class TestInvoice:
    def test_create_invoice(self, db_session):
        # setup
        customer = Customer(external_id="cust_9", email="i@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_106",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="low",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        plan = PaymentPlan(
            recovery_case_id=case.id,
            total_amount=50000,
            installment_amount=10000,
            number_of_installments=5,
            frequency="monthly",
        )
        db_session.add(plan)
        db_session.commit()

        # create invoice
        invoice = Invoice(
            recovery_case_id=case.id,
            customer_id=customer.id,
            invoice_number="INV-001",
            amount=10000,
            secure_token="test-token-123",
        )
        db_session.add(invoice)
        db_session.commit()

        assert invoice.id is not None
        assert invoice.status == InvoiceStatus.PENDING.value

    def test_invoice_status_enum(self, db_session):
        for status in InvoiceStatus:
            assert status.value in ["PENDING", "SENT", "VIEWED", "PAID", "CANCELLED"]


# ============ AuditEvent Tests ============

class TestAuditEvent:
    def test_create_audit_event(self, db_session):
        # setup
        customer = Customer(external_id="cust_10", email="j@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_107",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="high",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        # create audit event
        audit = AuditEvent(
            recovery_case_id=case.id,
            entity_type="recovery_case",
            entity_id=case.id,
            action="created",
            new_value={"status": "AT_RISK"},
        )
        db_session.add(audit)
        db_session.commit()

        assert audit.id is not None
        assert audit.action == "created"


# ============ Relationship Tests ============

class TestRelationships:
    def test_customer_to_revenue_events(self, db_session):
        # one customer can have many revenue events
        customer = Customer(external_id="cust_rel_1", email="rel@test.com")
        db_session.add(customer)
        db_session.commit()

        for i in range(3):
            event = RevenueEvent(
                customer_id=customer.id,
                external_event_id=f"evt_rel_{i}",
                event_type="payment_failed",
                amount=10000,
                status="failed",
                source="razorpay",
            )
            db_session.add(event)
        db_session.commit()

        db_session.refresh(customer)
        assert len(customer.revenue_events) == 3

    def test_customer_to_recovery_cases(self, db_session):
        # one customer can have many recovery cases
        customer = Customer(external_id="cust_rel_2", email="rel2@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_rel_2",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        for i in range(2):
            case = RecoveryCase(
                customer_id=customer.id,
                revenue_event_id=event.id,
                risk_level="high",
                original_amount=50000,
                remaining_amount=50000,
            )
            db_session.add(case)
        db_session.commit()

        db_session.refresh(customer)
        assert len(customer.recovery_cases) == 2

    def test_recovery_case_to_attempts(self, db_session):
        # one case can have many attempts
        customer = Customer(external_id="cust_rel_3", email="rel3@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_rel_3",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="high",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        for i in range(3):
            attempt = RecoveryAttempt(
                recovery_case_id=case.id,
                attempt_number=i + 1,
                channel="whatsapp",
                status="sent",
            )
            db_session.add(attempt)
        db_session.commit()

        db_session.refresh(case)
        assert len(case.recovery_attempts) == 3

    def test_recovery_case_to_conversations(self, db_session):
        # one case can have many conversations
        customer = Customer(external_id="cust_rel_4", email="rel4@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_rel_4",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="medium",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        conv = Conversation(recovery_case_id=case.id, channel="whatsapp")
        db_session.add(conv)
        db_session.commit()

        db_session.refresh(case)
        assert len(case.conversations) == 1

    def test_conversation_to_messages(self, db_session):
        # one conversation can have many messages
        customer = Customer(external_id="cust_rel_5", email="rel5@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_rel_5",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="low",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        conv = Conversation(recovery_case_id=case.id, channel="whatsapp")
        db_session.add(conv)
        db_session.commit()

        for i in range(2):
            msg = ConversationMessage(
                conversation_id=conv.id,
                direction="outbound" if i % 2 == 0 else "inbound",
                content=f"Message {i}",
            )
            db_session.add(msg)
        db_session.commit()

        db_session.refresh(conv)
        assert len(conv.messages) == 2

    def test_recovery_case_to_payment_plans(self, db_session):
        # one case can have many payment plans
        customer = Customer(external_id="cust_rel_6", email="rel6@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_rel_6",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="high",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        plan = PaymentPlan(
            recovery_case_id=case.id,
            total_amount=50000,
            installment_amount=10000,
            number_of_installments=5,
            frequency="monthly",
        )
        db_session.add(plan)
        db_session.commit()

        db_session.refresh(case)
        assert len(case.payment_plans) == 1

    def test_payment_plan_to_installments(self, db_session):
        # one payment plan has many installments
        customer = Customer(external_id="cust_rel_7", email="rel7@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_rel_7",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="high",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        plan = PaymentPlan(
            recovery_case_id=case.id,
            total_amount=50000,
            installment_amount=10000,
            number_of_installments=5,
            frequency="monthly",
        )
        db_session.add(plan)
        db_session.commit()

        for i in range(5):
            installment = Installment(
                payment_plan_id=plan.id,
                installment_number=i + 1,
                amount=10000,
                due_date=datetime.now(timezone.utc) + timedelta(days=30 * (i + 1)),
            )
            db_session.add(installment)
        db_session.commit()

        db_session.refresh(plan)
        assert len(plan.installments) == 5

    def test_recovery_case_to_invoices(self, db_session):
        # one recovery case has many invoices
        customer = Customer(external_id="cust_rel_8", email="rel8@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_rel_8",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="medium",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        for i in range(3):
            invoice = Invoice(
                recovery_case_id=case.id,
                customer_id=customer.id,
                invoice_number=f"INV-{i+1:03d}",
                amount=10000,
                secure_token=f"token-{i+1}",
            )
            db_session.add(invoice)
        db_session.commit()

        db_session.refresh(case)
        assert len(case.invoices) == 3

    def test_recovery_case_to_audit_events(self, db_session):
        # one case has many audit events
        customer = Customer(external_id="cust_rel_9", email="rel9@test.com")
        db_session.add(customer)
        db_session.commit()

        event = RevenueEvent(
            customer_id=customer.id,
            external_event_id="evt_rel_9",
            event_type="payment_failed",
            amount=50000,
            status="failed",
            source="razorpay",
        )
        db_session.add(event)
        db_session.commit()

        case = RecoveryCase(
            customer_id=customer.id,
            revenue_event_id=event.id,
            risk_level="high",
            original_amount=50000,
            remaining_amount=50000,
        )
        db_session.add(case)
        db_session.commit()

        for action in ["created", "status_changed", "attempt_added"]:
            audit = AuditEvent(
                recovery_case_id=case.id,
                entity_type="recovery_case",
                entity_id=case.id,
                action=action,
            )
            db_session.add(audit)
        db_session.commit()

        db_session.refresh(case)
        assert len(case.audit_events) == 3
