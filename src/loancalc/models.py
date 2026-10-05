"""Core data structures for loans, payment allocations, and simulated schedules.

Money is tracked as floats rounded to cents at every payment boundary; interest
accrual keeps extra precision until it is paid so long horizons do not drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

#: Balances below this are treated as paid off (sub-cent rounding dust).
EPSILON = 0.005

DAYS_PER_YEAR = 365.0


def money(value: float) -> float:
    """Round to cents, collapsing rounding dust to a clean zero."""
    rounded = round(value, 2)
    return 0.0 if abs(rounded) < EPSILON else rounded


@dataclass(slots=True)
class Loan:
    """A single tradeline with its own rate, minimum, and accrued interest."""

    name: str
    principal: float
    annual_rate: float
    minimum_payment: float
    loan_id: int | None = None
    accrued_interest: float = 0.0
    servicer: str = ""
    sort_order: int = 0

    @property
    def payoff_amount(self) -> float:
        """Cash needed today to close the loan: principal plus unpaid interest."""
        return money(self.principal + self.accrued_interest)

    @property
    def is_open(self) -> bool:
        return self.payoff_amount > EPSILON

    @property
    def daily_interest(self) -> float:
        return self.principal * self.annual_rate / DAYS_PER_YEAR

    def copy(self) -> Loan:
        return replace(self)

    def accrue(self, days: int) -> float:
        """Add simple daily interest for `days` and return the amount charged."""
        if not self.is_open or days <= 0:
            return 0.0
        charged = self.principal * self.annual_rate * days / DAYS_PER_YEAR
        self.accrued_interest += charged
        return charged

    def apply_payment(self, amount: float) -> tuple[float, float]:
        """Pay interest first, then principal. Returns (interest, principal) paid."""
        amount = min(money(amount), self.payoff_amount)
        if amount <= 0:
            return 0.0, 0.0
        interest_paid = min(self.accrued_interest, amount)
        self.accrued_interest -= interest_paid
        principal_paid = amount - interest_paid
        self.principal -= principal_paid
        if self.principal < EPSILON:
            self.principal = 0.0
        if self.accrued_interest < EPSILON:
            self.accrued_interest = 0.0
        return interest_paid, principal_paid


@dataclass(slots=True)
class Allocation:
    """How one month's capital landed on one loan."""

    loan_id: int | None
    loan_name: str
    amount: float
    minimum_portion: float
    extra_portion: float
    interest_portion: float
    principal_portion: float
    remaining_balance: float

    @property
    def is_payoff(self) -> bool:
        return self.remaining_balance <= EPSILON


@dataclass(slots=True)
class MonthResult:
    """One simulated (or logged) monthly cycle."""

    period: date
    starting_balance: float
    interest_charged: float
    total_paid: float
    interest_paid: float
    principal_paid: float
    ending_balance: float
    allocations: list[Allocation] = field(default_factory=list)
    shortfall: float = 0.0
    balances: dict[str, float] = field(default_factory=dict)

    @property
    def loans_closed(self) -> list[str]:
        return [a.loan_name for a in self.allocations if a.is_payoff and a.amount > 0]


@dataclass(slots=True)
class Schedule:
    """The full payoff forecast produced by the engine."""

    months: list[MonthResult]
    strategy: str
    monthly_budget: float
    starting_balance: float
    total_paid: float
    total_interest: float
    total_principal: float
    payoff_date: date | None
    months_to_payoff: int
    completed: bool
    loan_names: list[str] = field(default_factory=list)

    @property
    def years_to_payoff(self) -> float:
        return self.months_to_payoff / 12.0

    def balance_series(self) -> tuple[list[date], dict[str, list[float]]]:
        """Per-loan ending balances over time, ready for a stacked area chart."""
        periods = [m.period for m in self.months]
        series = {name: [m.balances.get(name, 0.0) for m in self.months] for name in self.loan_names}
        return periods, series


@dataclass(slots=True)
class PaymentRecord:
    """A payment the user actually made, as logged in the Action Center."""

    period: date
    paid_on: date
    total_amount: float
    interest_paid: float
    principal_paid: float
    allocations: list[Allocation] = field(default_factory=list)
    note: str = ""
    payment_id: int | None = None


@dataclass(slots=True)
class Baseline:
    """The original plan, kept so deviations can be scored against it."""

    captured_on: date
    monthly_budget: float
    strategy: str
    total_interest: float
    payoff_date: date | None
    starting_balance: float


@dataclass(slots=True)
class Scenario:
    """A what-if plan: a base monthly payment plus pinned one-off months."""

    name: str
    monthly_budget: float
    strategy: str = "avalanche"
    overrides: dict[date, float] = field(default_factory=dict)
    notes: dict[date, str] = field(default_factory=dict)
    scenario_id: int | None = None
    created_on: date = field(default_factory=date.today)

    def payment_for(self, period: date) -> float:
        return self.overrides.get(period, self.monthly_budget)

    def is_pinned(self, period: date) -> bool:
        return period in self.overrides

    def pin(self, period: date, amount: float, note: str = "") -> None:
        self.overrides[period] = money(amount)
        if note:
            self.notes[period] = note
        else:
            self.notes.pop(period, None)

    def unpin(self, period: date) -> None:
        self.overrides.pop(period, None)
        self.notes.pop(period, None)

    def copy(self, name: str) -> Scenario:
        return Scenario(
            name=name,
            monthly_budget=self.monthly_budget,
            strategy=self.strategy,
            overrides=dict(self.overrides),
            notes=dict(self.notes),
        )
