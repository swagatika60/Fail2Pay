from app.services.simulation import (
    SCENARIOS,
    _compute_simulation_analytics,
    run_simulation,
)


def test_run_simulation_creates_full_dataset(db_session):
    results = run_simulation(db_session)

    assert results["total_transactions"] == sum(SCENARIOS.values())
    assert results["customers_created"] == sum(SCENARIOS.values())
    assert results["cases_created"] == sum(SCENARIOS.values())
    assert set(results["scenarios_run"].keys()) == set(SCENARIOS.keys())
    # Verified Captured Payments are the ground truth for recovered money.
    assert results["payments_created"] > 0
    assert results["plans_created"] > 0


def test_simulation_analytics_shape(db_session):
    results = run_simulation(db_session)
    analytics = results["analytics"]

    assert analytics["total_transactions"] == sum(SCENARIOS.values())
    assert analytics["recovery_rate"] >= 0
    assert analytics["recovery_rate"] <= 1
    assert analytics["status_breakdown"]["recovered"] > 0
    assert analytics["communication_stats"]["total_messages"] > 0
    assert analytics["financial_summary"]["recovered"] > 0


def test_recovered_revenue_equals_only_captured_payments(db_session):
    """Recovered revenue must equal the sum of CAPPED captured Payment rows,
    never messages or promises."""
    from sqlalchemy import select

    from app.models.payment import Payment
    from app.models.recovery_case import RecoveryCase

    run_simulation(db_session)

    cases = list(db_session.execute(select(RecoveryCase)).scalars().all())
    payments = list(db_session.execute(select(Payment)).scalars().all())
    captured = [p for p in payments if p.status == "captured"]
    captured_by_case = {}
    for p in captured:
        captured_by_case[p.recovery_case_id] = (
            captured_by_case.get(p.recovery_case_id, 0) + p.amount
        )
    # Every captured payment belongs to a demo case
    assert len(captured) > 0

    analytics = _compute_simulation_analytics(db_session)
    expected = sum(captured_by_case.values())
    assert analytics["recovered_revenue"] == expected
    assert analytics["metrics"]["recovered_revenue"] == expected

    # Financial summary buckets partition the original revenue exactly.
    summary = analytics["financial_summary"]
    total_original = analytics["total_original_revenue"]
    assert (
        summary["recovered"]
        + summary["partially_recovered"]
        + summary["at_risk"]
        + summary["lost"]
        == total_original
    )


def test_promise_to_pay_is_not_recovered_money(db_session):
    """A promise message must NOT be recorded as a payment or counted as
    recovered revenue (user's hard rule)."""
    from sqlalchemy import select

    from app.models.payment import Payment
    from app.models.recovery_case import RecoveryCase

    run_simulation(db_session)

    analytics = _compute_simulation_analytics(db_session)
    assert analytics["status_breakdown"]["promised"] == SCENARIOS["promise_to_pay"]

    # Promised cases have NO captured payments backing them.
    cases = {
        c.id: c for c in db_session.execute(select(RecoveryCase)).scalars().all()
    }
    case_sim = {
        c.id: (c.extra_data or {}).get("scenario")
        for c in cases.values()
    }
    promised_ids = [cid for cid, sc in case_sim.items() if sc == "promise_to_pay"]
    assert len(promised_ids) == SCENARIOS["promise_to_pay"]

    payments = list(db_session.execute(select(Payment)).scalars().all())
    promised_payments = [
        p for p in payments if p.recovery_case_id in promised_ids
    ]
    assert promised_payments == []

    # Promised money is at risk, not recovered.
    assert analytics["promised_revenue"] > 0
    promised_sum = sum(cases[cid].original_amount for cid in promised_ids)
    assert analytics["promised_revenue"] == promised_sum


def test_payment_plan_installments_created(db_session):
    from sqlalchemy import select

    from app.models.installment import Installment
    from app.models.payment_plan import PaymentPlan

    run_simulation(db_session)

    plans = list(db_session.execute(select(PaymentPlan)).scalars().all())
    installments = list(db_session.execute(select(Installment)).scalars().all())

    assert len(plans) == SCENARIOS["payment_plan_request"] + SCENARIOS["plan_partial"]
    assert len(installments) > 0
    # plan scenarios schedule money without counting it as paid
    paid_inst = [i for i in installments if i.status == "PAID"]
    unpaid_inst = [i for i in installments if i.status == "SCHEDULED"]
    assert paid_inst and unpaid_inst

    analytics = _compute_simulation_analytics(db_session)
    assert analytics["payment_plans_count"] == len(plans)


def test_simulation_is_idempotent_no_duplicate_keys(db_session):
    """Re-running must clean previous demo data (regression: duplicate
    external_id unique-constraint crash from stale data)."""
    run_simulation(db_session)
    results = run_simulation(db_session)

    assert results["total_transactions"] == sum(SCENARIOS.values())
    assert results["cleaned_up"] == sum(SCENARIOS.values())

    analytics = _compute_simulation_analytics(db_session)
    assert analytics["total_transactions"] == sum(SCENARIOS.values())


def test_reset_logic_cleans_demo_data(db_session):
    from app.routes.simulation import reset_simulation_data

    run_simulation(db_session)

    result = reset_simulation_data(db_session)
    assert result["status"] == "reset"
    assert result["deleted"]["customers"] >= 100
    assert result["deleted"]["payments"] > 0
    assert result["deleted"]["plans"] > 0

    analytics = _compute_simulation_analytics(db_session)
    assert "error" in analytics