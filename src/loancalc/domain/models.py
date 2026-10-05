"""Core data structures: loans, plans, pins, scenarios and simulated schedules.

Money is rounded to cents at every payment boundary; interest accrual keeps
extra precision until it is paid so long horizons do not drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum

from loancalc.domain import amortization
from loancalc.domain.loan_types import InterestMethod, LoanType, LoanTypeSpec, spec
from loancalc.domain.periods import add_months, days_in_period

#: Balances below this are treated as paid off (sub-cent rounding dust).
EPSILON = 0.005

DAYS_PER_YEAR = 365.0

AVALANCHE = "avalanche"


def money(value: float) -> float:
    """Round to cents, collapsing rounding dust to a clean zero."""
    rounded = round(value, 2)
    return 0.0 if abs(rounded) < EPSILON else rounded


# --------------------------------------------------------------------------- #
# Loans
# --------------------------------------------------------------------------- #
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
    loan_type: LoanType = LoanType.STUDENT
    plan_id: int | None = None
    #: None means "use the loan type's default".
    interest_method: InterestMethod | None = None
    #: Remaining months on the contract; 0 for open-ended debt.
    term_months: int = 0
    #: Mortgage taxes + insurance collected by the servicer (never reduces debt).
    escrow_monthly: float = 0.0
    pmi_monthly: float = 0.0
    #: Current collateral value (home / vehicle).
    asset_value: float = 0.0
    #: Purchase price / appraisal at origination — PMI LTV is measured against this.
    original_value: float = 0.0
    #: Annual collateral change; None means "use the loan type's default".
    asset_growth: float | None = None
    #: Last month whose interest has already been charged to this loan.
    accrued_through: date | None = None

    # --- type-driven behaviour -------------------------------------------- #
    @property
    def spec(self) -> LoanTypeSpec:
        return spec(self.loan_type)

    @property
    def method(self) -> InterestMethod:
        return self.interest_method or self.spec.interest_method

    @property
    def growth(self) -> float:
        return self.spec.asset_growth if self.asset_growth is None else self.asset_growth

    @property
    def is_secured(self) -> bool:
        return self.spec.secured and self.asset_value > 0

    # --- balances ---------------------------------------------------------- #
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

    @property
    def scheduled_payment(self) -> float:
        """Contractual P&I implied by the remaining term (0 when no term)."""
        if self.term_months <= 0:
            return 0.0
        return amortization.scheduled_payment(self.principal, self.annual_rate, self.term_months)

    @property
    def effective_minimum(self) -> float:
        """The minimum the engine must cover: stated, else derived from the term."""
        if self.minimum_payment > 0:
            return self.minimum_payment
        return self.scheduled_payment

    @property
    def months_left_at_minimum(self) -> int | None:
        return amortization.remaining_term(
            self.payoff_amount, self.annual_rate, self.effective_minimum
        )

    # --- collateral -------------------------------------------------------- #
    @property
    def pmi_active(self) -> bool:
        if self.pmi_monthly <= 0 or not self.is_open:
            return False
        basis = self.original_value or self.asset_value
        return amortization.pmi_applies(self.principal, basis)

    @property
    def ltv(self) -> float | None:
        return amortization.loan_to_value(self.payoff_amount, self.asset_value)

    @property
    def equity(self) -> float:
        return money(self.asset_value - self.payoff_amount) if self.asset_value > 0 else 0.0

    @property
    def housing_payment(self) -> float:
        """What actually leaves the bank account for a mortgage: P&I + escrow + PMI."""
        return money(
            self.effective_minimum
            + self.escrow_monthly
            + (self.pmi_monthly if self.pmi_active else 0.0)
        )

    # --- mutation ---------------------------------------------------------- #
    def copy(self) -> Loan:
        return replace(self)

    def _interest_for(self, period: date) -> float:
        if self.method is InterestMethod.MONTHLY:
            return self.principal * self.annual_rate / 12.0
        days = days_in_period(period)
        if self.method is InterestMethod.DAILY_COMPOUND:
            balance = self.principal + self.accrued_interest
            return balance * ((1 + self.annual_rate / DAYS_PER_YEAR) ** days - 1)
        return self.principal * self.annual_rate * days / DAYS_PER_YEAR

    def accrue(self, period: date) -> float:
        """Charge interest through `period`, catching up any skipped months.

        Idempotent: a month that has already been charged is never charged
        again, so previews, rollover passes and re-logged payments are safe.
        """
        if self.accrued_through is not None and self.accrued_through >= period:
            return 0.0
        start = period if self.accrued_through is None else add_months(self.accrued_through, 1)
        charged = 0.0
        cursor = start
        while cursor <= period:
            if self.is_open:
                interest = self._interest_for(cursor)
                self.accrued_interest += interest
                charged += interest
            cursor = add_months(cursor, 1)
        self.accrued_through = period
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


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Plan:
    """A group of loans paid from one monthly budget with one strategy."""

    name: str
    monthly_budget: float = 0.0
    strategy: str = AVALANCHE
    #: Inactive plans are kept but excluded from the household projection.
    active: bool = True
    #: When this plan is paid off, its budget rolls into the other plans.
    rollover: bool = True
    #: Whether this plan receives budget freed up by other finished plans.
    accepts_rollover: bool = True
    color: str = ""
    sort_order: int = 0
    plan_id: int | None = None


# --------------------------------------------------------------------------- #
# Sandbox pins and scenarios
# --------------------------------------------------------------------------- #
class PinMode(StrEnum):
    #: Extra cash on top of the base payment (tax refund, bonus).
    ADD = "add"
    #: Replace the payment for that month with an exact amount.
    SET = "set"
    #: Pay only the contractual minimums that month (lean month).
    MINIMUM = "minimum"


class PinRepeat(StrEnum):
    ONCE = "once"
    YEARLY = "yearly"


PIN_MODE_LABELS = {
    PinMode.ADD: "Add to base payment",
    PinMode.SET: "Replace payment with",
    PinMode.MINIMUM: "Pay minimums only",
}


@dataclass(slots=True)
class Pin:
    """A known change to one month's payment (or the same month every year)."""

    period: date
    amount: float = 0.0
    mode: PinMode = PinMode.ADD
    label: str = ""
    repeat: PinRepeat = PinRepeat.ONCE
    until: date | None = None
    pin_id: int | None = None

    def applies_to(self, period: date) -> bool:
        if self.repeat is PinRepeat.ONCE:
            return period == self.period
        return (
            period.month == self.period.month
            and period >= self.period
            and (self.until is None or period <= self.until)
        )

    def describe(self) -> str:
        if self.mode is PinMode.MINIMUM:
            return "Minimums only"
        sign = "+" if self.mode is PinMode.ADD else "="
        return f"{sign}${self.amount:,.0f}"

    def copy(self) -> Pin:
        return replace(self, pin_id=None)


