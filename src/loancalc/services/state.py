"""Application state: the single source of truth shared by every view.

Holds every plan and loan, the plan currently being viewed, each plan's
forecast, and the household projection that runs all active plans together.
Views listen to the signals and never talk to each other directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from loancalc.data import ingest
from loancalc.data.paths import sample_data_text
from loancalc.data.storage import Store
from loancalc.domain import engine
from loancalc.domain.household import (
    HouseholdSchedule,
    PlanInput,
    simulate_household,
)
from loancalc.domain.loan_types import SPECS, LoanType
from loancalc.domain.models import (
    AVALANCHE,
    Allocation,
    Baseline,
    Loan,
    MonthResult,
    PaymentRecord,
    PinPreset,
    Plan,
    Scenario,
    Schedule,
)
from loancalc.domain.periods import add_months, months_between, period_of

DEFAULT_BUDGET = 5000.0
#: How far ahead the scenario planner lets you schedule payments.
PLANNING_HORIZON = 480
EXTRA_PALETTE = ("#2A9D8F", "#C9922A", "#8C4B4B", "#5B8C3A", "#A0548B", "#3F7F7F")


@dataclass(slots=True)
class ImportSummary:
    added: int = 0
    updated: int = 0
    plans_created: list[str] = field(default_factory=list)
    inferred_types: int = 0
    replaced: bool = False

    def describe(self) -> str:
        parts = []
        if self.added:
            parts.append(f"{self.added} loan(s) added")
        if self.updated:
            parts.append(f"{self.updated} updated")
        if self.plans_created:
            parts.append("new plan(s): " + ", ".join(self.plans_created))
        if self.inferred_types:
            parts.append(f"{self.inferred_types} loan type(s) guessed from names")
        return "; ".join(parts) or "Nothing changed"


class AppState(QObject):
    plansChanged = Signal()
    loansChanged = Signal()
    scheduleChanged = Signal()
    householdChanged = Signal()
    historyChanged = Signal()
    scenariosChanged = Signal()
    currentPlanChanged = Signal()
    statusMessage = Signal(str)

    def __init__(self, store: Store, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.plans: list[Plan] = []
        self.all_loans: list[Loan] = []
        self.current_plan_id: int | None = None
        self.schedules: dict[int, Schedule] = {}
        self.minimum_schedules: dict[int, Schedule] = {}
        self.household: HouseholdSchedule | None = None
        self.household_isolated: HouseholdSchedule | None = None
        self._bootstrap()

    # ===================================================================== #
    # Bootstrap / reload
    # ===================================================================== #
    def _bootstrap(self) -> None:
        if self.store.is_empty() and not self.store.plans():
            text = sample_data_text()
            if text:
                try:
                    self._install(ingest.load_loans_from_text(text), replace=False, emit=False)
                except ingest.IngestError:
                    pass
        self._load()
        self._adopt_orphans()
        self.recalculate_all(emit=False)
        for plan in self.plans:
            if plan.plan_id is not None and self.store.load_baseline(plan.plan_id) is None:
                self.capture_baseline(plan.plan_id, emit=False)

    def _load(self) -> None:
        self.plans = self.store.plans()
        self.all_loans = self.store.load_loans()
        saved = self.store.get_setting("current_plan")
        ids = [plan.plan_id for plan in self.plans]
        current = int(saved) if saved and saved.isdigit() else None
        self.current_plan_id = current if current in ids else (ids[0] if ids else None)

    def _adopt_orphans(self) -> None:
        """Any loan without a valid plan goes to its type's default plan."""
        ids = {plan.plan_id for plan in self.plans}
        orphans = [loan for loan in self.all_loans if loan.plan_id not in ids]
        for loan in orphans:
            loan.plan_id = self._plan_for_type(loan.loan_type).plan_id
        if orphans:
            self.store.save_loans(orphans)

    def reload(self) -> None:
        self._load()
        self._adopt_orphans()
        self.recalculate_all(emit=False)
        self._emit_all()

    def _emit_all(self) -> None:
        for signal in (self.plansChanged, self.currentPlanChanged, self.loansChanged,
                       self.historyChanged, self.scenariosChanged, self.scheduleChanged,
                       self.householdChanged):
            signal.emit()

    # ===================================================================== #
    # Plans
    # ===================================================================== #
    @property
    def current_plan(self) -> Plan | None:
        return self.plan_by_id(self.current_plan_id)

    def plan_by_id(self, plan_id: int | None) -> Plan | None:
        return next((plan for plan in self.plans if plan.plan_id == plan_id), None)

    def plan_loans(self, plan_id: int | None) -> list[Loan]:
        return [loan for loan in self.all_loans if loan.plan_id == plan_id]

    def plan_types(self, plan_id: int | None) -> set[LoanType]:
        return {loan.loan_type for loan in self.plan_loans(plan_id)}

    def plan_color(self, plan: Plan) -> str:
        if plan.color:
            return plan.color
        index = self.plans.index(plan) if plan in self.plans else 0
        return EXTRA_PALETTE[index % len(EXTRA_PALETTE)]

    def set_current_plan(self, plan_id: int | None) -> None:
        if plan_id == self.current_plan_id or self.plan_by_id(plan_id) is None:
            return
        self.current_plan_id = plan_id
        self.store.set_setting("current_plan", str(plan_id))
        for signal in (self.currentPlanChanged, self.loansChanged, self.historyChanged,
                       self.scenariosChanged, self.scheduleChanged):
            signal.emit()

    def _next_color(self) -> str:
        used = {plan.color for plan in self.plans}
        for color in (*[s.color for s in SPECS.values()], *EXTRA_PALETTE):
            if color not in used:
                return color
        return EXTRA_PALETTE[len(self.plans) % len(EXTRA_PALETTE)]

    def _plan_for_type(self, loan_type: LoanType) -> Plan:
        name = SPECS[loan_type].plan_name
        existing = next((p for p in self.plans if p.name.lower() == name.lower()), None)
        return existing or self._create_plan(name, color=SPECS[loan_type].color)

    def _create_plan(self, name: str, *, budget: float = 0.0, color: str = "") -> Plan:
        plan = Plan(
            name=name,
            monthly_budget=budget,
            color=color or self._next_color(),
            sort_order=len(self.plans),
        )
        self.store.save_plan(plan)
        self.plans.append(plan)
        return plan

    def add_plan(self, name: str, budget: float = 0.0) -> Plan:
        plan = self._create_plan(self._unique_plan_name(name), budget=budget)
        self.plansChanged.emit()
        self.set_current_plan(plan.plan_id)
        return plan

    def _unique_plan_name(self, base: str) -> str:
        names = {plan.name.lower() for plan in self.plans}
        candidate, suffix = base, 2
        while candidate.lower() in names:
            candidate, suffix = f"{base} ({suffix})", suffix + 1
        return candidate

    def save_plan(self, plan: Plan, *, recalc: bool = True) -> None:
        self.store.save_plan(plan)
        self.plans = self.store.plans()
        self.plansChanged.emit()
        if recalc:
            self.recalculate_all()

    def reorder_plans(self, ordered_ids: list[int]) -> None:
        for index, plan_id in enumerate(ordered_ids):
            plan = self.plan_by_id(plan_id)
            if plan is not None:
                plan.sort_order = index
                self.store.save_plan(plan)
        self.plans = self.store.plans()
        self.plansChanged.emit()
        self.recalculate_all()

    def delete_plan(self, plan: Plan) -> None:
        if plan.plan_id is None:
            return
        self.store.delete_plan(plan.plan_id)
        self._load()
        self.recalculate_all(emit=False)
        self._emit_all()
        self.statusMessage.emit(f"Deleted plan '{plan.name}'.")

    # ===================================================================== #
    # Current-plan convenience (what most tabs bind to)
    # ===================================================================== #
    @property
    def loans(self) -> list[Loan]:
        return self.plan_loans(self.current_plan_id)

    @property
    def schedule(self) -> Schedule | None:
        return self.schedules.get(self.current_plan_id) if self.current_plan_id else None

    @property
    def minimums_schedule(self) -> Schedule | None:
        return self.minimum_schedules.get(self.current_plan_id) if self.current_plan_id else None

    @property
    def monthly_budget(self) -> float:
        plan = self.current_plan
        return plan.monthly_budget if plan else 0.0

    @property
    def strategy(self) -> str:
        plan = self.current_plan
        return plan.strategy if plan else AVALANCHE

    @property
    def baseline(self) -> Baseline | None:
        return self.store.load_baseline(self.current_plan_id) if self.current_plan_id else None

    @property
    def current_period(self) -> date:
        return period_of(date.today())

    @property
    def total_balance(self) -> float:
        return engine.total_balance(self.loans)

    @property
    def total_minimum(self) -> float:
        return engine.total_minimum_payment(self.loans)

    @property
    def household_balance(self) -> float:
        return engine.total_balance(self.active_loans())

    def active_loans(self) -> list[Loan]:
        active = {plan.plan_id for plan in self.plans if plan.active}
        return [loan for loan in self.all_loans if loan.plan_id in active]

    def priority_loans(self) -> list[Loan]:
        return engine.priority_order(self.loans, self.strategy)

    def period_accrued(self, period: date, plan_id: int | None = None) -> bool:
        """True when every open loan in the plan has been charged for `period`."""
        loans = [loan for loan in self.plan_loans(plan_id or self.current_plan_id) if loan.is_open]
        return bool(loans) and all(
            loan.accrued_through is not None and loan.accrued_through >= period for loan in loans
        )

    @property
    def current_period_accrued(self) -> bool:
        return self.period_accrued(self.current_period)

    def paid_in_period(self, period: date, plan_id: int | None = None) -> float:
        return self.store.paid_in_period(period, plan_id or self.current_plan_id)

    def paid_this_period(self) -> float:
        return self.paid_in_period(self.current_period)

    def interest_paid_to_date(self) -> float:
        return round(self.store.payment_totals(self.current_plan_id)[1], 2)

    # ===================================================================== #
    # Forecasting
    # ===================================================================== #
    def _simulate_plan(self, plan: Plan) -> tuple[Schedule, Schedule]:
        loans = self.plan_loans(plan.plan_id)
        paid = self.paid_in_period(self.current_period, plan.plan_id)
        schedule = engine.simulate(
            loans,
            plan.monthly_budget,
            start_period=self.current_period,
            strategy=plan.strategy,
            first_month_budget=max(plan.monthly_budget - paid, 0.0),
        )
        minimums = engine.minimum_only_schedule(
            loans, start_period=self.current_period, strategy=plan.strategy
        )
        return schedule, minimums

    def _household_inputs(self) -> list[PlanInput]:
        inputs = []
        current = self.current_period
        for plan in self.plans:
            if not plan.active:
                continue
            paid = self.paid_in_period(current, plan.plan_id)
            budget = plan.monthly_budget

            def payment_for(period: date, budget=budget, paid=paid) -> float:
                return max(budget - paid, 0.0) if period == current else budget

            inputs.append(PlanInput(plan, self.plan_loans(plan.plan_id), payment_for))
        return inputs

    @property
    def rollover_enabled(self) -> bool:
        return self.store.get_bool("household_rollover", True)

    @property
    def rollover_strategy(self) -> str:
        return self.store.get_setting("household_rollover_strategy", AVALANCHE) or AVALANCHE

    def set_rollover(self, enabled: bool) -> None:
        self.store.set_bool("household_rollover", enabled)
        self._recalculate_household()
        self.householdChanged.emit()

    def set_rollover_strategy(self, strategy: str) -> None:
        self.store.set_setting("household_rollover_strategy", strategy)
        self._recalculate_household()
        self.householdChanged.emit()

    def _recalculate_household(self) -> None:
        inputs = self._household_inputs()
        self.household_isolated = simulate_household(
            inputs, start_period=self.current_period, rollover=False
        )
        self.household = (
            simulate_household(
                inputs,
                start_period=self.current_period,
                rollover=True,
                rollover_strategy=self.rollover_strategy,
            )
            if self.rollover_enabled
            else self.household_isolated
        )

    def recalculate_all(self, *, emit: bool = True) -> None:
        self.schedules.clear()
        self.minimum_schedules.clear()
        for plan in self.plans:
            if plan.plan_id is not None:
                self.schedules[plan.plan_id], self.minimum_schedules[plan.plan_id] = (
                    self._simulate_plan(plan)
                )
        self._recalculate_household()
        if emit:
            self.scheduleChanged.emit()
            self.householdChanged.emit()

    def recalculate(self) -> None:
        self.recalculate_all()

    def capture_baseline(self, plan_id: int | None = None, *, emit: bool = True) -> None:
        """Freeze a plan's projection so later deviations can be scored against it."""
        plan = self.plan_by_id(plan_id or self.current_plan_id)
        if plan is None or plan.plan_id is None:
            return
        projection = engine.simulate(
            self.plan_loans(plan.plan_id),
            plan.monthly_budget,
            start_period=self.current_period,
            strategy=plan.strategy,
        )
        self.store.save_baseline(
            plan.plan_id,
            Baseline(
                captured_on=date.today(),
                monthly_budget=plan.monthly_budget,
                strategy=plan.strategy,
                total_interest=projection.total_interest,
                payoff_date=projection.payoff_date,
                starting_balance=projection.starting_balance,
            ),
        )
        if emit:
            self.scheduleChanged.emit()

    def lifetime_interest(self) -> float:
        projected = self.schedule.total_interest if self.schedule else 0.0
        return round(self.interest_paid_to_date() + projected, 2)

    def interest_delta(self) -> float | None:
        """Positive = saving money versus the baseline plan."""
        baseline = self.baseline
        if not baseline:
            return None
        return round(baseline.total_interest - self.lifetime_interest(), 2)

    def payoff_delta_months(self) -> int | None:
        """Positive = finishing earlier than the baseline plan."""
        baseline = self.baseline
        if not baseline or not baseline.payoff_date or not self.schedule:
            return None
        projected = self.schedule.payoff_date
        return months_between(projected, baseline.payoff_date) if projected else None

    def household_payoff_for(self, plan_id: int | None) -> date | None:
        """When a plan finishes inside the household projection (with rollover)."""
        if self.household is None or plan_id is None:
            return None
        outcome = self.household.outcomes.get(plan_id)
        return outcome.payoff_date if outcome else None

    def set_monthly_budget(self, value: float) -> None:
        plan = self.current_plan
        if plan is None:
            return
        plan.monthly_budget = round(max(value, 0.0), 2)
        self.save_plan(plan)

    def set_strategy(self, strategy: str) -> None:
        plan = self.current_plan
        if plan is None:
            return
        plan.strategy = strategy
        self.save_plan(plan)

    # ===================================================================== #
    # Import / loan management
    # ===================================================================== #
    def import_file(self, path: str | Path, *, replace: bool = False) -> ImportSummary:
        summary = self.apply_import(ingest.load_loans(path), replace=replace)
        self.statusMessage.emit(f"Imported {Path(path).name}: {summary.describe()}")
        return summary

    def apply_import(self, result: ingest.ImportResult, *, replace: bool = False) -> ImportSummary:
        """Apply an already-parsed (and previewed) import."""
        return self._install(result, replace=replace)

    def reset_to_sample(self) -> ImportSummary:
        text = sample_data_text()
        if not text:
            raise ingest.IngestError("The bundled sample dataset is not available.")
        summary = self._install(ingest.load_loans_from_text(text), replace=True)
        self.statusMessage.emit("Restored the bundled dataset.")
        return summary

    def _install(self, result: ingest.ImportResult, *, replace: bool, emit: bool = True) -> ImportSummary:
        """Write imported loans into plans, matching existing plans/loans by name."""
        summary = ImportSummary(inferred_types=result.inferred_types, replaced=replace)
        if replace:
            self.store.wipe()
            self.plans, self.all_loans = [], []
        else:
            self.plans = self.store.plans()
            self.all_loans = self.store.load_loans()

        existing_plans = {plan.name.lower(): plan for plan in self.plans}
        touched: set[int] = set()
        to_save: list[Loan] = []
        for loan, plan_name in zip(result.loans, result.plan_names, strict=True):
            name = plan_name or SPECS[loan.loan_type].plan_name
            plan = existing_plans.get(name.lower())
            if plan is None:
                color = SPECS[loan.loan_type].color if not plan_name else ""
                plan = self._create_plan(name, color=color)
                existing_plans[name.lower()] = plan
                summary.plans_created.append(plan.name)
            loan.plan_id = plan.plan_id
            touched.add(plan.plan_id)

            match = next(
                (old for old in self.all_loans
                 if old.plan_id == plan.plan_id and old.name.lower() == loan.name.lower()),
                None,
            )
            if match is not None:
                # A fresh statement: take its numbers, keep identity and accrual state.
                loan.loan_id = match.loan_id
                loan.sort_order = match.sort_order
                loan.accrued_through = match.accrued_through
                summary.updated += 1
            else:
                loan.sort_order = len(self.plan_loans(plan.plan_id)) + len(to_save)
                summary.added += 1
            to_save.append(loan)

        self.store.save_loans(to_save)
        self.all_loans = self.store.load_loans()

        for plan_id in touched:
            plan = self.plan_by_id(plan_id)
            if plan is not None and plan.monthly_budget <= 0:
                plan_loans = self.plan_loans(plan_id)
                minimum = engine.total_minimum_payment(plan_loans)
                # Student plans default to the original $5,000 attack budget;
                # everything else starts at its contractual minimums.
                student = all(loan.loan_type is LoanType.STUDENT for loan in plan_loans)
                plan.monthly_budget = max(minimum, DEFAULT_BUDGET) if student else minimum
                self.store.save_plan(plan)
        self.plans = self.store.plans()
        if self.current_plan_id not in {p.plan_id for p in self.plans} and self.plans:
            self.current_plan_id = self.plans[0].plan_id
            self.store.set_setting("current_plan", str(self.current_plan_id))

        self.recalculate_all(emit=False)
        for plan_id in touched:
            if replace or self.store.load_baseline(plan_id) is None:
                self.capture_baseline(plan_id, emit=False)
        if emit:
            self._emit_all()
        return summary

    def upsert_loan(self, loan: Loan) -> None:
        if loan.plan_id is None:
            loan.plan_id = self.current_plan_id
        if loan.loan_id is None:
            loan.sort_order = len(self.plan_loans(loan.plan_id))
        self.store.save_loans([loan])
        self.all_loans = self.store.load_loans()
        self.recalculate_all(emit=False)
        self.loansChanged.emit()
        self.scheduleChanged.emit()
        self.householdChanged.emit()

    def delete_loan(self, loan: Loan) -> None:
        if loan.loan_id is not None:
            self.store.delete_loan(loan.loan_id)
        self.all_loans = self.store.load_loans()
        self.recalculate_all(emit=False)
        self.loansChanged.emit()
        self.scheduleChanged.emit()
        self.householdChanged.emit()

    # ===================================================================== #
    # Monthly action centre
    # ===================================================================== #
    def preview_payment(self, amount: float, period: date | None = None) -> MonthResult:
        """Show how `amount` would be split without touching stored balances."""
        result, _ = engine.preview_month(
            self.loans, amount, period or self.current_period, strategy=self.strategy
        )
        return result

    def log_payment(
        self, amount: float, note: str = "", period: date | None = None
    ) -> tuple[PaymentRecord, MonthResult]:
        """Commit a real payment: accrue, allocate, persist, re-forecast."""
        period = period or self.current_period
        loans = self.loans
        result = engine.apply_month(loans, amount, period, strategy=self.strategy)
        self.store.save_loans(loans)

        record = PaymentRecord(
            period=period,
            paid_on=date.today(),
            total_amount=result.total_paid,
            interest_paid=result.interest_paid,
            principal_paid=result.principal_paid,
            allocations=[a for a in result.allocations if a.amount > 0],
            note=note,
            plan_id=self.current_plan_id,
        )
        self.store.record_payment(record)
        self.all_loans = self.store.load_loans()
        self.recalculate_all(emit=False)
        self.loansChanged.emit()
        self.historyChanged.emit()
        self.scheduleChanged.emit()
        self.householdChanged.emit()
        return record, result

    def history(self, *, all_plans: bool = False) -> list[PaymentRecord]:
        return self.store.payments(None if all_plans else self.current_plan_id)

    def clear_history(self) -> None:
        plan_id = self.current_plan_id
        self.store.clear_payments(plan_id)
        self.recalculate_all(emit=False)
        self.historyChanged.emit()
        self.scheduleChanged.emit()
        self.householdChanged.emit()

    def allocation_rows(self, result: MonthResult) -> list[Allocation]:
        """Allocations in payoff-priority order, funded ones first."""
        ranked = {loan.name: index for index, loan in enumerate(self.priority_loans())}
        return sorted(
            result.allocations,
            key=lambda a: (a.amount <= 0, ranked.get(a.loan_name, 10_000)),
        )

    # ===================================================================== #
    # Scenario sandbox
    # ===================================================================== #
    @property
    def scenarios(self) -> list[Scenario]:
        return self.store.scenarios(self.current_plan_id) if self.current_plan_id else []

    def planning_periods(self, count: int | None = None) -> list[date]:
        """Months the planner can schedule, starting with the current one."""
        if count is None:
            projected = self.schedule.months_to_payoff if self.schedule else 24
            count = max(24, min(projected + 12, PLANNING_HORIZON))
        return [add_months(self.current_period, offset) for offset in range(count)]

    def simulate_scenario(self, scenario: Scenario) -> Schedule:
        """Forecast a what-if plan from today's real balances."""
        loans = self.plan_loans(scenario.plan_id or self.current_plan_id)
        return engine.simulate(
            loans,
            scenario.monthly_budget,
            start_period=self.current_period,
            strategy=scenario.strategy or self.strategy,
            payment_for=self._scenario_payments(scenario),
        )

    def _scenario_payments(self, scenario: Scenario):
        loans = self.plan_loans(scenario.plan_id or self.current_plan_id)
        minimum = engine.total_minimum_payment(loans)
        current = self.current_period
        already = self.paid_in_period(current, scenario.plan_id)

        def payment_for(period: date) -> float:
            amount = scenario.payment_for(period, minimum)
            return max(amount - already, 0.0) if period == current else amount

        return payment_for

    def household_with_scenario(self, scenario: Scenario) -> HouseholdSchedule:
        """The household projection if this scenario replaced its plan's settings."""
        inputs = self._household_inputs()
        for index, item in enumerate(inputs):
            if item.plan.plan_id == scenario.plan_id:
                plan = replace(
                    item.plan,
                    monthly_budget=scenario.monthly_budget,
                    strategy=scenario.strategy or item.plan.strategy,
                )
                inputs[index] = PlanInput(plan, item.loans, self._scenario_payments(scenario))
        return simulate_household(
            inputs,
            start_period=self.current_period,
            rollover=self.rollover_enabled,
            rollover_strategy=self.rollover_strategy,
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
            plan_id=self.current_plan_id,
        )
        return self.save_scenario(scenario)

    def save_scenario(self, scenario: Scenario) -> Scenario:
        if scenario.plan_id is None:
            scenario.plan_id = self.current_plan_id
        self.store.save_scenario(scenario)
        self.scenariosChanged.emit()
        return scenario

    def delete_scenario(self, scenario: Scenario) -> None:
        if scenario.scenario_id is not None:
            self.store.delete_scenario(scenario.scenario_id)
        self.scenariosChanged.emit()

    def adopt_scenario(self, scenario: Scenario) -> None:
        """Promote a sandbox plan's base payment and strategy to the live plan."""
        plan = self.plan_by_id(scenario.plan_id)
        if plan is None:
            return
        plan.monthly_budget = scenario.monthly_budget
        plan.strategy = scenario.strategy or plan.strategy
        self.save_plan(plan)
        self.statusMessage.emit(f"Adopted '{scenario.name}' as the active {plan.name} plan.")

    def presets(self) -> list[PinPreset]:
        return self.store.load_presets()

    def save_presets(self, presets: list[PinPreset]) -> None:
        self.store.save_presets(presets)
        self.scenariosChanged.emit()

    # ===================================================================== #
    # Backup / restore
    # ===================================================================== #
    def backup_to(self, path: Path) -> None:
        self.store.backup_to(path)
        self.statusMessage.emit(f"Backed up everything to {Path(path).name}")

    def restore_from(self, path: Path) -> None:
        self.store.restore_from(path)
        self.reload()
        self.statusMessage.emit(f"Restored from {Path(path).name}")
