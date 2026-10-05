"""Repayment engine: daily interest accrual plus avalanche/snowball allocation.

One pass per calendar month:
  1. accrue simple daily interest on every open loan,
  2. cover every minimum payment,
  3. funnel 100% of what is left onto the single highest-priority loan,
     rolling any overflow to the next one the moment a loan is retired.
"""
from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from loancalc.models import EPSILON, Allocation, Loan, MonthResult, Schedule, money

AVALANCHE = "avalanche"
SNOWBALL = "snowball"
HIGHEST_BALANCE = "highest_balance"

STRATEGY_LABELS = {
    AVALANCHE: "Avalanche (highest interest rate first)",
    SNOWBALL: "Snowball (smallest balance first)",
    HIGHEST_BALANCE: "Highest balance first",
}

#: Hard stop so a budget that cannot outrun interest never loops forever.
MAX_MONTHS = 720


class EngineError(RuntimeError):
    """Raised when a simulation cannot produce a meaningful result."""


def period_of(day: date) -> date:
    """Normalise any date to the first of its month."""
    return day.replace(day=1)


def add_months(period: date, count: int) -> date:
    total = (period.year * 12 + period.month - 1) + count
    return date(total // 12, total % 12 + 1, 1)


def days_in_period(period: date) -> int:
    return calendar.monthrange(period.year, period.month)[1]


def priority_order(loans: Iterable[Loan], strategy: str) -> list[Loan]:
    """Sort open loans by payoff priority; ties break on the larger balance."""
    open_loans = [loan for loan in loans if loan.is_open]
    if strategy == SNOWBALL:
        key = lambda loan: (loan.payoff_amount, -loan.annual_rate)  # noqa: E731
    elif strategy == HIGHEST_BALANCE:
        key = lambda loan: (-loan.payoff_amount, -loan.annual_rate)  # noqa: E731
    else:
        key = lambda loan: (-loan.annual_rate, -loan.payoff_amount)  # noqa: E731
    return sorted(open_loans, key=key)


def apply_month(
    loans: Sequence[Loan],
    budget: float,
    period: date,
    *,
    strategy: str = AVALANCHE,
    accrue: bool = True,
) -> MonthResult:
    """Run one monthly cycle **in place** against `loans` and report the result.

    Callers that only want a preview should pass copies (see `preview_month`).
    """
    starting_balance = money(sum(loan.payoff_amount for loan in loans))
    days = days_in_period(period)

    interest_charged = 0.0
    if accrue:
        for loan in loans:
            interest_charged += loan.accrue(days)

    ranked = priority_order(loans, strategy)
    paid: dict[int, list[float]] = {id(loan): [0.0, 0.0, 0.0, 0.0] for loan in loans}
    remaining = money(max(budget, 0.0))

    # Pass 1 - minimums, in priority order so a short month still protects the
    # most expensive debt first.
    required_minimums = 0.0
    for loan in ranked:
        due = min(loan.minimum_payment, loan.payoff_amount)
        required_minimums += due
        if remaining <= 0:
            continue
        payment = money(min(due, remaining))
        if payment <= 0:
            continue
        interest, principal = loan.apply_payment(payment)
        bucket = paid[id(loan)]
        bucket[0] += payment
        bucket[1] += payment
        bucket[2] += interest
        bucket[3] += principal
        remaining = money(remaining - payment)

    shortfall = money(max(required_minimums - money(max(budget, 0.0)), 0.0))

    # Pass 2 - the avalanche: everything left goes to the top-ranked open loan,
    # cascading onward each time one is retired.
    for loan in priority_order(loans, strategy):
        if remaining <= EPSILON:
            break
        payment = money(min(loan.payoff_amount, remaining))
        if payment <= 0:
            continue
        interest, principal = loan.apply_payment(payment)
        bucket = paid[id(loan)]
        bucket[0] += payment
        bucket[2] += interest
        bucket[3] += principal
        remaining = money(remaining - payment)

    allocations = [
        Allocation(
            loan_id=loan.loan_id,
            loan_name=loan.name,
            amount=money(paid[id(loan)][0]),
            minimum_portion=money(paid[id(loan)][1]),
            extra_portion=money(paid[id(loan)][0] - paid[id(loan)][1]),
            interest_portion=money(paid[id(loan)][2]),
            principal_portion=money(paid[id(loan)][3]),
            remaining_balance=loan.payoff_amount,
        )
        for loan in loans
    ]

    total_paid = money(sum(a.amount for a in allocations))
    return MonthResult(
        period=period,
        starting_balance=starting_balance,
        interest_charged=money(interest_charged),
        total_paid=total_paid,
        interest_paid=money(sum(a.interest_portion for a in allocations)),
        principal_paid=money(sum(a.principal_portion for a in allocations)),
        ending_balance=money(sum(loan.payoff_amount for loan in loans)),
        allocations=allocations,
        shortfall=shortfall,
        balances={loan.name: loan.payoff_amount for loan in loans},
    )


def preview_month(
    loans: Sequence[Loan],
    budget: float,
    period: date,
    *,
    strategy: str = AVALANCHE,
    accrue: bool = True,
) -> tuple[MonthResult, list[Loan]]:
    """Non-destructive `apply_month`; returns the result and the updated copies."""
    working = [loan.copy() for loan in loans]
    result = apply_month(working, budget, period, strategy=strategy, accrue=accrue)
    return result, working


def simulate(
    loans: Sequence[Loan],
    monthly_budget: float,
    *,
    start_period: date | None = None,
    strategy: str = AVALANCHE,
    first_month_budget: float | None = None,
    overrides: Mapping[date, float] | None = None,
    skip_first_accrual: bool = False,
    max_months: int = MAX_MONTHS,
) -> Schedule:
    """Project the full payoff timeline from today's balances forward.

    `overrides` pins specific months to an exact payment (a tax refund, a lean
    month); every other month uses `monthly_budget`.
    """
    working = [loan.copy() for loan in loans]
    starting_balance = money(sum(loan.payoff_amount for loan in working))
    period = period_of(start_period or date.today())

    schedule = Schedule(
        months=[],
        strategy=strategy,
        monthly_budget=money(monthly_budget),
        starting_balance=starting_balance,
        total_paid=0.0,
        total_interest=0.0,
        total_principal=0.0,
        payoff_date=None,
        months_to_payoff=0,
        completed=starting_balance <= EPSILON,
        loan_names=[loan.name for loan in working],
    )
    if schedule.completed:
        return schedule

    months: list[MonthResult] = []
    for index in range(max_months):
        budget = monthly_budget
        if index == 0 and first_month_budget is not None:
            budget = first_month_budget
        if overrides and period in overrides:
            budget = overrides[period]
        result = apply_month(
            working,
            budget,
            period,
            strategy=strategy,
            accrue=not (index == 0 and skip_first_accrual),
        )
        months.append(result)

        if result.ending_balance <= EPSILON:
            schedule.payoff_date = date(period.year, period.month, days_in_period(period))
            schedule.completed = True
            break
        # Negative amortisation: the plan can never finish, so stop early rather
        # than grinding to the month cap.
        if result.ending_balance >= result.starting_balance and result.total_paid > 0:
            if index > 2:
                break
        period = add_months(period, 1)

    schedule.months = months
    schedule.months_to_payoff = len(months)
    schedule.total_paid = money(sum(m.total_paid for m in months))
    schedule.total_interest = money(sum(m.interest_paid for m in months))
    schedule.total_principal = money(sum(m.principal_paid for m in months))
    return schedule


def minimum_only_schedule(
    loans: Sequence[Loan], *, start_period: date | None = None, strategy: str = AVALANCHE
) -> Schedule:
    """Forecast if the user only ever pays the contractual minimums."""
    total_minimum = sum(loan.minimum_payment for loan in loans if loan.is_open)
    return simulate(loans, total_minimum, start_period=start_period, strategy=strategy)


def total_minimum_payment(loans: Iterable[Loan]) -> float:
    return money(sum(loan.minimum_payment for loan in loans if loan.is_open))


def total_balance(loans: Iterable[Loan]) -> float:
    return money(sum(loan.payoff_amount for loan in loans))


def weighted_average_rate(loans: Iterable[Loan]) -> float:
    open_loans = [loan for loan in loans if loan.is_open]
    balance = sum(loan.payoff_amount for loan in open_loans)
    if balance <= EPSILON:
        return 0.0
    return sum(loan.payoff_amount * loan.annual_rate for loan in open_loans) / balance


def daily_interest_cost(loans: Iterable[Loan]) -> float:
    return money(sum(loan.daily_interest for loan in loans if loan.is_open))
