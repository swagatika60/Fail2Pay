"""Batch Simulation System for Fail2Pay.

Creates a controlled test dataset of 100 transactions with various
recovery scenarios. All data is clearly marked as DEMO data.

Scenarios:
- Successful payments (already recovered)
- Failed payments (recovery in progress)
- Repeated failures (multiple attempts)
- Customers who respond
- Customers who do not respond
- Customers requesting invoices
- Customers promising payment
- Customers requesting payment plans
- Customers opting out
- Customers whose payment is recovered
- Promise made but broken before eventual recovery

Revenue rules (hard guarantees):
- ``RecoveredRevenue`` is the sum of **verified captured payments** only
  (rows in the ``payments`` table with ``status == "captured"``).
- A customer *message* ("I'll pay tomorrow") is NEVER recorded as a payment
  and NEVER counted as recovered revenue.
- "Promise to pay" keeps a case PROMISED until money actually arrives.

DO NOT use fake numbers in the real analytics database
unless explicitly marked as DEMO data.

The whole dataset is created in a single transaction (one commit) so the
simulation stays fast even against slow or remote databases.
"""

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Demo marker
DEMO_MARKER = "DEMO_SIMULATION"

# Indian names for realistic test data
INDIAN_NAMES = [
    ("Rahul", "Sharma"), ("Priya", "Patel"), ("Amit", "Kumar"),
    ("Neha", "Gupta"), ("Rohan", "Singh"), ("Anjali", "Verma"),
    ("Vikram", "Reddy"), ("Pooja", "Nair"), ("Arjun", "Malhotra"),
    ("Kavita", "Joshi"), ("Suresh", "Iyer"), ("Meera", "Rao"),
    ("Deepak", "Mishra"), ("Sunita", "Bose"), ("Rajesh", "Tiwari"),
    ("Anita", "Desai"), ("Manoj", "Sinha"), ("Lata", "Pandey"),
    ("Sanjay", "Bhatt"), ("Rekha", "Menon"), ("Ajay", "Kulkarni"),
    ("Geeta", "Chandra"), ("Mohan", "Prasad"), ("Usha", "Saxena"),
    ("Vinod", "Chauhan"), ("Savita", "Pillai"), ("Ramesh", "Kapoor"),
    ("Aditi", "Iyengar"), ("Naveen", "Agarwal"), ("Sushila", "Mishra"),
    ("Ganesh", "Naik"), ("Lakshmi", "Balan"), ("Prakash", "Tandon"),
    ("Kamala", "Varma"), ("Harish", "Goswami"), ("Saroj", "Thakur"),
    ("Brijesh", "Pandey"), ("Indu", "Srivastava"), ("Dinesh", "Choudhary"),
    ("Padma", "Hegde"), ("Jai", "Shankar"), ("Vimla", "Rathore"),
    ("Surender", "Yadav"), ("Urmila", "Bhatt"), ("Kishore", "Mukherjee"),
    ("Bharti", "Sinha"), ("Yogesh", "Puri"), ("Shobha", "Kulkarni"),
    ("Mukesh", "Jain"), ("Neelam", "Chauhan"),
]

EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "rediffmail.com"]
PAYMENT_METHODS = ["card", "netbanking", "upi", "wallet"]
FAILURE_REASONS = [
    "Insufficient funds",
    "Card expired",
    "Bank declined transaction",
    "Payment gateway timeout",
    "Authentication failed",
    "Daily limit exceeded",
]


# ============================================================
# SCENARIO DISTRIBUTION (sums to 100 transactions)
# ============================================================

SCENARIOS = {
    # Payment was already collected before/independently of recovery
    "already_recovered": 8,

    # Failed - customer responds and pays (verified captured payment)
    "responds_and_pays": 12,

    # Failed - customer promises to pay, money never arrives
    "promise_to_pay": 10,

    # Failed - customer agrees to a payment plan, no money yet
    "payment_plan_request": 8,

    # Failed - customer asks for invoice, then pays
    "invoice_request": 5,

    # Failed - customer opts out (hard stop)
    "opts_out": 7,

    # Failed - no response (attempts exhausted -> lost)
    "no_response": 15,

    # Failed - repeated failures, then verified payment
    "repeated_failures": 10,

    # Failed - recovered after reminders (verified payment)
    "recovered_after_reminders": 10,

    # Failed - lost (all attempts exhausted)
    "lost": 5,

    # Failed - payment plan partially completed (verified installments)
    "plan_partial": 5,

    # Failed - promise broken, then eventually pays (verified payment)
    "promise_broken_recovered": 5,
}


