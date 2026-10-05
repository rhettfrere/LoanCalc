"""Single source of truth shared by every tab.

Holds the live loan set, the user's settings, the current forecast and the
baseline plan. Views listen to the signals rather than talking to each other.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from loancalc import engine, ingest
from loancalc.models import (
    Allocation,
    Baseline,
    Loan,
    MonthResult,
    PaymentRecord,
    Scenario,
    Schedule,
)
from loancalc.paths import sample_data_text
from loancalc.storage import Store

DEFAULT_BUDGET = 5000.0

#: How far ahead the scenario planner lets you schedule payments.
PLANNING_HORIZON = 120


class AppState(QObject):
    """Owns the data and republishes it whenever something changes."""

    loansChanged = Signal()
    scheduleChanged = Signal()
    historyChanged = Signal()
    scenariosChanged = Signal()
    statusMessage = Signal(str)

    def __init__(self, store: Store, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.loans: list[Loan] = []
        self.schedule: Schedule | None = None
        self.minimums_schedule: Schedule | None = None
        self.baseline: Baseline | None = store.load_baseline()
        self.monthly_budget = store.get_float("monthly_budget", DEFAULT_BUDGET)
        self.strategy = store.get_setting("strategy", engine.AVALANCHE) or engine.AVALANCHE
        self.scenarios: list[Scenario] = store.scenarios()
        self._load_initial_loans()

    # --- bootstrap --------------------------------------------------------- #
    def _load_initial_loans(self) -> None:
        if self.store.is_empty():
            text = sample_data_text()
            if text:
                try:
                    self.store.replace_loans(ingest.load_loans_from_text(text))
                except ingest.IngestError:
                    pass
        self.loans = self.store.load_loans()
        self.recalculate()
        if self.baseline is None and self.loans:
            self.capture_baseline()

    # --- derived values ---------------------------------------------------- #
    @property
    def current_period(self) -> date:
        return engine.period_of(date.today())

    @property
    def total_balance(self) -> float:
        return engine.total_balance(self.loans)

    @property
    def total_minimum(self) -> float:
        return engine.total_minimum_payment(self.loans)

    @property
    def last_accrued_period(self) -> date | None:
        raw = self.store.get_setting("last_accrued_period")
        return date.fromisoformat(raw) if raw else None

    def period_accrued(self, period: date) -> bool:
        """True when interest for `period` has already been charged."""
        last = self.last_accrued_period
        return last is not None and last >= period

    @property
    def current_period_accrued(self) -> bool:
        return self.period_accrued(self.current_period)

    def paid_in_period(self, period: date) -> float:
        return round(
            sum(p.total_amount for p in self.store.payments() if p.period == period), 2
        )

    def paid_this_period(self) -> float:
        return self.paid_in_period(self.current_period)

    def interest_paid_to_date(self) -> float:
        return round(self.store.payment_totals()[1], 2)

    def priority_loans(self) -> list[Loan]:
        return engine.priority_order(self.loans, self.strategy)

    # --- forecasting ------------------------------------------------------- #
    def recalculate(self) -> None:
        remaining_budget = max(self.monthly_budget - self.paid_this_period(), 0.0)
        self.schedule = engine.simulate(
            self.loans,
            self.monthly_budget,
            start_period=self.current_period,
            strategy=self.strategy,
            first_month_budget=remaining_budget,
            skip_first_accrual=self.current_period_accrued,
        )
        self.minimums_schedule = engine.minimum_only_schedule(
            self.loans, start_period=self.current_period, strategy=self.strategy
        )
        self.scheduleChanged.emit()

    def capture_baseline(self) -> None:
        """Freeze today's plan so later deviations can be scored against it."""
        plan = engine.simulate(
            self.loans,
            self.monthly_budget,
            start_period=self.current_period,
            strategy=self.strategy,
        )
        self.baseline = Baseline(
            captured_on=date.today(),
            monthly_budget=self.monthly_budget,
            strategy=self.strategy,
            total_interest=plan.total_interest,
            payoff_date=plan.payoff_date,
            starting_balance=plan.starting_balance,
        )
        self.store.save_baseline(self.baseline)
        self.scheduleChanged.emit()

    def lifetime_interest(self) -> float:
        """Interest already paid plus interest still forecast."""
        projected = self.schedule.total_interest if self.schedule else 0.0
        return round(self.interest_paid_to_date() + projected, 2)

    def interest_delta(self) -> float | None:
        """Positive = saving money versus the baseline plan."""
        if not self.baseline:
            return None
        return round(self.baseline.total_interest - self.lifetime_interest(), 2)

    def payoff_delta_months(self) -> int | None:
        """Positive = finishing earlier than the baseline plan."""
        if not self.baseline or not self.baseline.payoff_date or not self.schedule:
            return None
        projected = self.schedule.payoff_date
        if not projected:
            return None
        base = self.baseline.payoff_date
        return (base.year * 12 + base.month) - (projected.year * 12 + projected.month)

    # --- settings ---------------------------------------------------------- #
    def set_monthly_budget(self, value: float) -> None:
        self.monthly_budget = round(max(value, 0.0), 2)
        self.store.set_setting("monthly_budget", str(self.monthly_budget))
        self.recalculate()

    def set_strategy(self, strategy: str) -> None:
        self.strategy = strategy
        self.store.set_setting("strategy", strategy)
        self.recalculate()

    # --- loan management --------------------------------------------------- #
    def import_file(self, path: str | Path) -> int:
        loans = ingest.load_loans(path)
        self._install_loans(loans)
        self.statusMessage.emit(f"Imported {len(loans)} loans from {Path(path).name}")
        return len(loans)

    def reset_to_sample(self) -> int:
        text = sample_data_text()
        if not text:
            raise ingest.IngestError("The bundled sample dataset is not available.")
        loans = ingest.load_loans_from_text(text)
        self._install_loans(loans)
        self.statusMessage.emit(f"Restored the bundled dataset ({len(loans)} loans)")
        return len(loans)

    def _install_loans(self, loans: list[Loan]) -> None:
        self.store.clear_payments()
        self.loans = self.store.replace_loans(loans)
        self.store.set_setting("last_accrued_period", "")
        self.recalculate()
        self.capture_baseline()
        self.loansChanged.emit()
        self.historyChanged.emit()

    def upsert_loan(self, loan: Loan) -> None:
        if loan.loan_id is None:
            loan.sort_order = len(self.loans)
            self.loans.append(loan)
        self.store.save_loans(self.loans)
        self.loans = self.store.load_loans()
        self.recalculate()
        self.loansChanged.emit()

    def delete_loan(self, loan: Loan) -> None:
        if loan.loan_id is not None:
            self.store.delete_loan(loan.loan_id)
        self.loans = self.store.load_loans()
        self.recalculate()
        self.loansChanged.emit()

    # --- the monthly action centre ---------------------------------------- #
    def preview_payment(self, amount: float, period: date | None = None) -> MonthResult:
        """Show how `amount` would be split without touching stored balances."""
        period = period or self.current_period
        result, _ = engine.preview_month(
            self.loans,
            amount,
            period,
            strategy=self.strategy,
            accrue=not self.period_accrued(period),
        )
        return result

    def log_payment(
        self, amount: float, note: str = "", period: date | None = None
    ) -> tuple[PaymentRecord, MonthResult]:
        """Commit a real payment: accrue, allocate, persist, re-forecast."""
        period = period or self.current_period
        result = engine.apply_month(
            self.loans,
            amount,
            period,
            strategy=self.strategy,
            accrue=not self.period_accrued(period),
        )
        self.store.save_loans(self.loans)
        last = self.last_accrued_period
        self.store.set_setting(
            "last_accrued_period", max(period, last).isoformat() if last else period.isoformat()
        )

        record = PaymentRecord(
            period=period,
            paid_on=date.today(),
            total_amount=result.total_paid,
            interest_paid=result.interest_paid,
            principal_paid=result.principal_paid,
            allocations=[a for a in result.allocations if a.amount > 0],
            note=note,
        )
        self.store.record_payment(record)
        self.loans = self.store.load_loans()
        self.recalculate()
        self.loansChanged.emit()
        self.historyChanged.emit()
        return record, result

    def history(self) -> list[PaymentRecord]:
        return self.store.payments()

    def allocation_rows(self, result: MonthResult) -> list[Allocation]:
        """Allocations in payoff-priority order, funded ones first."""
        ranked = {loan.name: index for index, loan in enumerate(self.priority_loans())}
        return sorted(
            result.allocations,
            key=lambda a: (a.amount <= 0, ranked.get(a.loan_name, 10_000)),
        )

    # --- scenario sandbox -------------------------------------------------- #
    def planning_periods(self, count: int | None = None) -> list[date]:
        """Months the planner can schedule, starting with the current one."""
        if count is None:
            projected = self.schedule.months_to_payoff if self.schedule else 24
            count = max(24, min(projected + 12, PLANNING_HORIZON))
        start = self.current_period
        return [engine.add_months(start, offset) for offset in range(count)]

    def simulate_scenario(self, scenario: Scenario) -> Schedule:
        """Forecast a what-if plan from today's real balances."""
        return engine.simulate(
            self.loans,
            scenario.monthly_budget,
            start_period=self.current_period,
            strategy=scenario.strategy or self.strategy,
            overrides=scenario.overrides,
            skip_first_accrual=self.current_period_accrued,
        )

    def new_scenario(self, name: str | None = None) -> Scenario:
        existing = {s.name for s in self.scenarios}
        base = name or "Plan A"
        candidate, suffix = base, 2
        while candidate in existing:
            candidate, suffix = f"{base} ({suffix})", suffix + 1
        scenario = Scenario(
            name=candidate,
            monthly_budget=self.monthly_budget,
            strategy=self.strategy,
        )
        self.save_scenario(scenario)
        return scenario

    def save_scenario(self, scenario: Scenario) -> Scenario:
        self.store.save_scenario(scenario)
        self.scenarios = self.store.scenarios()
        self.scenariosChanged.emit()
        return scenario

    def delete_scenario(self, scenario: Scenario) -> None:
        if scenario.scenario_id is not None:
            self.store.delete_scenario(scenario.scenario_id)
        self.scenarios = self.store.scenarios()
        self.scenariosChanged.emit()

    def adopt_scenario(self, scenario: Scenario) -> None:
        """Promote a sandbox plan to the live plan."""
        self.strategy = scenario.strategy or self.strategy
        self.store.set_setting("strategy", self.strategy)
        self.set_monthly_budget(scenario.monthly_budget)
        self.statusMessage.emit(f"Adopted '{scenario.name}' as the active plan.")
