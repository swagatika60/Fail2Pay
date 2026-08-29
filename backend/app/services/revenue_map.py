"""Revenue Map analytics — dashboard metrics built from REAL database rows.

Money rules (never misleading):
- ``recovered_revenue`` is ONLY the sum of verified captured payments
  (rows in the ``payments`` table with ``status == "captured"``).
- ``attempted_recovery`` is the pool of money recovery *engaged*
  (cases with at least one attempt or a captured payment). It is a
  deliberate, separate number from verified recovered revenue — engaging
  a customer is NOT revenue.
- ``at_risk_revenue`` is the unpaid balance still open on live cases.
- ``lost_revenue`` is the original amount of cases closed as lost/stopped.

Everything is computed from the database — nothing is hardcoded.
"""

import logging
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.payment import Payment
from app.models.payment_plan import PaymentPlan
from app.models.recovery_case import RecoveryCase

logger = logging.getLogger(__name__)

OPEN_STATUSES = {
    "AT_RISK",
    "RECOVERY_IN_PROGRESS",
    "PROMISED",
    "SCHEDULED",
    "PARTIALLY_RECOVERED",
}
LOST_STATUSES = {"LOST", "STOPPED"}
PROMISE_SCENARIOS = {"promise_to_pay", "promise_broken_recovered"}

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "hi-en": "Hinglish",
    "or": "Odia",
}

CHANNEL_NAMES = {
    "whatsapp": "WhatsApp",
    "email": "Email",
    "payment_plan": "Payment Plan",
}


def _status(case) -> str:
    return case.status.value if hasattr(case.status, "value") else case.status


def _days_between(start, end) -> float:
    if not start or not end:
        return 0.0
    return max(0.0, (end - start).total_seconds() / 86400.0)


