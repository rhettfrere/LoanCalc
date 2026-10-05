"""Single-plan repayment engine.

One pass per calendar month:
  1. accrue interest on every open loan using that loan's own method
     (simple daily, monthly amortised, or daily compounding),
  2. cover every contractual minimum in priority order,
  3. funnel 100% of what is left onto the highest-priority loan, cascading
     to the next one the moment a loan is retired.

PMI is charged while a mortgage stays above 78% LTV; it is reported as a cost
but paid outside the budget, exactly like a real servicer statement.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import date

from loancalc.domain.models import (
    AVALANCHE,
    EPSILON,
    Allocation,
    Loan,
    MonthResult,
    Schedule,
    money,
)
from loancalc.domain.periods import add_months, month_end, period_of

SNOWBALL = "snowball"
HIGHEST_BALANCE = "highest_balance"

STRATEGY_LABELS = {
    AVALANCHE: "Avalanche (highest interest rate first)",
    SNOWBALL: "Snowball (smallest balance first)",
    HIGHEST_BALANCE: "Highest balance first",
}

#: Hard stop so a budget that cannot outrun interest never loops forever.
MAX_MONTHS = 720

PaymentFn = Callable[[date], float]


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
    cover_minimums: bool = True,
    charge_fees: bool = True,
) -> MonthResult:
    """Run one monthly cycle **in place** against `loans` and report the result.

    Accrual is idempotent per loan and period, so this can be called again in
    the same month (e.g. a household rollover pass) with `cover_minimums=False`
    to place extra capital without double-charging interest.
    """
    starting_balance = money(sum(loan.payoff_amount for loan in loans))
    interest_charged = sum(loan.accrue(period) for loan in loans)

    fees = escrow = 0.0
    if charge_fees:
        for loan in loans:
            if loan.is_open:
                escrow += loan.escrow_monthly
                if loan.pmi_active:
                    fees += loan.pmi_monthly

    paid: dict[int, list[float]] = {id(loan): [0.0, 0.0, 0.0, 0.0] for loan in loans}
    remaining = money(max(budget, 0.0))

    def pay(loan: Loan, amount: float, *, minimum: bool) -> float:
        amount = money(min(amount, loan.payoff_amount))
        if amount <= 0:
            return 0.0
        interest, principal = loan.apply_payment(amount)
        bucket = paid[id(loan)]
        bucket[0] += amount
        if minimum:
            bucket[1] += amount
        bucket[2] += interest
        bucket[3] += principal
        return amount

    # Pass 1 — minimums, in priority order so a short month still protects the
    # most expensive debt first.
    required = 0.0
    if cover_minimums:
        for loan in priority_order(loans, strategy):
            due = min(loan.effective_minimum, loan.payoff_amount)
            required += due
            if remaining > 0:
                remaining = money(remaining - pay(loan, min(due, remaining), minimum=True))

    shortfall = money(max(required - money(max(budget, 0.0)), 0.0))

    # Pass 2 — everything left goes to the top-ranked open loan, cascading
    # onward each time one is retired.
    for loan in priority_order(loans, strategy):
        if remaining <= EPSILON:
            break
        remaining = money(remaining - pay(loan, remaining, minimum=False))

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

    return MonthResult(
        period=period,
        starting_balance=starting_balance,
        interest_charged=money(interest_charged),
        total_paid=money(sum(a.amount for a in allocations)),
        interest_paid=money(sum(a.interest_portion for a in allocations)),
        principal_paid=money(sum(a.principal_portion for a in allocations)),
        ending_balance=money(sum(loan.payoff_amount for loan in loans)),
        allocations=allocations,
        shortfall=shortfall,
        balances={loan.name: loan.payoff_amount for loan in loans},
        fees_paid=money(fees),
        escrow_paid=money(escrow),
    )


def preview_month(
    loans: Sequence[Loan],
    budget: float,
    period: date,
    *,
    strategy: str = AVALANCHE,
) -> tuple[MonthResult, list[Loan]]:
    """Non-destructive `apply_month`; returns the result and the updated copies."""
    working = [loan.copy() for loan in loans]
    result = apply_month(working, budget, period, strategy=strategy)
    return result, working


def simulate(
    loans: Sequence[Loan],
    monthly_budget: float,
    *,
    start_period: date | None = None,
    strategy: str = AVALANCHE,
    first_month_budget: float | None = None,
    payment_for: PaymentFn | None = None,
    max_months: int = MAX_MONTHS,
) -> Schedule:
    """Project the full payoff timeline from today's balances forward.

    `payment_for(period)` lets a scenario vary the payment month to month;
    otherwise every month uses `monthly_budget`.
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

    pmi_watch = {loan.name for loan in working if loan.pmi_active}
    months: list[MonthResult] = []
    for index in range(max_months):
        budget = payment_for(period) if payment_for else monthly_budget
        if index == 0 and first_month_budget is not None:
            budget = first_month_budget
        result = apply_month(working, budget, period, strategy=strategy)
        months.append(result)

        for loan in working:
            if loan.name in pmi_watch and not loan.pmi_active:
                schedule.pmi_ends[loan.name] = add_months(period, 1)
                pmi_watch.discard(loan.name)

        if result.ending_balance <= EPSILON:
            schedule.payoff_date = month_end(period)
            schedule.completed = True
            break
        # Negative amortisation: the plan can never finish, so stop early rather
        # than grinding to the month cap.
        if index > 2 and result.ending_balance >= result.starting_balance and result.total_paid > 0:
            break
        period = add_months(period, 1)

    schedule.months = months
    schedule.months_to_payoff = len(months)
    schedule.total_paid = money(sum(m.total_paid for m in months))
    schedule.total_interest = money(sum(m.interest_paid for m in months))
    schedule.total_principal = money(sum(m.principal_paid for m in months))
    schedule.total_fees = money(sum(m.fees_paid for m in months))
    return schedule


def minimum_only_schedule(
    loans: Sequence[Loan], *, start_period: date | None = None, strategy: str = AVALANCHE
) -> Schedule:
    """Forecast if the user only ever pays the contractual minimums."""
    return simulate(
        loans, total_minimum_payment(loans), start_period=start_period, strategy=strategy
    )


def total_minimum_payment(loans: Iterable[Loan]) -> float:
    return money(sum(loan.effective_minimum for loan in loans if loan.is_open))


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