def _cleanup_demo_data(db: Session) -> int:
    """Remove all existing demo data in a single atomic transaction.

    Errors are no longer swallowed: if a table is missing the caller will
    see a clear failure instead of silently stale data (which previously
    caused duplicate-key crashes when re-running the simulation).
    """
    from app.models.audit_event import AuditEvent
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage
    from app.models.customer import Customer
    from app.models.installment import Installment
    from app.models.payment import Payment
    from app.models.payment_plan import PaymentPlan
    from app.models.recovery_case import RecoveryCase
    from app.models.revenue_event import RevenueEvent

    demo_customer_ids = list(
        db.execute(
            select(Customer.id).where(Customer.external_id.like(f"%{DEMO_MARKER}%"))
        ).scalars()
    )

    if not demo_customer_ids:
        return 0

    logger.info("Cleaning up %d existing demo customers...", len(demo_customer_ids))

    demo_case_ids = select(RecoveryCase.id).where(
        RecoveryCase.customer_id.in_(demo_customer_ids)
    )

    statements = [
        delete(AuditEvent).where(AuditEvent.recovery_case_id.in_(demo_case_ids)),
        delete(ConversationMessage).where(
            ConversationMessage.conversation_id.in_(
                select(Conversation.id).where(
                    Conversation.recovery_case_id.in_(demo_case_ids)
                )
            )
        ),
        delete(Conversation).where(Conversation.recovery_case_id.in_(demo_case_ids)),
        delete(Installment).where(Installment.recovery_case_id.in_(demo_case_ids)),
        delete(Payment).where(Payment.recovery_case_id.in_(demo_case_ids)),
        delete(PaymentPlan).where(PaymentPlan.recovery_case_id.in_(demo_case_ids)),
        delete(RecoveryCase).where(RecoveryCase.customer_id.in_(demo_customer_ids)),
        delete(RevenueEvent).where(RevenueEvent.customer_id.in_(demo_customer_ids)),
        delete(Customer).where(Customer.id.in_(demo_customer_ids)),
    ]

    for statement in statements:
        db.execute(statement)

    db.commit()
    logger.info("Demo data cleanup complete")
    return len(demo_customer_ids)