def compute_revenue_map(db: Session) -> dict:
    """Compute the full Revenue Map analytics payload."""
    all_cases = list(db.execute(select(RecoveryCase)).scalars().all())

    if not all_cases:
        return _empty_payload()

    all_payments = list(db.execute(select(Payment)).scalars().all())
    captured = [p for p in all_payments if p.status == "captured"]
    captured_by_case: dict = defaultdict(int)
    payments_by_case: dict = defaultdict(list)
    channel_totals: dict = defaultdict(int)
    channel_counts: dict = defaultdict(int)

    for payment in captured:
        captured_by_case[payment.recovery_case_id] += payment.amount
        payments_by_case[payment.recovery_case_id].append(payment)
        channel = (payment.extra_data or {}).get("channel") or "unknown"
        channel_totals[channel] += payment.amount
        channel_counts[channel] += 1

    # Per-case language (from the case's first conversation).
    all_conversations = list(db.execute(select(Conversation)).scalars().all())
    language_by_case: dict = {}
    for conversation in all_conversations:
        if conversation.recovery_case_id not in language_by_case:
            language_by_case[conversation.recovery_case_id] = (
                (conversation.extra_data or {}).get("language") or "en"
            )

    plans = list(db.execute(select(PaymentPlan)).scalars().all())
    plans_count = len(plans)
    plans_total = sum(p.total_amount for p in plans)
    plans_recovered = sum(p.amount_paid for p in plans)
    plans_remaining = max(plans_total - plans_recovered, 0)

    total_revenue = 0
    at_risk_revenue = 0
    lost_revenue = 0
    attempted_pool = 0
    recovered_count = 0
    attempts_before_recovery_total = 0
    recovery_time_total = 0.0
    earliest_created = None
    latest_paid_at = None

    risk_totals: dict = defaultdict(int)
    risk_counts: dict = defaultdict(int)
    language_totals: dict = defaultdict(int)
    language_counts: dict = defaultdict(int)

    promise_cases: set = set()
    promise_amount = 0
    promise_outstanding = 0
    promise_recovered = 0

    for case in all_cases:
        status = _status(case)
        original = case.original_amount
        total_revenue += original
        case_payments = payments_by_case.get(case.id, [])
        paid = captured_by_case.get(case.id, 0)

        # Money that recovery actually engaged (attempts or verified payment).
        if case.attempt_count > 0 or case_payments:
            attempted_pool += original

        if status in OPEN_STATUSES:
            at_risk_revenue += case.remaining_amount
        elif status in LOST_STATUSES:
            # Unrecovered portion of closed cases only. Captured payments on a
            # lost/stopped case already count toward recovered_revenue, so this
            # is (original - paid) — otherwise revenue would be double counted
            # and Verified + At Risk + Lost would exceed Total.
            lost_revenue += max(original - paid, 0)

        # Promise pool: cases currently PROMISED, or demo cases asked to
        # promise (including ones that later recovered).
        scenario = (case.extra_data or {}).get("scenario")
        if status == "PROMISED" or scenario in PROMISE_SCENARIOS:
            promise_cases.add(case.id)
            promise_amount += original
            promise_outstanding += case.remaining_amount

        # Verified-money attribution only (never messages).
        if paid > 0:
            recovered_count += 1
            attempts_before_recovery_total += case.attempt_count
            risk_totals[case.risk_level] += paid
            risk_counts[case.risk_level] += 1
            lang = language_by_case.get(case.id, "en")
            language_totals[lang] += paid
            language_counts[lang] += 1

            paid_times = [p.paid_at for p in case_payments if p.paid_at]
            if paid_times and case.created_at:
                recovery_time_total += _days_between(
                    case.created_at, max(paid_times)
                )
                for pt in paid_times:
                    if latest_paid_at is None or pt > latest_paid_at:
                        latest_paid_at = pt

        if case.created_at:
            if earliest_created is None or case.created_at < earliest_created:
                earliest_created = case.created_at

    for case_id in promise_cases:
        promise_recovered += captured_by_case.get(case_id, 0)

    recovered_revenue = sum(captured_by_case.values())
    recovery_rate = recovered_revenue / total_revenue if total_revenue else 0.0
    avg_time = (
        round(recovery_time_total / recovered_count, 1) if recovered_count else 0.0
    )
    avg_attempts = (
        round(attempts_before_recovery_total / recovered_count, 1)
        if recovered_count
        else 0.0
    )
    attempted_unfulfilled = max(attempted_pool - recovered_revenue, 0)

    funnel = [
        {
            "name": "Expected Revenue",
            "amount": total_revenue,
            "tooltip": "All failed payments entering recovery",
        },
        {
            "name": "Entered Recovery",
            "amount": attempted_pool,
            "tooltip": "Money recovery engaged via attempts (not yet revenue)",
        },
        {
            "name": "Verified Recovered",
            "amount": recovered_revenue,
            "tooltip": "Captured payments only — real money collected",
        },
        {
            "name": "Lost Revenue",
            "amount": lost_revenue,
            "tooltip": "Cases closed lost or opted out",
        },
        {
            "name": "Still At Risk",
            "amount": at_risk_revenue,
            "tooltip": "Unpaid balance on open cases",
        },
    ]

    channel_slices = [
        {
            "channel": channel,
            "name": CHANNEL_NAMES.get(channel, channel.title()),
            "amount": channel_totals[channel],
            "count": channel_counts[channel],
        }
        for channel in sorted(
            channel_totals, key=lambda c: channel_totals[c], reverse=True
        )
    ]

    risk_slices = [
        {
            "risk_level": level,
            "amount": risk_totals[level],
            "count": risk_counts[level],
        }
        for level in ("high", "medium", "low")
        if risk_totals.get(level, 0) > 0
    ]

    language_slices = [
        {
            "language": lang,
            "name": LANGUAGE_NAMES.get(lang, lang.title()),
            "amount": language_totals[lang],
            "count": language_counts[lang],
        }
        for lang in sorted(
            language_totals, key=lambda l: language_totals[l], reverse=True
        )
    ]

    timeline = _build_timeline(all_cases, captured, earliest_created, latest_paid_at)

    return {
        "total_revenue": total_revenue,
        "at_risk_revenue": at_risk_revenue,
        "recovered_revenue": recovered_revenue,
        "lost_revenue": lost_revenue,
        "recovery_rate": round(recovery_rate, 4),
        "avg_recovery_time_days": avg_time,
        "avg_attempts_before_recovery": avg_attempts,
        "attempted_recovery": attempted_pool,
        "attempted_unfulfilled": attempted_unfulfilled,
        "payments_count": len(captured),
        "cases_count": len(all_cases),
        "funnel": funnel,
        "recovery_by_channel": channel_slices,
        "recovery_by_risk_level": risk_slices,
        "recovery_by_language": language_slices,
        "payment_plan_recovery": {
            "plans_count": plans_count,
            "total_amount": plans_total,
            "recovered_amount": plans_recovered,
            "remaining_amount": plans_remaining,
            "recovery_rate": round(
                plans_recovered / plans_total if plans_total else 0.0, 4
            ),
        },
        "promise_to_pay_recovery": {
            "promised_cases": len(promise_cases),
            "promised_amount": promise_amount,
            "recovered_amount": promise_recovered,
            "outstanding_amount": promise_outstanding,
            "recovery_rate": round(
                promise_recovered / promise_amount if promise_amount else 0.0, 4
            ),
        },
        "recovery_timeline": timeline,
    }


