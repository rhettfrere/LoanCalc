"""Overview panel: headline numbers plus the ranked payoff queue."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from loancalc import engine
from loancalc.core import theme
from loancalc.formatting import duration, long_date, money, money_compact, percent
from loancalc.state import AppState
from loancalc.ui.widgets import Card, MetricCard, cell, make_table, money_spinbox


class DashboardTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())
        layout.addLayout(self._build_metrics())
        layout.addWidget(self._build_queue_card(), 1)

        state.scheduleChanged.connect(self.refresh)
        state.loansChanged.connect(self.refresh)
        self.refresh()

    # --- construction ------------------------------------------------------ #
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(theme.hero("Repayment Overview"))
        self.headline = theme.subtitle("")
        titles.addWidget(self.headline)
        row.addLayout(titles, 1)

        self.strategy_box = QComboBox()
        for key, label in engine.STRATEGY_LABELS.items():
            self.strategy_box.addItem(label, key)
        self.strategy_box.setCurrentIndex(
            max(self.strategy_box.findData(self.state.strategy), 0)
        )
        self.strategy_box.currentIndexChanged.connect(self._strategy_changed)
        self.strategy_box.setMinimumWidth(260)

        self.budget_box = money_spinbox(self.state.monthly_budget, large=True)
        self.budget_box.setMinimumWidth(170)
        self.budget_box.editingFinished.connect(self._budget_changed)

        controls = QHBoxLayout()
        controls.setSpacing(16)
        for label, widget in (("Strategy", self.strategy_box), ("Monthly allocation", self.budget_box)):
            block = QVBoxLayout()
            block.setSpacing(3)
            block.addWidget(theme.field(label))
            block.addWidget(widget)
            controls.addLayout(block)
        row.addLayout(controls)
        return row

    def _build_metrics(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(12)

        self.card_debt = MetricCard("Total debt", tone="warn")
        self.card_minimum = MetricCard("Total minimum / mo")
        self.card_target = MetricCard("Target payment / mo", tone="accent")
        self.card_payoff = MetricCard("Projected payoff", tone="info")
        self.card_interest = MetricCard("Lifetime interest", tone="warn")
        self.card_saved = MetricCard("vs. minimums only", tone="accent")

        cards = (
            self.card_debt, self.card_minimum, self.card_target,
            self.card_payoff, self.card_interest, self.card_saved,
        )
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 3, index % 3)
        return grid

    def _build_queue_card(self) -> Card:
        self.queue_card = Card(
            "Payoff queue",
            "Loans in attack order. The target gets every dollar left after minimums.",
        )
        self.table = make_table(
            ["#", "Loan", "Rate", "Balance", "Accrued int.", "Minimum", "Daily int.", "Projected payoff"]
        )
        self.queue_card.add(self.table, 1)
        return self.queue_card

    # --- events ------------------------------------------------------------ #
    def _strategy_changed(self) -> None:
        self.state.set_strategy(self.strategy_box.currentData())

    def _budget_changed(self) -> None:
        if abs(self.budget_box.value() - self.state.monthly_budget) > 0.004:
            self.state.set_monthly_budget(self.budget_box.value())

    # --- rendering --------------------------------------------------------- #
    def refresh(self) -> None:
        state = self.state
        schedule = state.schedule
        minimums = state.minimums_schedule

        self.budget_box.blockSignals(True)
        self.budget_box.setValue(state.monthly_budget)
        self.budget_box.blockSignals(False)

        total = state.total_balance
        minimum = state.total_minimum
        rate = engine.weighted_average_rate(state.loans)
        daily = engine.daily_interest_cost(state.loans)

        self.headline.setText(
            f"{len([x for x in state.loans if x.is_open])} open loans · "
            f"weighted average rate {percent(rate)} · "
            f"interest accruing at {money(daily)} per day"
        )

        self.card_debt.set_value(money(total))
        self.card_debt.set_note(f"{money(daily)}/day in interest")

        self.card_minimum.set_value(money(minimum))
        self.card_minimum.set_note("Contractual floor across all servicers")

        self.card_target.set_value(money(state.monthly_budget))
        extra = state.monthly_budget - minimum
        if extra >= 0:
            self.card_target.set_note(f"{money(extra)} of attack capital", "good")
        else:
            self.card_target.set_note(f"{money(-extra)} below the minimums", "bad")

        if schedule and schedule.completed and schedule.payoff_date:
            self.card_payoff.set_value(schedule.payoff_date.strftime("%b %Y"))
            self.card_payoff.set_note(
                f"{duration(schedule.months_to_payoff)} · {long_date(schedule.payoff_date)}"
            )
        else:
            self.card_payoff.set_value("Never")
            self.card_payoff.set_note("Allocation does not outpace interest", "bad")

        lifetime = state.lifetime_interest()
        self.card_interest.set_value(money(lifetime))
        delta = state.interest_delta()
        months_delta = state.payoff_delta_months()
        if delta is None:
            self.card_interest.set_note("Baseline not captured yet")
        elif delta > 0.5:
            note = f"{money(delta)} better than baseline"
            if months_delta:
                note += f" · {months_delta:+d} mo"
            self.card_interest.set_note(note, "good")
        elif delta < -0.5:
            note = f"{money(-delta)} worse than baseline"
            if months_delta:
                note += f" · {months_delta:+d} mo"
            self.card_interest.set_note(note, "bad")
        else:
            self.card_interest.set_note("Tracking the baseline plan")

        if minimums and minimums.completed and schedule and schedule.completed:
            saved = minimums.total_interest - schedule.total_interest
            self.card_saved.set_value(money_compact(saved))
            self.card_saved.set_note(
                f"and {duration(minimums.months_to_payoff - schedule.months_to_payoff)} sooner",
                "good",
            )
        else:
            self.card_saved.set_value("—")
            self.card_saved.set_note("")

        self._fill_queue()

    def _fill_queue(self) -> None:
        ranked = self.state.priority_loans()
        payoff_month = self._payoff_months()

        self.table.setRowCount(len(ranked))
        for row, loan in enumerate(ranked):
            is_target = row == 0
            values = [
                cell("TARGET" if is_target else str(row + 1),
                     bold=is_target, color=theme.ACCENT if is_target else ""),
                cell(loan.name, bold=is_target, tooltip=loan.servicer or loan.name),
                cell(percent(loan.annual_rate), align_right=True, bold=True,
                     color=theme.WARN if loan.annual_rate >= 0.06 else ""),
                cell(money(loan.payoff_amount), align_right=True),
                cell(money(loan.accrued_interest), align_right=True, muted=True),
                cell(money(loan.minimum_payment), align_right=True),
                cell(money(loan.daily_interest), align_right=True, muted=True),
                cell(payoff_month.get(loan.name, "—"), align_right=True,
                     color=theme.ACCENT if is_target else ""),
            ]
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
        self.table.refit()

    def _payoff_months(self) -> dict[str, str]:
        """Month each loan hits zero in the current forecast."""
        schedule = self.state.schedule
        if not schedule:
            return {}
        found: dict[str, str] = {}
        for month in schedule.months:
            for name, balance in month.balances.items():
                if balance <= 0 and name not in found:
                    found[name] = month.period.strftime("%b %Y")
        return found