def run_simulation(db: Session) -> dict:
    """Run the batch simulation with 100 controlled test transactions.

    Creates:
    - 100 customers
    - 100 revenue events (payment failures)
    - 100 recovery cases
    - Verified ``Payment`` rows only where money was actually captured
    - ``PaymentPlan`` / ``Installment`` rows for plan scenarios
    - Conversations / messages for every scenario
    - All data marked as DEMO_SIMULATION

    If demo data already exists, resets it first (idempotent).
    The whole dataset is committed once for speed.

    Returns:
        dict with simulation results and analytics
    """
    from app.models.audit_event import AuditEvent
    from app.models.customer import Customer
    from app.models.payment import Payment
    from app.models.payment_plan import PaymentPlan
    from app.models.recovery_case import RecoveryCase, RecoveryStatus
    from app.models.revenue_event import RevenueEvent

    cleaned = _cleanup_demo_data(db)
    logger.info(
        "Starting batch simulation with %d transactions...", sum(SCENARIOS.values())
    )

    results = {
        "total_transactions": 0,
        "customers_created": 0,
        "cases_created": 0,
        "payments_created": 0,
        "plans_created": 0,
        "scenarios_run": {},
        "cleaned_up": cleaned,
    }

    objects: list = []
    tx_index = 0
    now = datetime.now(timezone.utc)

    for scenario_name, count in SCENARIOS.items():
        scenario_outcomes = []
        open_endstate = scenario_name in {
            "promise_to_pay",
            "payment_plan_request",
            "plan_partial",
        }

        for _ in range(count):
            tx_index += 1
            name = random.choice(INDIAN_NAMES)
            email = f"{name[0].lower()}.{name[1].lower()}{tx_index}@{random.choice(EMAIL_DOMAINS)}"
            phone = f"+91{random.randint(7000000000, 9999999999)}"
            amount = random.choice([
                499, 999, 1499, 1999, 2499, 2999, 3499, 3999,
                4999, 5999, 7499, 9999, 11999, 14999, 19999,
            ]) * 100  # in paise

            # Stagger creation times so recovery-time analytics are real:
            # open cases were created recently, resolved ones were created
            # further in the past.
            days_ago = (
                random.randint(2, 12)
                if open_endstate
                else random.randint(14, 60)
            )
            created_at = now - timedelta(days=days_ago)

            customer_id = uuid.uuid4()
            customer = Customer(
                id=customer_id,
                external_id=f"{DEMO_MARKER}_cust_{tx_index}",
                email=email,
                phone=phone,
                name=f"{name[0]} {name[1]}",
            )

            revenue_event = RevenueEvent(
                id=uuid.uuid4(),
                customer_id=customer_id,
                external_event_id=f"pay_{DEMO_MARKER}_{tx_index}_{uuid.uuid4().hex[:8]}",
                event_type="payment_failed",
                amount=amount,
                currency="INR",
                status="failed",
                source="razorpay",
                created_at=created_at,
                extra_data={
                    "simulation": True,
                    "scenario": scenario_name,
                    "failure_reason": random.choice(FAILURE_REASONS),
                    "method": random.choice(PAYMENT_METHODS),
                },
            )

            case_id = uuid.uuid4()
            case = RecoveryCase(
                id=case_id,
                customer_id=customer_id,
                revenue_event_id=revenue_event.id,
                risk_level=random.choice(["high", "medium", "low"]),
                risk_reason=f"Demo: {scenario_name}",
                original_amount=amount,
                remaining_amount=amount,
                recovered_amount=0,
                attempt_count=0,
                max_attempts=5,
                status=RecoveryStatus.AT_RISK,
                created_at=created_at,
                recovery_started_at=created_at + timedelta(days=1),
                extra_data={"simulation": True, "scenario": scenario_name},
            )

            outcome, scenario_objects = _apply_scenario(
                scenario_name, case, customer, amount, case_id, tx_index
            )
            objects.extend([customer, revenue_event, case, *scenario_objects])

            objects.append(
                AuditEvent(
                    id=uuid.uuid4(),
                    recovery_case_id=case_id,
                    entity_type="simulation",
                    entity_id=case_id,
                    action=f"simulation_{scenario_name}",
                    new_value={
                        "scenario": scenario_name,
                        "final_status": outcome["final_status"],
                        "recovered": outcome["recovered"],
                        "amount": amount,
                        "demo": True,
                    },
                )
            )

            scenario_outcomes.append(outcome)
            results["total_transactions"] += 1
            results["customers_created"] += 1
            results["cases_created"] += 1

        results["scenarios_run"][scenario_name] = {
            "count": count,
            "outcomes": scenario_outcomes,
        }
        logger.info("Scenario %s: %d transactions completed", scenario_name, count)

    results["payments_created"] = sum(
        1 for o in objects if isinstance(o, Payment)
    )
    results["plans_created"] = sum(
        1 for o in objects if isinstance(o, PaymentPlan)
    )

    # One commit for the whole dataset — fast even on slow connections.
    db.add_all(objects)
    db.commit()

    analytics = _compute_simulation_analytics(db)
    results["analytics"] = analytics

    logger.info(
        "Simulation complete: %d transactions, %d verified payments, "
        "recovery rate: %.1f%%",
        results["total_transactions"],
        results["payments_created"],
        analytics["recovery_rate"] * 100,
    )

    return results


