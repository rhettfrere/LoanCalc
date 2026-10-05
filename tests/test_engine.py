from __future__ import annotations

import pytest

from loancalc.domain import engine
from loancalc.domain.loan_types import LoanType
from loancalc.domain.models import Loan
from tests.conftest import START


def test_avalanche_sends_extra_to_highest_rate(student_loans):
    result = engine.apply_month(student_loans, 1_000, START)
    by_name = {a.loan_name: a for a in result.allocations}
    assert by_name["High"].extra_portion == pytest.approx(1_000 - 275)
    assert by_name["Mid"].extra_portion == 0
    assert all(a.minimum_portion > 0 for a in result.allocations)


def test_short_budget_reports_shortfall(student_loans):
    result = engine.apply_month(student_loans, 200, START)
    assert result.shortfall == pytest.approx(75)
    assert result.total_paid == pytest.approx(200)


def test_accrual_is_idempotent_within_a_month(student_loans):
    loan = student_loans[0]
    first = loan.accrue(START)
    assert first > 0
    assert loan.accrue(START) == 0


def test_accrual_catches_up_skipped_months():
    loan = Loan("Gap", 10_000, 0.06, 100, accrued_through=START)
    from loancalc.domain.periods import add_months

    charged = loan.accrue(add_months(START, 2))
    assert charged == pytest.approx(10_000 * 0.06 * (30 + 31) / 365, rel=1e-6)


def test_mortgage_uses_monthly_interest(mortgage):
    result = engine.apply_month([mortgage], mortgage.effective_minimum, START)
    assert result.interest_charged == pytest.approx(280_000 * 0.065 / 12, abs=0.01)
    assert result.escrow_paid == 450
    assert result.fees_paid == 140


def test_credit_card_compounds_daily():
    card = Loan("Card", 1_000, 0.24, 50, loan_type=LoanType.CREDIT_CARD)
    charged = card.accrue(START)
    assert charged == pytest.approx(1_000 * ((1 + 0.24 / 365) ** 31 - 1), rel=1e-9)
    assert charged > 1_000 * 0.24 * 31 / 365


def test_prepaying_mortgage_ends_pmi_sooner(mortgage):
    base = engine.minimum_only_schedule([mortgage], start_period=START)
    fast = engine.simulate([mortgage], mortgage.effective_minimum + 500, start_period=START)
    assert fast.pmi_ends["Home"] < base.pmi_ends["Home"]
    assert fast.total_fees < base.total_fees
    assert fast.months_to_payoff < base.months_to_payoff


def test_minimum_derived_from_term(auto_loan):
    schedule = engine.minimum_only_schedule([auto_loan], start_period=START)
    assert schedule.completed
    assert abs(schedule.months_to_payoff - 60) <= 1


def test_simulation_conserves_principal(student_loans):
    schedule = engine.simulate(student_loans, 1_500, start_period=START)
    assert schedule.completed
    assert schedule.total_principal == pytest.approx(23_000, abs=0.05)
    assert schedule.total_paid == pytest.approx(schedule.total_principal + schedule.total_interest, abs=0.05)


def test_payment_function_overrides_months(student_loans):
    flat = engine.simulate(student_loans, 1_000, start_period=START)
    boosted = engine.simulate(
        student_loans, 1_000, start_period=START,
        payment_for=lambda p: 6_000 if p == START else 1_000,
    )
    assert boosted.total_interest < flat.total_interest
    assert boosted.months[0].total_paid == pytest.approx(6_000)


def test_unpayable_plan_stops_early():
    loan = Loan("Hopeless", 50_000, 0.25, 100, loan_type=LoanType.CREDIT_CARD)
    schedule = engine.simulate([loan], 100, start_period=START)
    assert not schedule.completed
    assert schedule.months_to_payoff < 12