@dataclass(slots=True)
class PinPreset:
    """A reusable pin template shown as a one-click button in the sandbox."""

    label: str
    mode: PinMode = PinMode.ADD
    amount: float = 0.0
    repeat: PinRepeat = PinRepeat.ONCE

    def to_pin(self, period: date) -> Pin:
        return Pin(period=period, amount=self.amount, mode=self.mode,
                   label=self.label, repeat=self.repeat)


DEFAULT_PRESETS = [
    PinPreset("Tax refund", PinMode.ADD, 3000.0),
    PinPreset("Bonus", PinMode.ADD, 10000.0),
    PinPreset("Lean month", PinMode.MINIMUM, 0.0),
]


@dataclass(slots=True)
class Scenario:
    """A what-if plan: a base monthly payment plus any number of pins."""

    name: str
    monthly_budget: float
    strategy: str = AVALANCHE
    pins: list[Pin] = field(default_factory=list)
    plan_id: int | None = None
    scenario_id: int | None = None
    created_on: date = field(default_factory=date.today)

    def pins_for(self, period: date) -> list[Pin]:
        return [pin for pin in self.pins if pin.applies_to(period)]

    def is_pinned(self, period: date) -> bool:
        return any(pin.applies_to(period) for pin in self.pins)

    def payment_for(self, period: date, minimum: float = 0.0) -> float:
        """Base payment, overridden by the latest SET/MINIMUM pin, plus every ADD."""
        active = self.pins_for(period)
        amount = self.monthly_budget
        replacing = [pin for pin in active if pin.mode is not PinMode.ADD]
        if replacing:
            last = replacing[-1]
            amount = minimum if last.mode is PinMode.MINIMUM else last.amount
        amount += sum(pin.amount for pin in active if pin.mode is PinMode.ADD)
        return money(max(amount, 0.0))

    def copy(self, name: str) -> Scenario:
        return Scenario(
            name=name,
            monthly_budget=self.monthly_budget,
            strategy=self.strategy,
            pins=[pin.copy() for pin in self.pins],
            plan_id=self.plan_id,
        )


# --------------------------------------------------------------------------- #
# Simulation output
# --------------------------------------------------------------------------- #
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
    #: PMI charged this month (a real cost of the debt, paid outside the budget).
    fees_paid: float = 0.0
    #: Escrow collected this month (pass-through, not a cost of the debt).
    escrow_paid: float = 0.0

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
    total_fees: float = 0.0
    #: Month PMI stops for each loan that carries it.
    pmi_ends: dict[str, date] = field(default_factory=dict)

    @property
    def years_to_payoff(self) -> float:
        return self.months_to_payoff / 12.0

    @property
    def total_cost(self) -> float:
        return money(self.total_interest + self.total_fees)

    def balance_series(self) -> tuple[list[date], dict[str, list[float]]]:
        """Per-loan ending balances over time, ready for a stacked area chart."""
        periods = [m.period for m in self.months]
        series = {name: [m.balances.get(name, 0.0) for m in self.months] for name in self.loan_names}
        return periods, series

    def loan_payoff_periods(self) -> dict[str, date]:
        found: dict[str, date] = {}
        for month in self.months:
            for name, balance in month.balances.items():
                if balance <= EPSILON and name not in found:
                    found[name] = month.period
        return found


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
    plan_id: int | None = None


@dataclass(slots=True)
class Baseline:
    """The original plan, kept so deviations can be scored against it."""

    captured_on: date
    monthly_budget: float
    strategy: str
    total_interest: float
    payoff_date: date | None
    starting_balance: float