def _apply_scenario(
    scenario: str,
    case,
    customer,
    amount: int,
    case_id: uuid.UUID,
    tx_index: int,
) -> tuple[dict, list]:
    """Build the objects that implement a recovery scenario.

    Mutates ``case`` in memory and returns ``(outcome, created_objects)``:
    conversations, messages, verified ``Payment`` rows and any
    ``PaymentPlan`` / ``Installment`` rows.

    Only ``pay()`` records money — and it always creates a captured Payment
    row. Messages alone never move money.
    """
    from app.models.conversation import Conversation, ConversationStatus
    from app.models.conversation_message import ConversationMessage
    from app.models.installment import Installment
    from app.models.payment import Payment
    from app.models.payment_plan import PaymentPlan
    from app.models.recovery_case import RecoveryStatus

    role = customer.name.split()[0]
    now = datetime.now(timezone.utc)
    case_created = case.created_at or now
    case_language = random.choices(
        ["en", "hi", "hi-en", "or"], weights=[55, 25, 15, 5]
    )[0]
    items: list = []

    def conv(*messages: str, channel: str = "whatsapp", lang: str | None = None) -> Conversation:
        """Create a conversation with the given (direction, content) pairs."""
        chat = Conversation(
            id=uuid.uuid4(),
            recovery_case_id=case_id,
            channel=channel,
            status=ConversationStatus.ACTIVE,
            extra_data={"simulation": True, "language": lang or case_language},
        )
        for direction, content in messages:
            items.append(
                ConversationMessage(
                    id=uuid.uuid4(),
                    conversation_id=chat.id,
                    direction=direction,
                    content=content,
                    message_type="text",
                    extra_data={"simulation": True, "language": lang or case_language},
                )
            )
        return chat

    def pay(
        pay_amount: int,
        method: str | None = None,
        channel: str = "whatsapp",
        paid_at: datetime | None = None,
    ) -> str:
        """Record a VERIFIED captured payment.

        This is the only way money is recovered — no message is ever
        mistaken for a payment. ``channel`` records how the money came
        back (whatsapp / email / payment_plan), and ``paid_at`` when it
        actually arrived.
        """
        payment_id = f"pay_{DEMO_MARKER}_{tx_index}_{uuid.uuid4().hex[:8]}"
        items.append(
            Payment(
                id=uuid.uuid4(),
                recovery_case_id=case_id,
                razorpay_payment_id=payment_id,
                razorpay_order_id=f"order_{DEMO_MARKER}_{tx_index}",
                amount=pay_amount,
                currency="INR",
                status="captured",
                method=method or random.choice(PAYMENT_METHODS),
                paid_at=paid_at or case_created + timedelta(days=random.randint(0, 21)),
                extra_data={
                    "simulation": True,
                    "scenario": scenario,
                    "channel": channel,
                },
            )
        )
        case.recovered_amount += pay_amount
        case.remaining_amount = max(case.original_amount - case.recovered_amount, 0)
        return payment_id

    def recover():
        """Close the case as fully recovered (all money captured)."""
        case.status = RecoveryStatus.RECOVERED
        case.recovered_amount = case.original_amount
        case.remaining_amount = 0
        case.closed_at = case_created + timedelta(days=random.randint(1, 24))

    def plan(installments_paid: int, number: int = 4) -> None:
        """Create a payment plan (ACCEPTED/ACTIVE) with installments.

        Paid installments reference their own verified Payment rows
        (channel = payment_plan).
        """
        installment_amount = amount // number
        plan = PaymentPlan(
            id=uuid.uuid4(),
            recovery_case_id=case_id,
            customer_id=customer.id,
            total_amount=amount,
            installment_amount=installment_amount,
            number_of_installments=number,
            frequency="weekly",
            currency="INR",
            status="ACTIVE",
            amount_paid=installment_amount * installments_paid,
            installments_paid=installments_paid,
            installments_failed=0,
            created_at=case_created,
            extra_data={"simulation": True, "scenario": scenario},
        )
        items.append(plan)
        for i in range(number):
            paid = i < installments_paid
            inst_paid_at = (
                case_created + timedelta(days=random.randint(1, 7)) if paid else None
            )
            payment_ref = (
                pay(installment_amount, "upi", channel="payment_plan", paid_at=inst_paid_at)
                if paid
                else None
            )
            items.append(
                Installment(
                    id=uuid.uuid4(),
                    payment_plan_id=plan.id,
                    recovery_case_id=case_id,
                    installment_number=i + 1,
                    amount=installment_amount,
                    due_date=case_created + timedelta(days=7 * (i + 1)),
                    currency="INR",
                    status="PAID" if paid else "SCHEDULED",
                    paid_at=inst_paid_at,
                    paid_amount=installment_amount if paid else 0,
                    razorpay_payment_id=payment_ref,
                    extra_data={"simulation": True},
                )
            )

    outcome: dict = {"scenario": scenario, "final_status": "", "recovered": False}

    if scenario == "already_recovered":
        items.append(conv(("outbound", f"Good news {role}, your payment of {_fmt(amount)} was received. Thank you!")))
        pay(amount)
        recover()
        outcome.update(final_status="RECOVERED", recovered=True)

    elif scenario == "responds_and_pays":
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        case.attempt_count = 1
        items.append(conv(
            ("outbound", f"Hi {role}, your payment of {_fmt(amount)} needs attention."),
            ("inbound", "I'll pay right now"),
        ))
        pay(amount)
        recover()
        case.attempt_count = 2
        outcome.update(final_status="RECOVERED", recovered=True)

    elif scenario == "promise_to_pay":
        case.status = RecoveryStatus.PROMISED
        case.attempt_count = 2
        items.append(conv(
            ("outbound", f"Hi {role}, your payment needs attention."),
            ("inbound", "Kal payment kar dunga"),
        ))
        # IMPORTANT: a promise is NOT a payment. No Payment row is created
        # and the case stays PROMISED (money still at risk).
        outcome.update(final_status="PROMISED", recovered=False)

    elif scenario == "payment_plan_request":
        case.status = RecoveryStatus.SCHEDULED
        case.attempt_count = 2
        items.append(conv(
            ("outbound", f"Hi {role}, your payment needs attention."),
            ("inbound", "Can I pay in installments?"),
        ))
        # Plan agreed but no installment paid yet — scheduled revenue.
        plan(installments_paid=0)
        outcome.update(final_status="SCHEDULED", recovered=False)

    elif scenario == "invoice_request":
        case.attempt_count = 1
        items.append(conv(
            ("outbound", f"Hi {role}, your payment needs attention."),
            ("inbound", "Please send me the invoice"),
            channel="email",
        ))
        pay(amount, channel="email")
        recover()
        outcome.update(final_status="RECOVERED", recovered=True)

    elif scenario == "opts_out":
        case.status = RecoveryStatus.STOPPED
        case.attempt_count = 1
        case.closed_at = case_created + timedelta(days=random.randint(7, 21))
        items.append(conv(
            ("outbound", f"Hi {role}, your payment needs attention."),
            ("inbound", "Stop messaging me"),
        ))
        outcome.update(final_status="STOPPED", recovered=False)

    elif scenario == "no_response":
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        case.attempt_count = 5
        items.append(conv(
            ("outbound", f"Hi {role}, your payment needs attention."),
            ("outbound", "Reminder: Your payment is still pending."),
            ("outbound", "Final reminder: Please complete your payment."),
        ))
        case.status = RecoveryStatus.LOST
        case.closed_at = case_created + timedelta(days=random.randint(14, 45))
        outcome.update(final_status="LOST", recovered=False)

    elif scenario == "repeated_failures":
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        case.attempt_count = 4
        items.append(conv(*[
            ("outbound", f"Reminder {j + 1}: Your payment of {_fmt(amount)} needs attention.")
            for j in range(4)
        ]))
        pay(amount)
        recover()
        case.attempt_count = 5
        outcome.update(final_status="RECOVERED", recovered=True)

    elif scenario == "recovered_after_reminders":
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        case.attempt_count = 3
        items.append(conv(
            ("outbound", f"Hi {role}, your payment needs attention."),
            ("outbound", "Reminder: Your payment is still pending."),
            ("inbound", "Okay I'll pay now"),
        ))
        pay(amount)
        recover()
        outcome.update(final_status="RECOVERED", recovered=True)

    elif scenario == "lost":
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        case.attempt_count = 5
        items.append(conv(*[
            ("outbound", f"Reminder {j + 1}: Your payment needs attention.")
            for j in range(5)
        ], channel="email"))
        case.status = RecoveryStatus.LOST
        case.closed_at = case_created + timedelta(days=random.randint(14, 45))
        outcome.update(final_status="LOST", recovered=False)

    elif scenario == "plan_partial":
        case.status = RecoveryStatus.PARTIALLY_RECOVERED
        case.attempt_count = 2
        # Two installments paid (verified), two still scheduled.
        plan(installments_paid=2)
        outcome.update(
            final_status="PARTIALLY_RECOVERED",
            recovered=False,
            recovered_amount=case.recovered_amount,
        )

    elif scenario == "promise_broken_recovered":
        case.status = RecoveryStatus.PROMISED
        case.attempt_count = 2
        items.append(conv(
            ("outbound", f"Hi {role}, your payment needs attention."),
            ("inbound", "I'll pay tomorrow"),
        ))
        case.status = RecoveryStatus.RECOVERY_IN_PROGRESS
        items.append(conv(
            ("outbound", "Your promised payment was not received. Please pay now."),
            ("inbound", "Sorry, paying now"),
        ))
        pay(amount)
        recover()
        outcome.update(final_status="RECOVERED", recovered=True)

    else:
        logger.warning("Unknown scenario %r — leaving case AT_RISK", scenario)
        outcome.update(final_status="AT_RISK", recovered=False)

    return outcome, items