def _build_timeline(
    all_cases: list,
    captured: list,
    earliest: object,
    latest: object,
) -> list:
    """Daily cumulative recovered revenue between first case and last payment.

    Falls back to weekly buckets if the range is very long so the chart
    stays readable without sampling away real data.
    """
    if not captured or earliest is None or latest is None:
        return []

    daily: dict = defaultdict(int)
    for payment in captured:
        daily[payment.paid_at.date()] += payment.amount

    span_days = (latest.date() - earliest.date()).days
    if span_days <= 0:
        return []

    if span_days > 120:
        # weekly buckets
        weekly: dict = defaultdict(int)
        for day, amount in daily.items():
            week_start = day - timedelta(days=day.weekday())
            weekly[week_start] += amount
        ordered = sorted(daily.keys()) + []
        points = sorted(weekly.items())
        cumulative = 0
        series = []
        for day, amount in points:
            cumulative += amount
            series.append(
                {
                    "label": day.isoformat(),
                    "recovered": amount,
                    "cumulative": cumulative,
                }
            )
        return series

    cumulative = 0
    series = []
    cursor = earliest.date()
    end = latest.date()
    while cursor <= end:
        amount = daily.get(cursor, 0)
        cumulative += amount
        series.append(
            {
                "label": cursor.isoformat(),
                "recovered": amount,
                "cumulative": cumulative,
            }
        )
        cursor += timedelta(days=1)
    return series


def _empty_payload() -> dict:
    return {
        "total_revenue": 0,
        "at_risk_revenue": 0,
        "recovered_revenue": 0,
        "lost_revenue": 0,
        "recovery_rate": 0.0,
        "avg_recovery_time_days": 0.0,
        "avg_attempts_before_recovery": 0.0,
        "attempted_recovery": 0,
        "attempted_unfulfilled": 0,
        "payments_count": 0,
        "cases_count": 0,
        "funnel": [],
        "recovery_by_channel": [],
        "recovery_by_risk_level": [],
        "recovery_by_language": [],
        "payment_plan_recovery": {
            "plans_count": 0,
            "total_amount": 0,
            "recovered_amount": 0,
            "remaining_amount": 0,
            "recovery_rate": 0.0,
        },
        "promise_to_pay_recovery": {
            "promised_cases": 0,
            "promised_amount": 0,
            "recovered_amount": 0,
            "outstanding_amount": 0,
            "recovery_rate": 0.0,
        },
        "recovery_timeline": [],
    }