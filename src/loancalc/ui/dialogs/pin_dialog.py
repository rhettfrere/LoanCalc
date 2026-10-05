"""Pin editor and pin-preset manager for the scenario sandbox."""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from loancalc.domain.models import (
    DEFAULT_PRESETS,
    PIN_MODE_LABELS,
    Pin,
    PinMode,
    PinPreset,
    PinRepeat,
    Scenario,
)
from loancalc.ui import theme
from loancalc.ui.widgets import cell, make_table, money_spinbox
from loancalc.util.formatting import money, month_label

REPEAT_LABELS = {
    PinRepeat.ONCE: "Just this month",
    PinRepeat.YEARLY: "Every year in this month",
}


def _period_combo(periods: list[date], selected: date | None, *, allow_none: str = "") -> QComboBox:
    box = QComboBox()
    if allow_none:
        box.addItem(allow_none, "")
    for period in periods:
        box.addItem(month_label(period), period.isoformat())
    if selected is not None:
        index = box.findData(selected.isoformat())
        if index < 0:
            box.insertItem(1 if allow_none else 0, month_label(selected), selected.isoformat())
            index = box.findData(selected.isoformat())
        box.setCurrentIndex(index)
    box.setMaxVisibleItems(18)
    return box


class PinDialog(QDialog):
    """Create or edit one pin, with a live preview of the month's payment."""

    def __init__(
        self,
        parent: QWidget,
        scenario: Scenario,
        periods: list[date],
        minimum: float,
        *,
        pin: Pin | None = None,
        period: date | None = None,
        presets: list[PinPreset] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit pin" if pin else "Add pin")
        self.setMinimumWidth(460)
        self._scenario = scenario
        self._pin = pin
        self._minimum = minimum

        self.label = QLineEdit(pin.label if pin else "")
        self.label.setPlaceholderText("e.g. Tax refund, Bonus, Car repair")
        self.preset = QComboBox()
        self.preset.addItem("Start from a preset…", None)
        for index, preset in enumerate(presets or []):
            self.preset.addItem(f"{preset.label}  ({_preset_text(preset)})", index)
        self._presets = presets or []
        self.preset.currentIndexChanged.connect(self._apply_preset)
        self.preset.setVisible(bool(presets) and pin is None)

        self.month = _period_combo(periods, pin.period if pin else period)
        self.mode = QComboBox()
        for mode, text in PIN_MODE_LABELS.items():
            self.mode.addItem(text, mode.value)
        self.amount = money_spinbox(pin.amount if pin else 0.0, maximum=10_000_000.0)
        self.repeat = QComboBox()
        for repeat, text in REPEAT_LABELS.items():
            self.repeat.addItem(text, repeat.value)
        self.until = _period_combo(periods, pin.until if pin else None, allow_none="No end date")
        self.preview = theme.subtitle("")

        if pin:
            self.mode.setCurrentIndex(self.mode.findData(pin.mode.value))
            self.repeat.setCurrentIndex(self.repeat.findData(pin.repeat.value))

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow(self.preset)
        form.addRow(theme.field("Label"), self.label)
        form.addRow(theme.field("Month"), self.month)
        form.addRow(theme.field("Change"), self.mode)
        form.addRow(theme.field("Amount"), self.amount)
        form.addRow(theme.field("Repeat"), self.repeat)
        form.addRow(theme.field("Until"), self.until)
        self._form = form

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        theme.primary(buttons.button(QDialogButtonBox.StandardButton.Save))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(buttons)

        for widget in (self.month, self.mode, self.repeat, self.until):
            widget.currentIndexChanged.connect(self._refresh)
        self.amount.valueChanged.connect(self._refresh)
        self._refresh()

    def _apply_preset(self) -> None:
        index = self.preset.currentData()
        if index is None:
            return
        preset = self._presets[index]
        self.label.setText(preset.label)
        self.mode.setCurrentIndex(self.mode.findData(preset.mode.value))
        self.amount.setValue(preset.amount)
        self.repeat.setCurrentIndex(self.repeat.findData(preset.repeat.value))

    def _refresh(self) -> None:
        mode = PinMode(self.mode.currentData())
        self._form.setRowVisible(self.amount, mode is not PinMode.MINIMUM)
        self._form.setRowVisible(self.until, self.repeat.currentData() == PinRepeat.YEARLY.value)

        pin = self._build()
        trial = Scenario(
            name="preview",
            monthly_budget=self._scenario.monthly_budget,
            pins=[p for p in self._scenario.pins if p is not self._pin] + [pin],
        )
        before = Scenario(
            name="before",
            monthly_budget=self._scenario.monthly_budget,
            pins=[p for p in self._scenario.pins if p is not self._pin],
        )
        period = pin.period
        text = (
            f"{month_label(period)}: {money(before.payment_for(period, self._minimum))} → "
            f"<b>{money(trial.payment_for(period, self._minimum))}</b>"
        )
        if pin.repeat is PinRepeat.YEARLY:
            text += f"  ·  repeats every {period:%B}" + (
                f" through {pin.until.year}" if pin.until else ""
            )
        self.preview.setText(text)

    def _build(self) -> Pin:
        until = self.until.currentData()
        return Pin(
            period=date.fromisoformat(self.month.currentData()),
            amount=round(self.amount.value(), 2),
            mode=PinMode(self.mode.currentData()),
            label=self.label.text().strip(),
            repeat=PinRepeat(self.repeat.currentData()),
            until=date.fromisoformat(until) if until and self.repeat.currentData() == "yearly" else None,
            pin_id=self._pin.pin_id if self._pin else None,
        )

    def _accept(self) -> None:
        pin = self._build()
        if pin.mode is PinMode.ADD and pin.amount <= 0:
            QMessageBox.information(self, "Amount needed", "Enter how much extra you'll have.")
            return
        if pin.until is not None and pin.until < pin.period:
            QMessageBox.information(self, "Check dates", "'Until' must be after the first month.")
            return
        self.accept()

    def result_pin(self) -> Pin:
        pin = self._build()
        if not pin.label:
            pin.label = {PinMode.ADD: "Extra", PinMode.SET: "Adjusted", PinMode.MINIMUM: "Lean month"}[pin.mode]
        return pin


def _preset_text(preset: PinPreset) -> str:
    if preset.mode is PinMode.MINIMUM:
        text = "minimums only"
    elif preset.mode is PinMode.ADD:
        text = f"+{money(preset.amount)}"
    else:
        text = f"= {money(preset.amount)}"
    return text + (", yearly" if preset.repeat is PinRepeat.YEARLY else "")


class PresetsDialog(QDialog):
    """Edit the one-click pin buttons shown in the sandbox."""

    def __init__(self, parent: QWidget, presets: list[PinPreset]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pin presets")
        self.setMinimumSize(560, 360)
        self._presets = [PinPreset(p.label, p.mode, p.amount, p.repeat) for p in presets]

        self.table = make_table(["Label", "Change", "Amount", "Repeat"])
        self.table.doubleClicked.connect(lambda: self._edit())

        add = QPushButton("Add")
        add.clicked.connect(self._add)
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        up = QPushButton("▲")
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("▼")
        down.clicked.connect(lambda: self._move(1))
        reset = theme.quiet(QPushButton("Restore defaults"))
        reset.clicked.connect(self._reset)
        tools = QHBoxLayout()
        for button in (add, edit, remove, up, down):
            tools.addWidget(button)
        tools.addStretch(1)
        tools.addWidget(reset)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        theme.primary(buttons.button(QDialogButtonBox.StandardButton.Save))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(theme.subtitle(
            "Presets appear as one-click buttons in the sandbox. Select a month in the "
            "plan, then click a preset to pin it there."
        ))
        layout.addWidget(self.table, 1)
        layout.addLayout(tools)
        layout.addWidget(buttons)
        self._fill()

    def presets(self) -> list[PinPreset]:
        return list(self._presets)

    def _fill(self, select: int = 0) -> None:
        self.table.setRowCount(len(self._presets))
        for row, preset in enumerate(self._presets):
            values = [
                cell(preset.label, bold=True),
                cell(PIN_MODE_LABELS[preset.mode]),
                cell("—" if preset.mode is PinMode.MINIMUM else money(preset.amount), align_right=True),
                cell(REPEAT_LABELS[preset.repeat]),
            ]
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
        self.table.refit()
        if self._presets:
            self.table.selectRow(min(select, len(self._presets) - 1))

    def _dialog(self, preset: PinPreset | None) -> PinPreset | None:
        today = date.today().replace(day=1)
        scratch = Scenario(name="preset", monthly_budget=0.0)
        pin = preset.to_pin(today) if preset else None
        dialog = PinDialog(self, scratch, [today], 0.0, pin=pin, period=today)
        dialog.setWindowTitle("Edit preset" if preset else "Add preset")
        dialog.month.setEnabled(False)
        dialog.until.setEnabled(False)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        result = dialog.result_pin()
        return PinPreset(result.label, result.mode, result.amount, result.repeat)

    def _add(self) -> None:
        preset = self._dialog(None)
        if preset:
            self._presets.append(preset)
            self._fill(len(self._presets) - 1)

    def _edit(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._presets):
            preset = self._dialog(self._presets[row])
            if preset:
                self._presets[row] = preset
                self._fill(row)

    def _remove(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._presets):
            del self._presets[row]
            self._fill(row)

    def _move(self, step: int) -> None:
        row = self.table.currentRow()
        target = row + step
        if 0 <= row < len(self._presets) and 0 <= target < len(self._presets):
            self._presets[row], self._presets[target] = self._presets[target], self._presets[row]
            self._fill(target)

    def _reset(self) -> None:
        self._presets = [PinPreset(p.label, p.mode, p.amount, p.repeat) for p in DEFAULT_PRESETS]
        self._fill()
