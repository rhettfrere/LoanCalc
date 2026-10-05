"""Household: every active plan on one calendar, and how they help each other."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from loancalc.domain import engine
from loancalc.domain.household import ROLLOVER_LABELS
from loancalc.domain.loan_types import SPECS
from loancalc.domain.periods import months_between
from loancalc.services.state import AppState
from loancalc.ui import theme
from loancalc.ui.charts import HouseholdBalanceChart, HouseholdCashFlowChart
from loancalc.ui.widgets import Card, MetricCard, banner, cell, make_table
from loancalc.util.formatting import duration, money, money_compact

ACTIVE_COLUMN = 6
ROLLOVER_COLUMN = 7


class HouseholdTab(QWidget):
    #: Emitted with a plan id when the user wants to drill into a plan.
    openPlan = Signal(int)
    managePlans = Signal()

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())
        self.empty = banner(
            "No active plans carry debt. Import loans (File → Import Loans…) or activate a plan."
        )
        layout.addWidget(self.empty)
        layout.addLayout(self._build_metrics())

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_plans_card())
        splitter.addWidget(self._build_charts_card())
        splitter.setSizes([260, 460])
        layout.addWidget(splitter, 1)

        for signal in (state.householdChanged, state.plansChanged, state.loansChanged):
            signal.connect(self.refresh)
        self.refresh()

    # --- construction ------------------------------------------------------ #
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(theme.hero("Household"))
        self.sub = theme.subtitle("")
        titles.addWidget(self.sub)
        row.addLayout(titles, 1)

        self.rollover = QCheckBox("Roll finished plans into the rest")
        self.rollover.setToolTip(
            "When a plan is paid off, keep paying its budget — redirected to plans still in debt."
        )
        self.rollover.toggled.connect(self._rollover_toggled)
        self.rollover_mode = QComboBox()
        for key, label in ROLLOVER_LABELS.items():
            self.rollover_mode.addItem(label, key)
        self.rollover_mode.currentIndexChanged.connect(self._mode_changed)
        manage = QPushButton("Manage plans…")
        manage.clicked.connect(self.managePlans.emit)

        controls = QVBoxLayout()
        controls.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(self.rollover)
        top.addWidget(manage)
        controls.addLayout(top)
        mode_row = QHBoxLayout()
        mode_row.addWidget(theme.field("Freed money goes to"))
        mode_row.addWidget(self.rollover_mode)
        controls.addLayout(mode_row)
        row.addLayout(controls)
        return row

    def _build_metrics(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(12)
        self.card_debt = MetricCard("Household debt", tone="warn")
        self.card_commitment = MetricCard("Monthly commitment", tone="accent")
        self.card_free = MetricCard("Debt-free", tone="info")
        self.card_isolated = MetricCard("Without rollover")
        self.card_cost = MetricCard("Lifetime interest", tone="warn")
        self.card_saved = MetricCard("Rollover saves", tone="accent")
        for index, card in enumerate((self.card_debt, self.card_commitment, self.card_free,
                                      self.card_isolated, self.card_cost, self.card_saved)):
            grid.addWidget(card, index // 3, index % 3)
        return grid

    def _build_plans_card(self) -> Card:
        card = Card(
            "Plans",
            "Tick Active to include a plan, Rolls over to pass its budget on once paid off. "
            "Double-click a plan to open it.",
        )
        self.table = make_table(
            ["Plan", "Loan types", "Balance", "Budget / mo", "On its own", "In household",
             "Active", "Rolls over", "Interest", "Received", "Passed on"]
        )
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellDoubleClicked.connect(self._open_plan)
        card.add(self.table, 1)
        return card

    def _build_charts_card(self) -> Card:
        card = Card("Household timeline", "")
        self.balance_chart = HouseholdBalanceChart()
        self.cash_chart = HouseholdCashFlowChart()
        tabs = QTabWidget()
        tabs.addTab(self.balance_chart, "Balance by plan")
        tabs.addTab(self.cash_chart, "Monthly payments by plan")
        card.add(tabs, 1)
        self.chart_card = card
        return card

    # --- events ------------------------------------------------------------ #
    def _rollover_toggled(self, checked: bool) -> None:
        if not self._loading:
            self.state.set_rollover(checked)

    def _mode_changed(self) -> None:
        if not self._loading:
            self.state.set_rollover_strategy(self.rollover_mode.currentData())

    def _plan_at(self, row: int):
        item = self.table.item(row, 0)
        return self.state.plan_by_id(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() not in (ACTIVE_COLUMN, ROLLOVER_COLUMN):
            return
        plan = self._plan_at(item.row())
        if plan is None:
            return
        checked = item.checkState() == Qt.CheckState.Checked
        if item.column() == ACTIVE_COLUMN:
            plan.active = checked
        else:
            plan.rollover = checked
        # Saving rebuilds this table, so don't do it inside its own signal.
        QTimer.singleShot(0, lambda: self.state.save_plan(plan))

    def _open_plan(self, row: int, column: int) -> None:
        if column in (ACTIVE_COLUMN, ROLLOVER_COLUMN):
            return
        plan = self._plan_at(row)
        if plan is not None and plan.plan_id is not None:
            self.openPlan.emit(plan.plan_id)

    # --- rendering --------------------------------------------------------- #
    def refresh(self) -> None:
        state = self.state
        household, isolated = state.household, state.household_isolated

        self._loading = True
        self.rollover.setChecked(state.rollover_enabled)
        self.rollover_mode.setCurrentIndex(max(self.rollover_mode.findData(state.rollover_strategy), 0))
        self.rollover_mode.setEnabled(state.rollover_enabled)
        self._loading = False

        active = [plan for plan in state.plans if plan.active]
        self.sub.setText(
            f"{len(active)} of {len(state.plans)} plans active · "
            "every active plan simulated together on one calendar"
        )
        has_debt = bool(household and household.starting_balance > 0)
        self.empty.setVisible(not has_debt)

        self._fill_metrics(household, isolated)
        self._fill_table()

        colors = {plan.plan_id: state.plan_color(plan) for plan in state.plans}
        self.balance_chart.render(household, colors, isolated if state.rollover_enabled else None)
        self.cash_chart.render(household, colors)
        if household and household.total_rolled > 0:
            self.chart_card.set_subtitle(
                f"{money(household.total_rolled)} is redirected from finished plans over the "
                "timeline. The dashed line is the same household without rollover."
            )
        else:
            self.chart_card.set_subtitle("Balance and payments for every active plan, month by month.")

    def _fill_metrics(self, household, isolated) -> None:
        state = self.state
        loans = state.active_loans()
        self.card_debt.set_value(money(engine.total_balance(loans)))
        self.card_debt.set_note(f"{len([l for l in loans if l.is_open])} open loans across active plans")

        commitment = household.monthly_commitment if household else 0.0
        minimums = engine.total_minimum_payment(loans)
        self.card_commitment.set_value(money(commitment))
        self.card_commitment.set_note(f"{money(minimums)} of it is contractual minimums")

        def payoff(card, schedule, fallback_note=""):
            if schedule and schedule.completed and schedule.payoff_date:
                card.set_value(schedule.payoff_date.strftime("%b %Y"))
                card.set_note(duration(schedule.months_to_payoff) + fallback_note)
            else:
                card.set_value("—" if not schedule or schedule.starting_balance <= 0 else "Never")
                card.set_note("")

        payoff(self.card_free, household, " with rollover" if state.rollover_enabled else "")
        payoff(self.card_isolated, isolated, " — each plan on its own")
        self.card_isolated.setVisible(state.rollover_enabled)

        if household:
            cost = household.total_cost
            pmi = f" incl. {money(household.total_fees)} PMI" if household.total_fees else ""
            self.card_cost.set_value(money(cost))
            self.card_cost.set_note(f"From today across all active plans{pmi}")
        if household and isolated and state.rollover_enabled and household.completed and isolated.completed:
            saved = isolated.total_cost - household.total_cost
            sooner = months_between(household.payoff_date, isolated.payoff_date)
            self.card_saved.set_value(money_compact(saved))
            self.card_saved.set_note(f"and debt-free {duration(sooner)} sooner" if sooner > 0 else "", "good")
        else:
            self.card_saved.set_value("—")
            self.card_saved.set_note("Turn on rollover to compare" if not state.rollover_enabled else "")

    def _fill_table(self) -> None:
        state = self.state
        household = state.household
        self._loading = True
        self.table.setRowCount(len(state.plans))
        for row, plan in enumerate(state.plans):
            loans = state.plan_loans(plan.plan_id)
            own = state.schedules.get(plan.plan_id)
            outcome = household.outcomes.get(plan.plan_id) if household else None
            types = ", ".join(sorted({SPECS[l.loan_type].label for l in loans})) or "—"
            color = state.plan_color(plan)

            name = cell(plan.name, bold=True, color=color)
            name.setData(Qt.ItemDataRole.UserRole, plan.plan_id)
            own_text = own.payoff_date.strftime("%b %Y") if own and own.completed and own.payoff_date else (
                "Paid off" if own and own.starting_balance <= 0 else "Never")
            if outcome is None:
                house_text = "Inactive" if not plan.active else "—"
            elif outcome.payoff_date:
                house_text = outcome.payoff_date.strftime("%b %Y")
            else:
                house_text = "Paid off" if outcome.starting_balance <= 0 else "Never"
            sooner = (
                own and own.payoff_date and outcome and outcome.payoff_date
                and outcome.payoff_date < own.payoff_date
            )

            values = [
                name,
                cell(types, muted=True),
                cell(money(engine.total_balance(loans)), align_right=True, bold=True),
                cell(money(plan.monthly_budget), align_right=True),
                cell(own_text, align_right=True, muted=not plan.active),
                cell(house_text, align_right=True, bold=bool(sooner),
                     color=theme.ACCENT if sooner else "",
                     tooltip=f"{months_between(outcome.payoff_date, own.payoff_date)} months sooner thanks to rollover"
                     if sooner else ""),
                self._check(plan.active),
                self._check(plan.rollover),
                cell(money(outcome.total_interest) if outcome else "—", align_right=True, color=theme.WARN),
                cell(money(outcome.rolled_in) if outcome and outcome.rolled_in else "—",
                     align_right=True, color=theme.ACCENT if outcome and outcome.rolled_in else ""),
                cell(money(outcome.rolled_out) if outcome and outcome.rolled_out else "—",
                     align_right=True, muted=True),
            ]
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
        self._loading = False
        self.table.refit()

    @staticmethod
    def _check(checked: bool) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item
