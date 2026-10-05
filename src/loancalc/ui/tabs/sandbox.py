"""Scenario sandbox: workshop a month-by-month plan and compare hypotheticals.

Pins mark known changes — a tax refund every April, a bonus in October, a lean
holiday month — on top of a base payment. They can be added, edited,
duplicated or deleted at any time as life changes, and each scenario is scored
both on its own and inside the household projection.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
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

from loancalc.domain import engine
from loancalc.domain.models import Pin, PinMode, PinRepeat, Scenario, Schedule
from loancalc.services.state import AppState
from loancalc.ui import theme
from loancalc.ui.charts import ScenarioChart
from loancalc.ui.dialogs.pin_dialog import REPEAT_LABELS, PinDialog, PresetsDialog
from loancalc.ui.widgets import Card, MetricCard, cell, make_table
from loancalc.util.formatting import duration, money, month_label

PAYMENT_COLUMN = 1
PINS_COLUMN = 2
MANUAL_LABEL = "Manual"


class MoneyDelegate(QStyledItemDelegate):
    """Spin-box editor so payment cells can never hold junk."""

    def createEditor(self, parent, option, index):  # noqa: N802 - Qt API
        editor = QDoubleSpinBox(parent)
        editor.setRange(0.0, 10_000_000.0)
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


def _pin_value(pin: Pin) -> str:
    if pin.mode is PinMode.MINIMUM:
        return "Minimums"
    return f"{'+' if pin.mode is PinMode.ADD else '='} {money(pin.amount)}"


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

        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self._build_planner_card())
        left.addWidget(self._build_pins_card())
        left.setSizes([440, 260])

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._build_right_column())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([540, 760])
        layout.addWidget(splitter, 1)

        state.scenariosChanged.connect(self._reload_scenarios)
        state.currentPlanChanged.connect(self._plan_changed)
        state.scheduleChanged.connect(self.recalculate)
        state.loansChanged.connect(self.recalculate)
        self._reload_scenarios()

    # ===================================================================== #
    # Construction
    # ===================================================================== #
    def _build_header(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(2)
        self.heading = theme.hero("Scenario Sandbox")
        column.addWidget(self.heading)
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
        for label, slot in (("New", self._new), ("Duplicate", self._duplicate),
                            ("Rename", self._rename), ("Delete", self._delete)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)

        row.addSpacing(16)
        row.addWidget(theme.field("Base payment"))
        self.base_payment = QDoubleSpinBox()
        self.base_payment.setRange(0.0, 10_000_000.0)
        self.base_payment.setDecimals(2)
        self.base_payment.setSingleStep(250.0)
        self.base_payment.setPrefix("$ ")
        self.base_payment.setGroupSeparatorShown(True)
        self.base_payment.setMinimumWidth(150)
        self.base_payment.editingFinished.connect(self._base_changed)
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
        self.card_household = MetricCard("Household debt-free", tone="info")
        for card in (self.card_payoff, self.card_interest, self.card_total,
                     self.card_delta, self.card_household):
            row.addWidget(card)
        return container

    def _build_planner_card(self) -> Card:
        card = Card(
            "Monthly plan",
            "Type a new amount into any month to pin it, or double-click a month to add a "
            "detailed pin. Pinned months are highlighted.",
        )
        self.planner = make_table(
            ["Month", "Payment", "Pins", "Interest", "Principal", "Balance after"],
            editable=True,
        )
        self.planner.setItemDelegateForColumn(PAYMENT_COLUMN, MoneyDelegate())
        self.planner.itemChanged.connect(self._cell_changed)
        self.planner.cellDoubleClicked.connect(self._planner_double_clicked)
        card.add(self.planner, 1)
        return card

    def _build_pins_card(self) -> Card:
        card = Card("Pins", "Known changes to the base payment. Edit them as life changes.")
        self.pins_table = make_table(["Starts", "Label", "Change", "Repeat", "Until"])
        self.pins_table.cellDoubleClicked.connect(lambda *_: self._edit_pin())
        card.add(self.pins_table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        for label, slot in (("Add pin…", self._add_pin), ("Edit…", self._edit_pin),
                            ("Duplicate", self._duplicate_pin), ("Delete", self._delete_pin)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        clear = theme.quiet(QPushButton("Clear all"))
        clear.clicked.connect(self._clear_pins)
        actions.addWidget(clear)
        card.add_layout(actions)

        self.presets_row = QHBoxLayout()
        self.presets_row.setSpacing(6)
        card.add_layout(self.presets_row)
        return card

    def _build_right_column(self) -> QWidget:
        chart_card = Card(
            "Repayment over time",
            "Balance remaining each month. Hover to read every plan at once.",
        )
        self.chart = ScenarioChart()
        chart_card.add(self.chart, 1)

        compare_card = Card("Comparison", "Every saved scenario for this plan against the active plan.")
        self.comparison = make_table(
            ["Plan", "Base / mo", "Pins", "Payoff", "Interest", "Interest Δ", "Months Δ"]
        )
        compare_card.add(self.comparison, 1)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(chart_card)
        splitter.addWidget(compare_card)
        splitter.setSizes([420, 260])
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        return container

    def _rebuild_presets(self) -> None:
        while self.presets_row.count():
            item = self.presets_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.presets_row.addWidget(theme.field("Quick pin:"))
        for preset in self.state.presets():
            text = preset.label if preset.mode is PinMode.MINIMUM else f"{preset.label} {_pin_value(preset.to_pin(date.today()))}"
            button = QPushButton(text)
            button.setToolTip("Pin this to the month selected in the plan above")
            button.clicked.connect(lambda _=False, p=preset: self._apply_preset(p))
            self.presets_row.addWidget(button)
        self.presets_row.addStretch(1)
        manage = theme.quiet(QPushButton("Manage presets…"))
        manage.clicked.connect(self._manage_presets)
        self.presets_row.addWidget(manage)

    # ===================================================================== #
    # Scenario lifecycle
    # ===================================================================== #
    def _plan_changed(self) -> None:
        self.scenario = None
        self._reload_scenarios()

    def _reload_scenarios(self) -> None:
        plan = self.state.current_plan
        self.heading.setText(f"Scenario Sandbox  ·  {plan.name}" if plan else "Scenario Sandbox")
        self._rebuild_presets()
        if plan is None:
            return
        scenarios = self.state.scenarios
        if not scenarios:
            self.state.new_scenario("Plan A")
            return

        self._loading = True
        current = self.scenario.scenario_id if self.scenario else None
        self.picker.clear()
        for scenario in scenarios:
            self.picker.addItem(scenario.name, scenario.scenario_id)
        index = self.picker.findData(current)
        self.picker.setCurrentIndex(index if index >= 0 else 0)
        self._loading = False
        self._scenario_selected()

    def _scenario_selected(self) -> None:
        if self._loading:
            return
        scenario_id = self.picker.currentData()
        self.scenario = next((s for s in self.state.scenarios if s.scenario_id == scenario_id), None)
        if self.scenario is None:
            return
        self._loading = True
        self.base_payment.setValue(self.scenario.monthly_budget)
        index = self.strategy_box.findData(self.scenario.strategy or self.state.strategy)
        self.strategy_box.setCurrentIndex(max(index, 0))
        self._loading = False
        self.recalculate()

    def _save(self) -> None:
        """Persist; the resulting scenariosChanged reloads and re-renders."""
        if self.scenario is not None:
            self.state.save_scenario(self.scenario)

    def _new(self) -> None:
        self.scenario = self.state.new_scenario()
        self._reload_scenarios()

    def _duplicate(self) -> None:
        if self.scenario is None:
            return
        self.scenario = self.scenario.copy(f"{self.scenario.name} (copy)")
        self.state.save_scenario(self.scenario)

    def _rename(self) -> None:
        if self.scenario is None:
            return
        name, ok = QInputDialog.getText(self, "Rename scenario", "Name:", text=self.scenario.name)
        if ok and name.strip():
            self.scenario.name = name.strip()
            self.state.save_scenario(self.scenario)

    def _delete(self) -> None:
        if self.scenario is None:
            return
        if len(self.state.scenarios) == 1:
            QMessageBox.information(self, "Keep one", "Keep at least one scenario — rename it instead.")
            return
        confirm = QMessageBox.question(
            self, "Delete scenario", f"Delete '{self.scenario.name}' and its pins?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            doomed, self.scenario = self.scenario, None
            self.state.delete_scenario(doomed)

    def _adopt(self) -> None:
        if self.scenario is None:
            return
        detail = (
            f"Set the {self.state.current_plan.name} plan to {money(self.scenario.monthly_budget)} "
            f"per month using {engine.STRATEGY_LABELS[self.scenario.strategy]}?"
        )
        if self.scenario.pins:
            detail += (
                f"\n\nThe {len(self.scenario.pins)} pin(s) stay in the sandbox — log them in the "
                "Action Center when they actually happen."
            )
        confirm = QMessageBox.question(
            self, "Adopt scenario", detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.adopt_scenario(self.scenario)

    def _base_changed(self) -> None:
        if self._loading or self.scenario is None:
            return
        value = round(self.base_payment.value(), 2)
        if abs(value - self.scenario.monthly_budget) > 0.004:
            self.scenario.monthly_budget = value
            self._save()

    def _strategy_changed(self) -> None:
        if self._loading or self.scenario is None:
            return
        self.scenario.strategy = self.strategy_box.currentData()
        self._save()

    # ===================================================================== #
    # Pins
    # ===================================================================== #
    def _minimum(self) -> float:
        return engine.total_minimum_payment(self.state.loans)

    def _selected_pin(self) -> Pin | None:
        row = self.pins_table.currentRow()
        if self.scenario is None or row < 0:
            return None
        item = self.pins_table.item(row, 0)
        index = item.data(Qt.ItemDataRole.UserRole) if item else None
        return self.scenario.pins[index] if index is not None and index < len(self.scenario.pins) else None

    def _period_at(self, row: int) -> date | None:
        item = self.planner.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return date.fromisoformat(value) if value else None

    def _selected_period(self) -> date | None:
        return self._period_at(self.planner.currentRow())

    def _open_pin_dialog(self, *, pin: Pin | None = None, period: date | None = None) -> Pin | None:
        if self.scenario is None:
            return None
        dialog = PinDialog(
            self, self.scenario, self.state.planning_periods(), self._minimum(),
            pin=pin, period=period or self._selected_period() or self.state.current_period,
            presets=self.state.presets(),
        )
        return dialog.result_pin() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def _add_pin(self, period: date | None = None) -> None:
        pin = self._open_pin_dialog(period=period)
        if pin is not None and self.scenario is not None:
            self.scenario.pins.append(pin)
            self._save()

    def _edit_pin(self, pin: Pin | None = None) -> None:
        pin = pin or self._selected_pin()
        if pin is None or self.scenario is None:
            QMessageBox.information(self, "Select a pin", "Pick a pin in the list first.")
            return
        updated = self._open_pin_dialog(pin=pin)
        if updated is not None:
            self.scenario.pins[self.scenario.pins.index(pin)] = updated
            self._save()

    def _duplicate_pin(self) -> None:
        pin = self._selected_pin()
        if pin is None or self.scenario is None:
            return
        self.scenario.pins.append(pin.copy())
        self._save()

    def _delete_pin(self) -> None:
        pin = self._selected_pin()
        if pin is None or self.scenario is None:
            return
        self.scenario.pins.remove(pin)
        self._save()

    def _clear_pins(self) -> None:
        if self.scenario is None or not self.scenario.pins:
            return
        confirm = QMessageBox.question(
            self, "Clear pins",
            f"Remove all {len(self.scenario.pins)} pins from '{self.scenario.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.scenario.pins.clear()
            self._save()

    def _apply_preset(self, preset) -> None:
        period = self._selected_period()
        if period is None or self.scenario is None:
            QMessageBox.information(self, "Pick a month", "Select a month in the plan first.")
            return
        self.scenario.pins.append(preset.to_pin(period))
        self._save()

    def _manage_presets(self) -> None:
        dialog = PresetsDialog(self, self.state.presets())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.state.save_presets(dialog.presets())

    def _planner_double_clicked(self, row: int, column: int) -> None:
        if column == PAYMENT_COLUMN:
            return
        period = self._period_at(row)
        if period is None or self.scenario is None:
            return
        pins = self.scenario.pins_for(period)
        if pins:
            self._edit_pin(pins[-1])
        else:
            self._add_pin(period)

    def _cell_changed(self, item: QTableWidgetItem) -> None:
        """Typing a payment pins it as a one-off 'Manual' replacement."""
        if self._loading or self.scenario is None or item.column() != PAYMENT_COLUMN:
            return
        period = self._period_at(item.row())
        amount = item.data(Qt.ItemDataRole.UserRole)
        if period is None or amount is None:
            return
        amount = round(float(amount), 2)
        manual = [
            p for p in self.scenario.pins
            if p.repeat is PinRepeat.ONCE and p.period == period
            and p.mode is PinMode.SET and p.label == MANUAL_LABEL
        ]
        for pin in manual:
            self.scenario.pins.remove(pin)
        without = self.scenario.payment_for(period, self._minimum())
        if abs(amount - without) > 0.004:
            self.scenario.pins.append(Pin(period, amount, PinMode.SET, MANUAL_LABEL))
        self._save()

    # ===================================================================== #
    # Rendering
    # ===================================================================== #
    def recalculate(self) -> None:
        if self.scenario is None or self.state.current_plan is None:
            return
        self._schedule = self.state.simulate_scenario(self.scenario)
        self._fill_planner()
        self._fill_pins()
        self._fill_metrics()
        rows = self._comparison_rows()
        self._fill_comparison(rows)
        self.chart.render([(label, schedule, color, dashed) for label, schedule, color, dashed, _ in rows])

    def _fill_planner(self) -> None:
        scenario, schedule = self.scenario, self._schedule
        if scenario is None or schedule is None:
            return
        periods = self.state.planning_periods()
        by_period = {month.period: month for month in schedule.months}
        minimum = self._minimum()

        self._loading = True
        self.planner.setRowCount(len(periods))
        for row, period in enumerate(periods):
            pins = scenario.pins_for(period)
            pinned = bool(pins)
            month = by_period.get(period)
            amount = scenario.payment_for(period, minimum)
            settled = month is None

            label = cell(month_label(period), bold=pinned)
            label.setData(Qt.ItemDataRole.UserRole, period.isoformat())
            if period == self.state.current_period:
                label.setText(f"{month_label(period)}  ·  this month")

            payment = cell(
                "—" if settled else money(amount), align_right=True, bold=pinned,
                color=theme.ACCENT if pinned else "",
            )
            payment.setData(Qt.ItemDataRole.UserRole, amount)

            pin_text = ", ".join(f"{p.label} {_pin_value(p)}" for p in pins)
            values = [
                label,
                payment,
                cell(pin_text or "", color=theme.ACCENT if pinned else "",
                     tooltip="Double-click to add or edit a pin for this month"),
                cell(money(month.interest_paid) if month else "—", align_right=True,
                     color=theme.WARN if month else "", muted=settled),
                cell(money(month.principal_paid) if month else "—", align_right=True,
                     color=theme.ACCENT if month else "", muted=settled),
                cell("DEBT FREE" if settled else money(month.ending_balance), align_right=True,
                     bold=settled, color=theme.ACCENT if settled else ""),
            ]
            for column, item in enumerate(values):
                editable = column == PAYMENT_COLUMN and not settled
                flags = item.flags()
                item.setFlags(flags | Qt.ItemFlag.ItemIsEditable if editable else flags & ~Qt.ItemFlag.ItemIsEditable)
                self.planner.setItem(row, column, item)
        self._loading = False
        self.planner.refit()

    def _fill_pins(self) -> None:
        scenario = self.scenario
        if scenario is None:
            return
        selected = self._selected_pin()
        order = sorted(range(len(scenario.pins)), key=lambda i: (scenario.pins[i].period, i))
        self.pins_table.setRowCount(len(order))
        for row, index in enumerate(order):
            pin = scenario.pins[index]
            first = cell(month_label(pin.period), bold=True)
            first.setData(Qt.ItemDataRole.UserRole, index)
            values = [
                first,
                cell(pin.label),
                cell(_pin_value(pin), align_right=True,
                     color=theme.ACCENT if pin.mode is PinMode.ADD else theme.WARN if pin.mode is PinMode.MINIMUM else ""),
                cell(REPEAT_LABELS[pin.repeat], muted=pin.repeat is PinRepeat.ONCE),
                cell(month_label(pin.until) if pin.until else ("—" if pin.repeat is PinRepeat.ONCE else "No end"),
                     muted=True),
            ]
            for column, item in enumerate(values):
                self.pins_table.setItem(row, column, item)
            if pin is selected:
                self.pins_table.selectRow(row)
        self.pins_table.refit()

    def _fill_metrics(self) -> None:
        schedule, active = self._schedule, self.state.schedule
        if schedule is None:
            return
        if schedule.completed and schedule.payoff_date:
            self.card_payoff.set_value(schedule.payoff_date.strftime("%b %Y"))
            self.card_payoff.set_note(duration(schedule.months_to_payoff))
        else:
            self.card_payoff.set_value("Never")
            self.card_payoff.set_note("Payments do not outpace interest", "bad")

        self.card_interest.set_value(money(schedule.total_interest))
        self.card_interest.set_note(
            f"{len(self.scenario.pins)} pin(s)" + (f" · {money(schedule.total_fees)} PMI" if schedule.total_fees else "")
        )
        self.card_total.set_value(money(schedule.total_paid))
        self.card_total.set_note("Principal + interest from today")

        if active and active.completed and schedule.completed:
            swing = active.total_cost - schedule.total_cost
            months = active.months_to_payoff - schedule.months_to_payoff
            self.card_delta.set_value(("Saves " if swing >= 0 else "Costs ") + money(abs(swing)))
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

        others = [p for p in self.state.plans if p.active and p.plan_id != self.state.current_plan_id
                  and self.state.plan_loans(p.plan_id)]
        if others and self.state.current_plan and self.state.current_plan.active:
            household = self.state.household_with_scenario(self.scenario)
            baseline = self.state.household
            if household.completed and household.payoff_date:
                self.card_household.set_value(household.payoff_date.strftime("%b %Y"))
                if baseline and baseline.completed and baseline.payoff_date:
                    diff = (baseline.payoff_date.year * 12 + baseline.payoff_date.month) - (
                        household.payoff_date.year * 12 + household.payoff_date.month)
                    saved = baseline.total_cost - household.total_cost
                    tone = "good" if saved >= 0 else "bad"
                    when = (f"{duration(abs(diff))} {'earlier' if diff > 0 else 'later'}" if diff else "same month")
                    self.card_household.set_note(
                        f"{when} · {'saves' if saved >= 0 else 'costs'} {money(abs(saved))} across all plans", tone
                    )
                else:
                    self.card_household.set_note("All active plans together")
            else:
                self.card_household.set_value("Never")
                self.card_household.set_note("", "")
            self.card_household.setVisible(True)
        else:
            self.card_household.setVisible(False)

    def _comparison_rows(self) -> list[tuple[str, Schedule, str, bool, int]]:
        """(label, schedule, colour, dashed, pin count) for every plan."""
        rows: list[tuple[str, Schedule, str, bool, int]] = []
        if self.state.schedule:
            rows.append(("Active plan", self.state.schedule, theme.TEXT, True, 0))
        if self.state.minimums_schedule:
            rows.append(("Minimums only", self.state.minimums_schedule, theme.WARN, True, 0))
        for index, scenario in enumerate(self.state.scenarios):
            is_current = self.scenario is not None and scenario.scenario_id == self.scenario.scenario_id
            schedule = self._schedule if is_current else self.state.simulate_scenario(scenario)
            if schedule is not None:
                color = theme.CHART_SERIES[index % len(theme.CHART_SERIES)]
                rows.append((scenario.name, schedule, color, False, len(scenario.pins)))
        return rows

    def _fill_comparison(self, rows) -> None:
        active = self.state.schedule
        self.comparison.setRowCount(len(rows))
        for index, (label, schedule, color, _, pins) in enumerate(rows):
            is_current = self.scenario is not None and label == self.scenario.name
            if active and active.completed and schedule.completed:
                interest_delta = active.total_cost - schedule.total_cost
                months_delta = active.months_to_payoff - schedule.months_to_payoff
            else:
                interest_delta = months_delta = None
            values = [
                cell(label, bold=is_current, color=color),
                cell(money(schedule.monthly_budget), align_right=True),
                cell(str(pins) if pins else "—", align_right=True, muted=not pins),
                cell(schedule.payoff_date.strftime("%b %Y") if schedule.completed and schedule.payoff_date
                     else "Never", align_right=True, bold=is_current,
                     tooltip=duration(schedule.months_to_payoff)),
                cell(money(schedule.total_interest), align_right=True, color=theme.WARN),
                cell("—" if interest_delta is None else money(interest_delta), align_right=True, bold=True,
                     color="" if interest_delta is None else (theme.ACCENT if interest_delta >= 0 else theme.DANGER)),
                cell("—" if months_delta is None else f"{months_delta:+d}", align_right=True,
                     color="" if months_delta is None else (theme.ACCENT if months_delta >= 0 else theme.DANGER)),
            ]
            for column, item in enumerate(values):
                self.comparison.setItem(index, column, item)
        self.comparison.refit()
