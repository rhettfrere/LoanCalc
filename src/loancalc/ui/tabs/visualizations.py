"""Visualizations for the selected plan: burn-down, scenarios, cost, mix, equity."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from loancalc.domain.loan_types import LoanType
from loancalc.services.state import AppState
from loancalc.ui import theme
from loancalc.ui.charts import (
    BurndownChart,
    EquityChart,
    MonthlySplitChart,
    PrincipalInterestChart,
    ScenarioChart,
)
from loancalc.ui.widgets import Card
from loancalc.util.formatting import duration, money


class VisualizationsTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        self.burndown = BurndownChart()
        self.cost_split = PrincipalInterestChart()
        self.monthly_split = MonthlySplitChart()
        self.scenarios = ScenarioChart()
        self.equity = EquityChart()

        self.burndown_card = Card("Balance burn-down", "")
        self.burndown_card.add(self.burndown, 1)
        self.scenario_card = Card(
            "Repayment over time",
            "Balance remaining each month for the active plan, minimums only, and every "
            "sandbox scenario — all from today's real balances.",
        )
        self.scenario_card.add(self.scenarios, 1)
        self.cost_card = Card("Lifetime principal vs. interest", "")
        self.cost_card.add(self.cost_split, 1)
        self.mix_card = Card("Monthly payment composition", "")
        self.mix_card.add(self.monthly_split, 1)

        self.equity_card = Card("Equity", "")
        self.loan_picker = QComboBox()
        self.loan_picker.setMinimumWidth(280)
        self.loan_picker.currentIndexChanged.connect(self._render_equity)
        picker_row = QHBoxLayout()
        picker_row.addWidget(theme.field("Loan"))
        picker_row.addWidget(self.loan_picker)
        picker_row.addStretch(1)
        self.equity_card.add_layout(picker_row)
        self.equity_card.add(self.equity, 1)

        self.tabs = QTabWidget()
        for widget, label in (
            (self.burndown_card, "Burn-down"),
            (self.scenario_card, "Repayment over time"),
            (self.cost_card, "Principal vs. interest"),
            (self.mix_card, "Payment mix"),
            (self.equity_card, "Equity"),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(14, 14, 14, 14)
            page_layout.addWidget(widget)
            self.tabs.addTab(page, label)
        self._equity_index = self.tabs.count() - 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.tabs)

        for signal in (state.scheduleChanged, state.scenariosChanged, state.currentPlanChanged):
            signal.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        schedule = self.state.schedule
        minimums = self.state.minimums_schedule
        colors = self._type_colors()

        self.burndown.render(schedule, colors)
        self.cost_split.render(schedule, minimums)
        self.monthly_split.render(schedule)
        self.scenarios.render(self._scenario_series())
        self._refresh_equity_picker()

        if schedule and schedule.completed:
            self.burndown_card.set_subtitle(
                f"Every loan to zero in {duration(schedule.months_to_payoff)} "
                f"at {money(schedule.monthly_budget)} per month."
            )
        else:
            self.burndown_card.set_subtitle(
                "The current allocation never clears the debt — raise it to see a payoff date."
            )

        if schedule and minimums and schedule.completed and minimums.completed:
            saved = minimums.total_cost - schedule.total_cost
            sooner = minimums.months_to_payoff - schedule.months_to_payoff
            pmi = " and PMI" if minimums.total_fees else ""
            self.cost_card.set_subtitle(
                f"Your plan saves {money(saved)} in interest{pmi} and finishes "
                f"{duration(sooner)} earlier than paying minimums only."
            )
        else:
            self.cost_card.set_subtitle("Total cost of the debt by the time it is retired.")

        self.mix_card.set_subtitle(
            "Interest shrinks as principal falls — hover to read any month exactly."
        )

    def _type_colors(self) -> dict[str, str] | None:
        """Colour bands by loan type when a plan mixes types."""
        loans = self.state.loans
        if len({loan.loan_type for loan in loans}) < 2:
            return None
        return {loan.name: loan.spec.color for loan in loans}

    def _refresh_equity_picker(self) -> None:
        secured = [loan for loan in self.state.loans if loan.spec.secured]
        current = self.loan_picker.currentData()
        self.loan_picker.blockSignals(True)
        self.loan_picker.clear()
        for loan in secured:
            suffix = "" if loan.asset_value > 0 else "  (no value entered)"
            self.loan_picker.addItem(f"{loan.name}{suffix}", loan.loan_id)
        index = self.loan_picker.findData(current)
        self.loan_picker.setCurrentIndex(index if index >= 0 else 0)
        self.loan_picker.blockSignals(False)
        self.tabs.setTabVisible(self._equity_index, bool(secured))
        self._render_equity()

    def _render_equity(self) -> None:
        loan_id = self.loan_picker.currentData()
        loan = next((l for l in self.state.loans if l.loan_id == loan_id), None)
        self.equity.render(loan, self.state.schedule, self.state.minimums_schedule)
        if loan is None:
            self.equity_card.set_subtitle("")
            return
        if loan.loan_type is LoanType.MORTGAGE:
            self.equity_card.set_subtitle(
                f"Home value at {loan.growth * 100:+.1f}%/yr against your balance. Dotted lines "
                "mark the 80% / 78% loan-to-value PMI thresholds."
            )
        else:
            self.equity_card.set_subtitle(
                f"{loan.spec.asset_label} at {loan.growth * 100:+.1f}%/yr against your balance. "
                "Red shading means you owe more than it's worth."
            )

    def _scenario_series(self):
        series = []
        if self.state.schedule:
            series.append(("Active plan", self.state.schedule, theme.TEXT, True))
        if self.state.minimums_schedule:
            series.append(("Minimums only", self.state.minimums_schedule, theme.WARN, True))
        for index, scenario in enumerate(self.state.scenarios):
            series.append(
                (scenario.name, self.state.simulate_scenario(scenario),
                 theme.CHART_SERIES[index % len(theme.CHART_SERIES)], False)
            )
        return series
