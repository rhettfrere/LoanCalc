from __future__ import annotations

import pytest

from loancalc.domain import engine
from loancalc.domain.household import PLAN_ORDER, PlanInput, simulate_household
from loancalc.domain.models import Plan
from tests.conftest import START


@pytest.fixture
def inputs(student_loans, mortgage, auto_loan):
    return [
        PlanInput(Plan("Student", 2_500, plan_id=1), student_loans),
        PlanInput(Plan("Auto", auto_loan.effective_minimum, plan_id=2), [auto_loan]),
        PlanInput(Plan("Mortgage", mortgage.effective_minimum, plan_id=3), [mortgage]),
    ]


def test_isolated_household_matches_each_plan_alone(inputs):
    household = simulate_household(inputs, start_period=START, rollover=False)
    for item in inputs:
        alone = engine.simulate(item.loans, item.plan.monthly_budget, start_period=START)
        outcome = household.outcomes[item.plan.plan_id]
        assert outcome.payoff_date == alone.payoff_date
        assert outcome.total_interest == pytest.approx(alone.total_interest, abs=0.05)
    assert household.total_rolled == 0


def test_rollover_is_never_worse(inputs):
    isolated = simulate_household(inputs, start_period=START, rollover=False)
    rolled = simulate_household(inputs, start_period=START, rollover=True)
    assert rolled.total_cost < isolated.total_cost
    assert rolled.payoff_date < isolated.payoff_date
    assert rolled.outcomes[3].rolled_in > 0
    assert rolled.outcomes[1].rolled_out > 0


def test_rolled_money_is_conserved(inputs):
    rolled = simulate_household(inputs, start_period=START, rollover=True)
    given = sum(o.rolled_out for o in rolled.outcomes.values())
    received = sum(o.rolled_in for o in rolled.outcomes.values())
    # The final month can free money with nowhere left to go.
    assert received <= given + 0.01
    assert received == pytest.approx(rolled.total_rolled, abs=0.05)


def test_opting_out_of_receiving(inputs):
    inputs[2].plan.accepts_rollover = False
    rolled = simulate_household(inputs, start_period=START, rollover=True)
    assert rolled.outcomes[3].rolled_in == 0


def test_plan_order_feeds_next_plan_first(inputs):
    rolled = simulate_household(inputs, start_period=START, rollover=True, rollover_strategy=PLAN_ORDER)
    student_done = rolled.outcomes[1].payoff_date
    first_roll = next(m for m in rolled.months if m.rolled > 0)
    assert first_roll.period <= student_done
    assert rolled.outcomes[2].rolled_in > 0
