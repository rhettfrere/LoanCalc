"""Visualizations tab: interactive burn-down, cost split, and payment mix."""
from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from loancalc.core import theme
from loancalc.formatting import duration, money
from loancalc.state import AppState
from loancalc.ui.charts import (
    BurndownChart,
    MonthlySplitChart,
    PrincipalInterestChart,
    ScenarioChart,
)
from loancalc.ui.widgets import Card


class ChartsTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        self.burndown = BurndownChart()
        self.cost_split = PrincipalInterestChart()
        self.monthly_split = MonthlySplitChart()
        self.scenarios = ScenarioChart()

        self.burndown_card = Card("Balance burn-down", "")
        self.burndown_card.add(self.burndown, 1)

        self.scenario_card = Card(
            "Repayment over time",
            "Balance remaining each month for every plan, starting from today's "
            "real balances. Hover to read them all at once.",
        )
        self.scenario_card.add(self.scenarios, 1)

        self.cost_card = Card("Lifetime principal vs. interest", "")
        self.cost_card.add(self.cost_split, 1)

        self.mix_card = Card("Monthly payment composition", "")
        self.mix_card.add(self.monthly_split, 1)

        tabs = QTabWidget()
        for widget, label in (
            (self.burndown_card, "Burn-down"),
            (self.scenario_card, "Repayment over time"),
            (self.cost_card, "Principal vs. interest"),
            (self.mix_card, "Payment mix"),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(14, 14, 14, 14)
            page_layout.addWidget(widget)
            tabs.addTab(page, label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(tabs)

        state.scheduleChanged.connect(self.refresh)
        state.scenariosChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        schedule = self.state.schedule
        minimums = self.state.minimums_schedule

        self.burndown.render(schedule)
        self.cost_split.render(schedule, minimums)
        self.monthly_split.render(schedule)
        self.scenarios.render(self._scenario_series())

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
            saved = minimums.total_interest - schedule.total_interest
            sooner = minimums.months_to_payoff - schedule.months_to_payoff
            self.cost_card.set_subtitle(
                f"Your plan saves {money(saved)} in interest and finishes "
                f"{duration(sooner)} earlier than paying minimums only."
            )
        else:
            self.cost_card.set_subtitle("Total cost of the debt by the time it is retired.")

        self.mix_card.set_subtitle(
            "Interest shrinks as principal falls — hover to read any month exactly."
        )

    def _scenario_series(self):
        """Active plan, minimums, and every saved sandbox scenario."""
        series = []
        if self.state.schedule:
            series.append(("Active plan", self.state.schedule, theme.TEXT, True))
        if self.state.minimums_schedule:
            series.append(("Minimums only", self.state.minimums_schedule, theme.WARN, True))
        for index, scenario in enumerate(self.state.scenarios):
            series.append(
                (
                    scenario.name,
                    self.state.simulate_scenario(scenario),
                    theme.CHART_SERIES[index % len(theme.CHART_SERIES)],
                    False,
                )
            )
        return series
