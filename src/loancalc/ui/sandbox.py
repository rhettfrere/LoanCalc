"""Scenario sandbox: workshop a month-by-month plan and compare hypotheticals.

Pin known windfalls (a tax refund in April, a bonus in October) or lean months
to specific dates, leave the rest at the base payment, and watch the payoff
date and lifetime interest move against the active plan.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from loancalc import engine
from loancalc.core import theme
from loancalc.formatting import duration, money, month_label
from loancalc.models import Scenario, Schedule
from loancalc.state import AppState
from loancalc.ui.charts import ScenarioChart
from loancalc.ui.widgets import Card, MetricCard, cell, make_table

PAYMENT_COLUMN = 1
NOTE_COLUMN = 2

PRESETS = (
    ("Tax refund", 3000.0),
    ("Bonus", 10000.0),
    ("Lean month", 0.0),
)


class MoneyDelegate(QStyledItemDelegate):
    """Spin-box editor so payment cells can never hold junk."""

    def createEditor(self, parent, option, index):  # noqa: N802 - Qt API
        editor = QDoubleSpinBox(parent)
        editor.setRange(0.0, 1_000_000.0)
        editor.setDecimals(2)
        editor.setSingleStep(250.0)
        editor.setPrefix("$ ")
        editor.setGroupSeparatorShown(True)
        editor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return editor

    def setEditorData(self, editor, index):  # noqa: N802 - Qt API
        editor.setValue(float(index.data(Qt.ItemDataRole.UserRole) or 0.0))

    def setModelData(self, editor, model, index):  # noqa: N802 - Qt API
        editor.interpretText()
        model.setData(index, round(editor.value(), 2), Qt.ItemDataRole.UserRole)


class SandboxTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.scenario: Scenario | None = None
        self._loading = False
        self._schedule: Schedule | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_metrics())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_planner_card())
        splitter.addWidget(self._build_right_column())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([520, 780])
        layout.addWidget(splitter, 1)

        state.scenariosChanged.connect(self._reload_scenarios)
        state.scheduleChanged.connect(self.recalculate)
        state.loansChanged.connect(self.recalculate)
        self._reload_scenarios()

    # --- construction ------------------------------------------------------ #
    def _build_header(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(2)
        column.addWidget(theme.hero("Scenario Sandbox"))
        column.addWidget(
            theme.subtitle(
                "Every projection starts from your real balances today — payments "
                "already logged and interest already accrued are baked in."
            )
        )

        row = QHBoxLayout()
        row.setSpacing(8)

        self.picker = QComboBox()
        self.picker.setMinimumWidth(220)
        self.picker.currentIndexChanged.connect(self._scenario_selected)
        row.addWidget(theme.field("Scenario"))
        row.addWidget(self.picker)

        for label, slot in (
            ("New", self._new),
            ("Duplicate", self._duplicate),
            ("Rename", self._rename),
            ("Delete", self._delete),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)

        row.addSpacing(16)
        row.addWidget(theme.field("Base payment"))
        self.base_payment = QDoubleSpinBox()
        self.base_payment.setRange(0.0, 1_000_000.0)
        self.base_payment.setDecimals(2)
        self.base_payment.setSingleStep(250.0)
        self.base_payment.setPrefix("$ ")
        self.base_payment.setGroupSeparatorShown(True)
        self.base_payment.setMinimumWidth(150)
        self.base_payment.valueChanged.connect(self._base_changed)
        row.addWidget(self.base_payment)

        self.strategy_box = QComboBox()
        for key, label in engine.STRATEGY_LABELS.items():
            self.strategy_box.addItem(label, key)
        self.strategy_box.currentIndexChanged.connect(self._strategy_changed)
        row.addWidget(theme.field("Strategy"))
        row.addWidget(self.strategy_box)

        row.addStretch(1)
        self.adopt_button = theme.primary(QPushButton("Adopt as active plan"))
        self.adopt_button.clicked.connect(self._adopt)
        row.addWidget(self.adopt_button)

        column.addSpacing(6)
        column.addLayout(row)
        return column

    def _build_metrics(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.card_payoff = MetricCard("Scenario payoff", tone="info")
        self.card_interest = MetricCard("Lifetime interest", tone="warn")
        self.card_total = MetricCard("Total paid")
        self.card_delta = MetricCard("vs. active plan", tone="accent")

        for card in (self.card_payoff, self.card_interest, self.card_total, self.card_delta):
            row.addWidget(card)
        return container

    def _build_planner_card(self) -> Card:
        card = Card(
            "Monthly plan",
            "Edit any month to pin it. Pinned months are highlighted; everything "
            "else follows the base payment.",
        )

        self.planner = make_table(
            ["Month", "Payment", "Note", "Interest", "Principal", "Balance after"],
            editable=True,
        )
        self.planner.setItemDelegateForColumn(PAYMENT_COLUMN, MoneyDelegate())
        self.planner.itemChanged.connect(self._cell_changed)
        card.add(self.planner, 1)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        for label, amount in PRESETS:
            button = QPushButton(f"{label}  {money(amount)}")
            button.setToolTip(f"Pin {money(amount)} to the selected month")
            button.clicked.connect(lambda _=False, a=amount, n=label: self._apply_preset(a, n))
            tools.addWidget(button)
        tools.addStretch(1)
        unpin = QPushButton("Unpin month")
        unpin.clicked.connect(self._unpin_selected)
        tools.addWidget(unpin)
        clear = QPushButton("Clear all pins")
        clear.clicked.connect(self._clear_pins)
        tools.addWidget(clear)
        card.add_layout(tools)
        return card

    def _build_right_column(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        chart_card = Card(
            "Repayment over time",
            "Balance remaining each month. Hover to read every plan at once.",
        )
        self.chart = ScenarioChart()
        chart_card.add(self.chart, 1)

        compare_card = Card("Comparison", "All saved scenarios against the active plan.")
        self.comparison = make_table(
            ["Plan", "Base / mo", "Pins", "Payoff", "Interest", "Interest Δ", "Months Δ"]
        )
        compare_card.add(self.comparison, 1)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(chart_card)
        splitter.addWidget(compare_card)
        splitter.setSizes([420, 260])
        layout.addWidget(splitter)
        return container

    # --- scenario lifecycle ------------------------------------------------ #
    def _reload_scenarios(self) -> None:
        if not self.state.scenarios:
            self.state.new_scenario("Plan A")
            return

        self._loading = True
        current = self.scenario.scenario_id if self.scenario else None
        self.picker.clear()
        for scenario in self.state.scenarios:
            self.picker.addItem(scenario.name, scenario.scenario_id)
        index = self.picker.findData(current)
        self.picker.setCurrentIndex(index if index >= 0 else 0)
        self._loading = False
        self._scenario_selected()

    def _scenario_selected(self) -> None:
        if self._loading:
            return
        scenario_id = self.picker.currentData()
        self.scenario = next(
            (s for s in self.state.scenarios if s.scenario_id == scenario_id), None
        )
        if self.scenario is None:
            return

        self._loading = True
        self.base_payment.setValue(self.scenario.monthly_budget)
        index = self.strategy_box.findData(self.scenario.strategy or self.state.strategy)
        self.strategy_box.setCurrentIndex(max(index, 0))
        self._loading = False
        self.recalculate()

    def _new(self) -> None:
        scenario = self.state.new_scenario()
        self.scenario = scenario
        self._reload_scenarios()

    def _duplicate(self) -> None:
        if self.scenario is None:
            return
        copy = self.scenario.copy(f"{self.scenario.name} (copy)")
        self.state.save_scenario(copy)
        self.scenario = copy
        self._reload_scenarios()

    def _rename(self) -> None:
        if self.scenario is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Rename scenario", "Name:", text=self.scenario.name
        )
        if accepted and name.strip():
            self.scenario.name = name.strip()
            self.state.save_scenario(self.scenario)
            self._reload_scenarios()

    def _delete(self) -> None:
        if self.scenario is None:
            return
        if len(self.state.scenarios) == 1:
            QMessageBox.information(
                self, "Keep one", "Keep at least one scenario — rename it instead."
            )
            return
        confirm = QMessageBox.question(
            self,
            "Delete scenario",
            f"Delete '{self.scenario.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.delete_scenario(self.scenario)
            self.scenario = None
            self._reload_scenarios()

    def _adopt(self) -> None:
        if self.scenario is None:
            return
        pinned = len(self.scenario.overrides)
        detail = (
            f"Set the active plan to {money(self.scenario.monthly_budget)} per month"
            f" using the {engine.STRATEGY_LABELS[self.scenario.strategy]} strategy?"
        )
        if pinned:
            detail += (
                f"\n\nNote: the {pinned} pinned month(s) stay in the sandbox — log them "
                "in the Action Center when they actually happen."
            )
        confirm = QMessageBox.question(
            self, "Adopt scenario", detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.adopt_scenario(self.scenario)

    # --- editing ----------------------------------------------------------- #
    def _base_changed(self) -> None:
        if self._loading or self.scenario is None:
            return
        self.scenario.monthly_budget = round(self.base_payment.value(), 2)
        self.state.save_scenario(self.scenario)
        self.recalculate()

    def _strategy_changed(self) -> None:
        if self._loading or self.scenario is None:
            return
        self.scenario.strategy = self.strategy_box.currentData()
        self.state.save_scenario(self.scenario)
        self.recalculate()

    def _cell_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self.scenario is None:
            return
        period = self._period_at(item.row())
        if period is None:
            return

        if item.column() == PAYMENT_COLUMN:
            amount = item.data(Qt.ItemDataRole.UserRole)
            if amount is None:
                return
            amount = round(float(amount), 2)
            if abs(amount - self.scenario.monthly_budget) < 0.005:
                self.scenario.unpin(period)
            else:
                self.scenario.pin(period, amount, self.scenario.notes.get(period, ""))
        elif item.column() == NOTE_COLUMN:
            note = item.text().strip()
            if self.scenario.is_pinned(period):
                if note:
                    self.scenario.notes[period] = note
                else:
                    self.scenario.notes.pop(period, None)
            elif note:
                self.scenario.pin(period, self.scenario.monthly_budget, note)
        else:
            return

        self.state.save_scenario(self.scenario)
        self.recalculate()

    def _period_at(self, row: int) -> date | None:
        item = self.planner.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return date.fromisoformat(value) if value else None

    def _selected_period(self) -> date | None:
        return self._period_at(self.planner.currentRow())

    def _apply_preset(self, amount: float, label: str) -> None:
        period = self._selected_period()
        if period is None or self.scenario is None:
            QMessageBox.information(
                self, "Pick a month", "Select a month in the plan first."
            )
            return
        # A windfall is on top of the normal payment; a lean month replaces it.
        total = self.scenario.monthly_budget + amount if amount > 0 else 0.0
        self.scenario.pin(period, total, label)
        self.state.save_scenario(self.scenario)
        self.recalculate()

    def _unpin_selected(self) -> None:
        period = self._selected_period()
        if period is None or self.scenario is None:
            return
        self.scenario.unpin(period)
        self.state.save_scenario(self.scenario)
        self.recalculate()

    def _clear_pins(self) -> None:
        if self.scenario is None or not self.scenario.overrides:
            return
        confirm = QMessageBox.question(
            self,
            "Clear pins",
            f"Remove all {len(self.scenario.overrides)} pinned months from "
            f"'{self.scenario.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.scenario.overrides.clear()
        self.scenario.notes.clear()
        self.state.save_scenario(self.scenario)
        self.recalculate()

    # --- rendering --------------------------------------------------------- #
    def recalculate(self) -> None:
        if self.scenario is None:
            return
        self._schedule = self.state.simulate_scenario(self.scenario)
        self._fill_planner()
        self._fill_metrics()
        self._fill_comparison()
        self._fill_chart()

    def _fill_planner(self) -> None:
        scenario = self.scenario
        schedule = self._schedule
        if scenario is None or schedule is None:
            return

        periods = self.state.planning_periods()
        by_period = {month.period: month for month in schedule.months}

        self._loading = True
        self.planner.setRowCount(len(periods))
        for row, period in enumerate(periods):
            pinned = scenario.is_pinned(period)
            month = by_period.get(period)
            amount = scenario.payment_for(period)
            settled = month is None

            label = cell(month_label(period), bold=pinned)
            label.setData(Qt.ItemDataRole.UserRole, period.isoformat())
            if period == self.state.current_period:
                label.setText(f"{month_label(period)}  ·  this month")

            payment = cell(
                "—" if settled else money(amount),
                align_right=True,
                bold=pinned,
                color=theme.ACCENT if pinned else "",
            )
            payment.setData(Qt.ItemDataRole.UserRole, amount)
            if settled:
                payment.setFlags(payment.flags() & ~Qt.ItemFlag.ItemIsEditable)

            note = QTableWidgetItem(scenario.notes.get(period, ""))
            if settled:
                note.setFlags(note.flags() & ~Qt.ItemFlag.ItemIsEditable)

            values = [
                label,
                payment,
                note,
                cell(money(month.interest_paid) if month else "—", align_right=True,
                     color=theme.WARN if month else "", muted=settled),
                cell(money(month.principal_paid) if month else "—", align_right=True,
                     color=theme.ACCENT if month else "", muted=settled),
                cell(
                    "DEBT FREE" if settled else money(month.ending_balance),
                    align_right=True,
                    bold=settled,
                    color=theme.ACCENT if settled else "",
                ),
            ]
            for column, item in enumerate(values):
                if column != NOTE_COLUMN:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == PAYMENT_COLUMN and not settled:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.planner.setItem(row, column, item)
        self._loading = False
        self.planner.refit()

    def _fill_metrics(self) -> None:
        schedule = self._schedule
        active = self.state.schedule
        if schedule is None:
            return

        if schedule.completed and schedule.payoff_date:
            self.card_payoff.set_value(schedule.payoff_date.strftime("%b %Y"))
            self.card_payoff.set_note(duration(schedule.months_to_payoff))
        else:
            self.card_payoff.set_value("Never")
            self.card_payoff.set_note("Payments do not outpace interest", "bad")

        self.card_interest.set_value(money(schedule.total_interest))
        pinned = len(self.scenario.overrides) if self.scenario else 0
        self.card_interest.set_note(f"{pinned} pinned month(s)")

        self.card_total.set_value(money(schedule.total_paid))
        self.card_total.set_note("Principal + interest from today")

        if active and active.completed and schedule.completed:
            swing = active.total_interest - schedule.total_interest
            months = active.months_to_payoff - schedule.months_to_payoff
            self.card_delta.set_value(
                ("Saves " if swing >= 0 else "Costs ") + money(abs(swing))
            )
            self.card_delta.set_tone("accent" if swing >= 0 else "warn")
            if months:
                self.card_delta.set_note(
                    f"{duration(abs(months))} {'earlier' if months > 0 else 'later'}",
                    "good" if months > 0 else "bad",
                )
            else:
                self.card_delta.set_note("Same payoff month")
        else:
            self.card_delta.set_value("—")
            self.card_delta.set_note("")

    def _comparison_rows(self) -> list[tuple[str, Schedule, str, bool, int]]:
        """(label, schedule, colour, dashed, pinned months) for every plan."""
        rows: list[tuple[str, Schedule, str, bool, int]] = []
        if self.state.schedule:
            rows.append(("Active plan", self.state.schedule, theme.TEXT, True, 0))
        if self.state.minimums_schedule:
            rows.append(("Minimums only", self.state.minimums_schedule, theme.WARN, True, 0))
        for index, scenario in enumerate(self.state.scenarios):
            schedule = (
                self._schedule
                if self.scenario and scenario.scenario_id == self.scenario.scenario_id
                else self.state.simulate_scenario(scenario)
            )
            if schedule is None:
                continue
            color = theme.CHART_SERIES[index % len(theme.CHART_SERIES)]
            rows.append((scenario.name, schedule, color, False, len(scenario.overrides)))
        return rows

    def _fill_comparison(self) -> None:
        rows = self._comparison_rows()
        active = self.state.schedule

        self.comparison.setRowCount(len(rows))
        for index, (label, schedule, color, _, pinned) in enumerate(rows):
            is_current = (
                self.scenario is not None and label == self.scenario.name
            )
            if active and active.completed and schedule.completed:
                interest_delta = active.total_interest - schedule.total_interest
                months_delta = active.months_to_payoff - schedule.months_to_payoff
            else:
                interest_delta = months_delta = None

            values = [
                cell(label, bold=is_current, color=color),
                cell(money(schedule.monthly_budget), align_right=True),
                cell(str(pinned) if pinned else "—", align_right=True, muted=not pinned),
                cell(
                    schedule.payoff_date.strftime("%b %Y")
                    if schedule.completed and schedule.payoff_date
                    else "Never",
                    align_right=True,
                    bold=is_current,
                    tooltip=duration(schedule.months_to_payoff),
                ),
                cell(money(schedule.total_interest), align_right=True, color=theme.WARN),
                cell(
                    "—" if interest_delta is None else money(interest_delta),
                    align_right=True,
                    bold=True,
                    color=""
                    if interest_delta is None
                    else (theme.ACCENT if interest_delta >= 0 else theme.DANGER),
                ),
                cell(
                    "—" if months_delta is None else f"{months_delta:+d}",
                    align_right=True,
                    color=""
                    if months_delta is None
                    else (theme.ACCENT if months_delta >= 0 else theme.DANGER),
                ),
            ]
            for column, item in enumerate(values):
                self.comparison.setItem(index, column, item)
        self.comparison.refit()

    def _fill_chart(self) -> None:
        self.chart.render(
            [(label, schedule, color, dashed) for label, schedule, color, dashed, _ in self._comparison_rows()]
        )