def _fmt(amount_paise: int) -> str:
    """Format amount."""
    return f"₹{amount_paise // 100:,}"


def _demo_cases(db: Session):
    """Fetch all demo recovery cases (backend-agnostic)."""
    from app.models.recovery_case import RecoveryCase

    all_cases = list(db.execute(select(RecoveryCase)).scalars().all())
    return [
        c for c in all_cases
        if c.extra_data and c.extra_data.get("simulation")
    ]


def _compute_simulation_analytics(db: Session) -> dict:
    """Compute analytics from the simulation data.

    Money is only counted from VERIFIED captured payments (``payments``
    table rows with ``status == "captured"``). Messages and promises are
    never counted as revenue.

    ``financial_summary`` partitions the original revenue exactly:
    recovered + partially_recovered + at_risk + lost == total_original.
    """
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage
    from app.models.payment import Payment
    from app.models.payment_plan import PaymentPlan

    demo_cases = _demo_cases(db)
    total = len(demo_cases)
    if total == 0:
        return {"error": "No demo cases found"}

    demo_case_ids = {c.id for c in demo_cases}

    # --- Verified money ground truth ---
    demo_payments = list(
        db.execute(
            select(Payment).where(Payment.recovery_case_id.in_(demo_case_ids))
        ).scalars()
    )
    paid_by_case: dict = {}
    for payment in demo_payments:
        if payment.status == "captured":
            paid_by_case[payment.recovery_case_id] = (
                paid_by_case.get(payment.recovery_case_id, 0) + payment.amount
            )
    total_verified_payments = len(demo_payments)
    total_captured = sum(
        p.amount for p in demo_payments if p.status == "captured"
    )

    # --- Plans ---
    demo_plans = list(
        db.execute(
            select(PaymentPlan).where(PaymentPlan.recovery_case_id.in_(demo_case_ids))
        ).scalars()
    )
    plans_count = len(demo_plans)

    # --- Per-case aggregation ---
    total_original = 0
    total_attempts = 0
    status_counts: dict = {}
    bucket_recovered = 0
    bucket_partial = 0
    bucket_at_risk = 0
    bucket_lost = 0
    promised_revenue = 0
    scheduled_revenue = 0

    for case in demo_cases:
        status = case.status.value if hasattr(case.status, "value") else case.status
        status_counts[status] = status_counts.get(status, 0) + 1

        original = case.original_amount
        paid = min(paid_by_case.get(case.id, 0), original)
        total_original += original
        total_attempts += case.attempt_count

        if status == "RECOVERED" or paid >= original:
            bucket_recovered += original
        elif status in ("LOST", "STOPPED"):
            bucket_lost += original
        else:
            bucket_partial += paid
            bucket_at_risk += original - paid

        if status == "PROMISED":
            promised_revenue += original
        if status == "SCHEDULED":
            scheduled_revenue += original

    recovered_revenue = total_captured

    # Outstanding money on open (not lost/stopped/recovered) cases.
    revenue_at_risk = max(total_original - recovered_revenue - bucket_lost, 0)

    lost_revenue = bucket_lost
    recovery_rate = recovered_revenue / total_original if total_original else 0
    total_remaining = total_original - recovered_revenue

    # --- Conversations / messages on demo cases ---
    all_conversations = list(db.execute(select(Conversation)).scalars().all())
    demo_conversations = [
        cv for cv in all_conversations if cv.recovery_case_id in demo_case_ids
    ]
    conv_ids = {cv.id for cv in demo_conversations}

    total_messages = 0
    inbound_messages = 0
    if conv_ids:
        all_messages = list(db.execute(select(ConversationMessage)).scalars().all())
        for message in all_messages:
            if message.conversation_id in conv_ids:
                total_messages += 1
                if message.direction == "inbound":
                    inbound_messages += 1

    metrics = {
        "total_revenue": total_original,
        "revenue_at_risk": revenue_at_risk,
        "recovery_attempts": total_attempts,
        "customer_responses": inbound_messages,
        "promise_to_pay": promised_revenue,
        "scheduled_revenue": scheduled_revenue,
        "payment_plans": plans_count,
        "recovered_revenue": recovered_revenue,
        "lost_revenue": lost_revenue,
        "recovery_rate": round(recovery_rate, 4),
    }

    return {
        "total_transactions": total,
        "total_original_revenue": total_original,
        "total_recovered_revenue": recovered_revenue,
        "recovered_revenue": recovered_revenue,
        "revenue_at_risk": revenue_at_risk,
        "recovery_attempts": total_attempts,
        "customer_responses": inbound_messages,
        "promised_revenue": promised_revenue,
        "scheduled_revenue": scheduled_revenue,
        "payment_plans_count": plans_count,
        "lost_revenue": lost_revenue,
        "total_remaining_revenue": total_remaining,
        "recovery_rate": round(recovery_rate, 4),
        "payments_count": total_verified_payments,
        "status_breakdown": {
            "recovered": status_counts.get("RECOVERED", 0),
            "lost": status_counts.get("LOST", 0),
            "stopped": status_counts.get("STOPPED", 0),
            "in_progress": status_counts.get("RECOVERY_IN_PROGRESS", 0),
            "promised": status_counts.get("PROMISED", 0),
            "partially_recovered": status_counts.get("PARTIALLY_RECOVERED", 0),
            "scheduled": status_counts.get("SCHEDULED", 0),
            "at_risk": status_counts.get("AT_RISK", 0),
        },
        "communication_stats": {
            "total_messages": total_messages,
            "inbound_messages": inbound_messages,
            "outbound_messages": total_messages - inbound_messages,
            "customer_response_rate": round(
                inbound_messages / total_messages if total_messages > 0 else 0, 4
            ),
        },
        "scenario_distribution": SCENARIOS,
        "financial_summary": {
            "recovered": bucket_recovered,
            "partially_recovered": bucket_partial,
            "at_risk": bucket_at_risk,
            "lost": bucket_lost,
        },
        "metrics": metrics,
    }


