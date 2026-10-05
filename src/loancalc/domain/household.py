"""Household engine: every active plan simulated together on one calendar.

Each plan pays its own loans from its own budget with its own strategy. When a
plan is fully paid off and has `rollover` enabled, its budget is not lost — it
is freed and redirected to the plans still carrying debt:

* ``avalanche`` — freed cash chases the highest-rate loan anywhere in the
  household (mathematically cheapest), or
* ``plan_order`` — freed cash goes to the next plan in your priority order and
  is spent using that plan's own strategy.

Running the same inputs with ``rollover=False`` gives the "isolated" picture,
so the difference between the two is exactly how the plans help each other.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from loancalc.domain.engine import MAX_MONTHS, apply_month
from loancalc.domain.models import AVALANCHE, EPSILON, Loan, Plan, money
from loancalc.domain.periods import add_months, month_end, period_of

PLAN_ORDER = "plan_order"

ROLLOVER_LABELS = {
    AVALANCHE: "Highest rate anywhere in the household",
    PLAN_ORDER: "Next plan in priority order",
}


@dataclass(slots=True)
class PlanInput:
    plan: Plan
    loans: list[Loan]
    #: Optional month-by-month payment (e.g. first month net of logged payments).
    payment_for: Callable[[date], float] | None = None


@dataclass(slots=True)
class PlanOutcome:
    plan: Plan
    starting_balance: float
    balances: list[float] = field(default_factory=list)
    paid: list[float] = field(default_factory=list)
    total_paid: float = 0.0
    total_interest: float = 0.0
    total_fees: float = 0.0
    rolled_in: float = 0.0
    rolled_out: float = 0.0
    payoff_date: date | None = None
    months_to_payoff: int = 0

    @property
    def completed(self) -> bool:
        return self.payoff_date is not None or self.starting_balance <= EPSILON


@dataclass(slots=True)
class HouseholdMonth:
    period: date
    starting_balance: float
    ending_balance: float
    total_paid: float
    interest_paid: float
    principal_paid: float
    fees_paid: float
    rolled: float
    plan_balances: dict[int, float]
    plans_completed: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HouseholdSchedule:
    months: list[HouseholdMonth]
    outcomes: dict[int, PlanOutcome]
    rollover: bool
    rollover_strategy: str
    starting_balance: float
    monthly_commitment: float
    total_paid: float = 0.0
    total_interest: float = 0.0
    total_fees: float = 0.0
    payoff_date: date | None = None
    months_to_payoff: int = 0
    completed: bool = False

    @property
    def total_cost(self) -> float:
        return money(self.total_interest + self.total_fees)

    @property
    def total_rolled(self) -> float:
        return money(sum(month.rolled for month in self.months))


def simulate_household(
    inputs: Sequence[PlanInput],
    *,
    start_period: date | None = None,
    rollover: bool = True,
    rollover_strategy: str = AVALANCHE,
    max_months: int = MAX_MONTHS,
) -> HouseholdSchedule:
    period = period_of(start_period or date.today())
    working: dict[int, list[Loan]] = {}
    owners: dict[int, int] = {}
    plans: dict[int, Plan] = {}
    for index, item in enumerate(inputs):
        key = item.plan.plan_id if item.plan.plan_id is not None else -(index + 1)
        plans[key] = item.plan
        working[key] = [loan.copy() for loan in item.loans]
        for loan in working[key]:
            owners[id(loan)] = key
    payment_fns = {
        key: item.payment_for for key, item in zip(plans, inputs, strict=True)
    }

    outcomes = {
        key: PlanOutcome(plan=plans[key], starting_balance=_balance(working[key]))
        for key in plans
    }
    schedule = HouseholdSchedule(
        months=[],
        outcomes=outcomes,
        rollover=rollover,
        rollover_strategy=rollover_strategy,
        starting_balance=money(sum(o.starting_balance for o in outcomes.values())),
        monthly_commitment=money(sum(plan.monthly_budget for plan in plans.values())),
    )
    if schedule.starting_balance <= EPSILON:
        schedule.completed = True
        return schedule

    stalled = 0
    for index in range(max_months):
        starting = money(sum(_balance(loans) for loans in working.values()))
        paid_by_plan = dict.fromkeys(plans, 0.0)
        interest = principal = fees = 0.0
        freed = 0.0

        for key, plan in plans.items():
            loans = working[key]
            fn = payment_fns[key]
            budget = fn(period) if fn else plan.monthly_budget
            if not any(loan.is_open for loan in loans):
                if rollover and plan.rollover:
                    freed += budget
                    outcomes[key].rolled_out += budget
                continue
            result = apply_month(loans, budget, period, strategy=plan.strategy)
            paid_by_plan[key] += result.total_paid
            interest += result.interest_paid
            principal += result.principal_paid
            fees += result.fees_paid
            outcomes[key].total_fees += result.fees_paid
            outcomes[key].total_interest += result.interest_paid
            leftover = money(budget - result.total_paid)
            if leftover > 0 and rollover and plan.rollover:
                freed += leftover
                outcomes[key].rolled_out += leftover

        rolled = 0.0
        if freed > EPSILON:
            rolled, extra_interest, extra_principal = _place_rollover(
                freed, period, plans, working, owners, outcomes, paid_by_plan, rollover_strategy
            )
            interest += extra_interest
            principal += extra_principal

        balances = {key: _balance(loans) for key, loans in working.items()}
        completed_now: list[str] = []
        for key, outcome in outcomes.items():
            outcome.balances.append(balances[key])
            outcome.paid.append(money(paid_by_plan[key]))
            outcome.total_paid += paid_by_plan[key]
            if outcome.payoff_date is None and outcome.starting_balance > EPSILON and balances[key] <= EPSILON:
                outcome.payoff_date = month_end(period)
                outcome.months_to_payoff = index + 1
                completed_now.append(plans[key].name)

        ending = money(sum(balances.values()))
        schedule.months.append(
            HouseholdMonth(
                period=period,
                starting_balance=starting,
                ending_balance=ending,
                total_paid=money(sum(paid_by_plan.values())),
                interest_paid=money(interest),
                principal_paid=money(principal),
                fees_paid=money(fees),
                rolled=money(rolled),
                plan_balances=balances,
                plans_completed=completed_now,
            )
        )

        if ending <= EPSILON:
            schedule.payoff_date = month_end(period)
            schedule.completed = True
            break
        stalled = stalled + 1 if ending >= starting else 0
        if stalled > 3:
            break
        period = add_months(period, 1)

    for outcome in outcomes.values():
        outcome.total_paid = money(outcome.total_paid)
        outcome.total_interest = money(outcome.total_interest)
        outcome.total_fees = money(outcome.total_fees)
        outcome.rolled_in = money(outcome.rolled_in)
        outcome.rolled_out = money(outcome.rolled_out)

    schedule.months_to_payoff = len(schedule.months)
    schedule.total_paid = money(sum(m.total_paid for m in schedule.months))
    schedule.total_interest = money(sum(m.interest_paid for m in schedule.months))
    schedule.total_fees = money(sum(m.fees_paid for m in schedule.months))
    return schedule


def _balance(loans: Sequence[Loan]) -> float:
    return money(sum(loan.payoff_amount for loan in loans))


def _place_rollover(
    freed: float,
    period: date,
    plans: dict[int, Plan],
    working: dict[int, list[Loan]],
    owners: dict[int, int],
    outcomes: dict[int, PlanOutcome],
    paid_by_plan: dict[int, float],
    strategy: str,
) -> tuple[float, float, float]:
    """Spend freed budget on the remaining plans. Returns (placed, interest, principal)."""
    receivers = [
        key for key, plan in plans.items()
        if plan.accepts_rollover and any(loan.is_open for loan in working[key])
    ]
    if not receivers:
        return 0.0, 0.0, 0.0

    if strategy == PLAN_ORDER:
        batches = [(working[key], plans[key].strategy) for key in receivers]
    else:
        pooled = [loan for key in receivers for loan in working[key]]
        batches = [(pooled, AVALANCHE)]

    placed = interest = principal = 0.0
    remaining = freed
    for loans, plan_strategy in batches:
        if remaining <= EPSILON:
            break
        result = apply_month(
            loans, remaining, period,
            strategy=plan_strategy, cover_minimums=False, charge_fees=False,
        )
        for loan, allocation in zip(loans, result.allocations, strict=True):
            if allocation.amount > 0:
                key = owners[id(loan)]
                paid_by_plan[key] += allocation.amount
                outcomes[key].rolled_in += allocation.amount
                outcomes[key].total_interest += allocation.interest_portion
        placed += result.total_paid
        interest += result.interest_paid
        principal += result.principal_paid
        remaining = money(remaining - result.total_paid)
    return money(placed), interest, principal
