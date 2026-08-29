"""Tests for the Revenue Map analytics (verified-money dashboard)."""

from sqlalchemy import select

from app.models.payment import Payment
from app.services.revenue_map import compute_revenue_map
from app.services.simulation import SCENARIOS, run_simulation


def _captured_total(db_session) -> int:
    payments = list(db_session.execute(select(Payment)).scalars().all())
    return sum(p.amount for p in payments if p.status == "captured")


def test_revenue_map_recovered_is_only_verified_payments(db_session):
    """recovered_revenue must equal the sum of captured Payment rows and
    nothing else (no messages, no promises)."""
    run_simulation(db_session)
    rm = compute_revenue_map(db_session)

    assert rm["recovered_revenue"] == _captured_total(db_session)
    assert rm["recovered_revenue"] > 0
    assert rm["payments_count"] > 0


def test_breakdowns_sum_exactly_to_recovered_revenue(db_session):
    run_simulation(db_session)
    rm = compute_revenue_map(db_session)

    by_channel = sum(s["amount"] for s in rm["recovery_by_channel"])
    by_risk = sum(s["amount"] for s in rm["recovery_by_risk_level"])
    by_language = sum(s["amount"] for s in rm["recovery_by_language"])

    assert by_channel == rm["recovered_revenue"]
    assert by_risk == rm["recovered_revenue"]
    assert by_language == rm["recovered_revenue"]


def test_channel_breakdown_contains_expected_channels(db_session):
    run_simulation(db_session)
    rm = compute_revenue_map(db_session)

    channels = {s["channel"] for s in rm["recovery_by_channel"]}
    assert "whatsapp" in channels
    assert "email" in channels
    assert "payment_plan" in channels


def test_funnel_and_attempt_vs_recovered_distinction(db_session):
    run_simulation(db_session)
    rm = compute_revenue_map(db_session)

    funnel = {stage["name"]: stage["amount"] for stage in rm["funnel"]}

    assert funnel["Expected Revenue"] == rm["total_revenue"]
    assert funnel["Verified Recovered"] == rm["recovered_revenue"]

    # Attempted recovery is a bigger pool than verified recovered revenue and
    # the shortfall is never negative (recovery may not have touched all of it).
    assert rm["attempted_recovery"] >= rm["recovered_revenue"]
    assert rm["attempted_unfulfilled"] >= 0


def test_recovery_time_and_attempts_metrics(db_session):
    run_simulation(db_session)
    rm = compute_revenue_map(db_session)

    assert rm["avg_recovery_time_days"] >= 0
    assert rm["avg_attempts_before_recovery"] >= 0


def test_recovery_timeline_is_cumulative_to_recovered(db_session):
    run_simulation(db_session)
    rm = compute_revenue_map(db_session)

    timeline = rm["recovery_timeline"]
    assert len(timeline) > 0

    cumulative = 0
    for point in timeline:
        cumulative += point["recovered"]
        assert point["cumulative"] == cumulative
    assert timeline[-1]["cumulative"] == rm["recovered_revenue"]


def test_payment_plan_and_promise_panels(db_session):
    run_simulation(db_session)
    rm = compute_revenue_map(db_session)

    plans = rm["payment_plan_recovery"]
    assert plans["plans_count"] == SCENARIOS["payment_plan_request"] + SCENARIOS["plan_partial"]
    assert plans["total_amount"] > 0
    assert plans["recovered_amount"] > 0  # installments actually paid
    assert plans["remaining_amount"] > 0  # scheduled not yet paid

    promises = rm["promise_to_pay_recovery"]
    assert promises["promised_cases"] == SCENARIOS["promise_to_pay"] + SCENARIOS["promise_broken_recovered"]
    assert promises["promised_amount"] > 0
    assert promises["recovered_amount"] > 0  # promise-broken-then-paid cases
    assert promises["outstanding_amount"] > 0  # still-promised money


def test_revenue_map_empty_database(db_session):
    rm = compute_revenue_map(db_session)

    assert rm["total_revenue"] == 0
    assert rm["recovered_revenue"] == 0
    assert rm["funnel"] == []
    assert rm["recovery_timeline"] == []


def test_reconciled_sum_matches_total_revenue(db_session):
    """Verified Recovered + Still At Risk + Lost must equal Total Revenue.

    Captured payments on a closed (lost/stopped) case must not be double
    counted: it counts toward recovered, and only the unrecovered remainder
    is "lost".
    """
    run_simulation(db_session)
    rm = compute_revenue_map(db_session)

    funnel = {stage["name"]: stage["amount"] for stage in rm["funnel"]}

    assert (
        rm["recovered_revenue"] + rm["at_risk_revenue"] + rm["lost_revenue"]
        == rm["total_revenue"]
    )
    assert funnel["Verified Recovered"] == rm["recovered_revenue"]
    assert funnel["Still At Risk"] == rm["at_risk_revenue"]
    assert funnel["Lost Revenue"] == rm["lost_revenue"]
    assert (
        funnel["Verified Recovered"]
        + funnel["Still At Risk"]
        + funnel["Lost Revenue"]
        == funnel["Expected Revenue"]
    )
    assert rm["attempted_unfulfilled"] == max(
        rm["attempted_recovery"] - rm["recovered_revenue"], 0
    )