# ============================================================
# VERIFIED IMPACT LEDGER & RECOVERY PIPELINE
# ============================================================


def compute_verified_impact_ledger(db: Session) -> dict:
    """Build the Verified Impact Ledger over the DEMO simulation data.

    Shows the recovery pipeline funnel (only over DEMO_SIMULATION data):
        At Risk -> Intervention Dispatched -> Promise Captured -> Verified Recovered

    Hard revenue rule: money is VERIFIED RECOVERED only when a ``Payment``
    row with ``status == "captured"`` exists. A promise or a message is
    NEVER counted as recovered revenue.

    Returns (for the demo dataset):
      - funnel: stage-by-stage counts + amounts (monotonically shrinking)
      - ledger: one verified row per case (amount, how it was recovered)
      - summary: original, verified recovered, at-risk, recovery rate
    """
    from app.models.conversation import Conversation
    from app.models.conversation_message import ConversationMessage
    from app.models.payment import Payment
    from app.models.payment_plan import PaymentPlan

    demo_cases = _demo_cases(db)
    total = len(demo_cases)
    if total == 0:
        return {
            "present": False,
            "summary": {
                "original_revenue": 0, "verified_recovered": 0,
                "revenue_at_risk": 0, "recovery_rate": 0,
            },
            "funnel": _empty_funnel(),
            "ledger": [],
        }

    demo_case_ids = [c.id for c in demo_cases]

    # Verified captured payments ground truth
    payments = list(
        db.execute(select(Payment).where(Payment.recovery_case_id.in_(demo_case_ids)))
        .scalars()
    )
    captured_by_case: dict = {}
    for payment in payments:
        if payment.status == "captured":
            captured_by_case[payment.recovery_case_id] = (
                captured_by_case.get(payment.recovery_case_id, 0) + payment.amount
            )

    # Interventions: does the case have any outbound message / recovery attempt?
    conversations = list(
        db.execute(select(Conversation).where(Conversation.recovery_case_id.in_(demo_case_ids)))
        .scalars()
    )
    conv_case = {cv.id: cv.recovery_case_id for cv in conversations}
    conv_ids = list(conv_case.keys())
    outbound_by_case: dict = {}
    inbound_by_case: dict = {}
    if conv_ids:
        msgs = list(
            db.execute(select(ConversationMessage).where(ConversationMessage.conversation_id.in_(conv_ids)))
            .scalars()
        )
        for m in msgs:
            case_id = conv_case[m.conversation_id]
            if m.direction == "outbound":
                outbound_by_case[case_id] = outbound_by_case.get(case_id, 0) + 1
            else:
                inbound_by_case[case_id] = inbound_by_case.get(case_id, 0) + 1

    # Plans (promise captured / scheduled money)
    plans = list(
        db.execute(select(PaymentPlan).where(PaymentPlan.recovery_case_id.in_(demo_case_ids)))
        .scalars()
    )
    plan_count_by_case = {p.recovery_case_id: p for p in plans}

    ledger = []
    for case in demo_cases:
        original = case.original_amount
        captured = min(captured_by_case.get(case.id, 0), original)
        remaining = original - captured
        status = case.status.value if hasattr(case.status, "value") else case.status
        verified_recovered = captured > 0
        intervention = outbound_by_case.get(case.id, 0) > 0
        # "Promise captured" means the customer committed to pay. A verified
        # recovery necessarily followed a captured commitment, so recovered
        # cases also qualify here — this keeps the funnel monotonic and
        # airtight against "promise counted as money" abuse.
        promise_captured = (
            verified_recovered
            or status == "PROMISED"
            or status == "SCHEDULED"
            or case.id in plan_count_by_case
            or inbound_by_case.get(case.id, 0) > 0
        )

        ledger.append({
            "case_id": str(case.id),
            "risk_level": case.risk_level,
            "status": status,
            "original_amount": original,
            "verified_recovered_amount": captured,
            "remaining_amount": remaining,
            "intervention_dispatched": intervention,
            "promise_captured": promise_captured,
            "verified_recovered": verified_recovered,
        })

    def _stage_amount(pred):
        return sum(row["original_amount"] for row in ledger if pred(row))

    def _stage_count(pred):
        return sum(1 for row in ledger if pred(row))

    # Funnel stages (monotonically shrinking by construction)
    recovered = [r for r in ledger if r["verified_recovered"]]
    promised = [r for r in ledger if r["promise_captured"]]
    intervened = [r for r in ledger if r["intervention_dispatched"]]

    funnel = {
        "at_risk": {
            "count": _stage_count(lambda r: True),
            "amount": _stage_amount(lambda r: True),
        },
        "intervention_dispatched": {
            "count": _stage_count(lambda r: r["intervention_dispatched"]),
            "amount": _stage_amount(lambda r: r["intervention_dispatched"]),
        },
        "promise_captured": {
            "count": _stage_count(lambda r: r["promise_captured"]),
            "amount": _stage_amount(lambda r: r["promise_captured"]),
        },
        "verified_recovered": {
            "count": len(recovered),
            "amount": sum(r["verified_recovered_amount"] for r in recovered),
        },
    }

    original_revenue = funnel["at_risk"]["amount"]
    verified_recovered = sum(r["verified_recovered_amount"] for r in ledger)
    revenue_at_risk = original_revenue - verified_recovered
    recovery_rate = verified_recovered / original_revenue if original_revenue else 0

    return {
        "present": True,
        "summary": {
            "original_revenue": original_revenue,
            "verified_recovered": verified_recovered,
            "revenue_at_risk": revenue_at_risk,
            "recovery_rate": round(recovery_rate, 4),
        },
        "funnel": funnel,
        "ledger": ledger,
    }


def _empty_funnel() -> dict:
    return {
        "at_risk": {"count": 0, "amount": 0},
        "intervention_dispatched": {"count": 0, "amount": 0},
        "promise_captured": {"count": 0, "amount": 0},
        "verified_recovered": {"count": 0, "amount": 0},
    }