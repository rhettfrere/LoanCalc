"""Plan manager: create, edit, reorder and delete plans."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from loancalc.domain import engine
from loancalc.domain.loan_types import SPECS
from loancalc.domain.models import Plan
from loancalc.services.state import AppState
from loancalc.ui import theme
from loancalc.ui.widgets import money_spinbox
from loancalc.util.formatting import money


def _swatch(color: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class PlanManagerDialog(QDialog):
    def __init__(self, parent: QWidget, state: AppState) -> None:
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Manage plans")
        self.setMinimumSize(760, 460)
        self._loading = False

        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.list.currentRowChanged.connect(self._selected)

        add = QPushButton("Add plan")
        add.clicked.connect(self._add)
        remove = QPushButton("Delete")
        remove.clicked.connect(self._delete)
        up = QPushButton("▲")
        up.setToolTip("Move up (higher priority for plan-order rollover)")
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("▼")
        down.setToolTip("Move down")
        down.clicked.connect(lambda: self._move(1))
        list_buttons = QHBoxLayout()
        for button in (add, remove, up, down):
            list_buttons.addWidget(button)

        left = QVBoxLayout()
        left.addWidget(theme.section("Plans"))
        left.addWidget(self.list, 1)
        left.addLayout(list_buttons)

        self.name = QLineEdit()
        self.name.editingFinished.connect(self._commit)
        self.budget = money_spinbox(0.0, maximum=1_000_000.0)
        self.budget.editingFinished.connect(self._commit)
        self.budget_hint = theme.status("")
        self.strategy = QComboBox()
        for key, label in engine.STRATEGY_LABELS.items():
            self.strategy.addItem(label, key)
        self.strategy.currentIndexChanged.connect(self._commit)
        self.color = QPushButton("Choose colour…")
        self.color.clicked.connect(self._pick_color)

        self.active = QCheckBox("Active — include in the household projection")
        self.rollover = QCheckBox("When paid off, roll this plan's budget into other plans")
        self.accepts = QCheckBox("Accept budget rolled over from finished plans")
        for box in (self.active, self.rollover, self.accepts):
            box.toggled.connect(self._commit)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow(theme.field("Name"), self.name)
        budget_col = QVBoxLayout()
        budget_col.setSpacing(2)
        budget_col.addWidget(self.budget)
        budget_col.addWidget(self.budget_hint)
        form.addRow(theme.field("Monthly budget"), budget_col)
        form.addRow(theme.field("Strategy"), self.strategy)
        form.addRow(theme.field("Colour"), self.color)
        form.addRow(self.active)
        form.addRow(self.rollover)
        form.addRow(self.accepts)

        self.summary = theme.subtitle("")
        right = QVBoxLayout()
        right.addWidget(theme.section("Plan settings"))
        right.addLayout(form)
        right.addWidget(self.summary)
        right.addStretch(1)
        self.editor = QWidget()
        self.editor.setLayout(right)

        body = QHBoxLayout()
        body.setSpacing(18)
        body.addLayout(left)
        body.addWidget(self.editor, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(
            theme.subtitle(
                "A plan groups loans that share one monthly budget and one payoff strategy — "
                "e.g. Student Loans, Mortgage, Auto. Each can be viewed on its own; the "
                "Household tab runs every active plan together."
            )
        )
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

        self._reload(select=state.current_plan_id)

    # --- list -------------------------------------------------------------- #
    @property
    def plan(self) -> Plan | None:
        item = self.list.currentItem()
        return self.state.plan_by_id(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _reload(self, select: int | None = None) -> None:
        self._loading = True
        self.list.clear()
        for plan in self.state.plans:
            loans = self.state.plan_loans(plan.plan_id)
            label = f"{plan.name}  ·  {len(loans)} loan{'s' if len(loans) != 1 else ''}"
            if not plan.active:
                label += "  (inactive)"
            item = QListWidgetItem(_swatch(self.state.plan_color(plan)), label)
            item.setData(Qt.ItemDataRole.UserRole, plan.plan_id)
            self.list.addItem(item)
            if plan.plan_id == select:
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self._loading = False
        self._selected()

    def _selected(self) -> None:
        if self._loading:
            return
        plan = self.plan
        self.editor.setEnabled(plan is not None)
        if plan is None:
            return
        self._loading = True
        self.name.setText(plan.name)
        self.budget.setValue(plan.monthly_budget)
        self.strategy.setCurrentIndex(max(self.strategy.findData(plan.strategy), 0))
        self.color.setIcon(_swatch(self.state.plan_color(plan)))
        self.active.setChecked(plan.active)
        self.rollover.setChecked(plan.rollover)
        self.accepts.setChecked(plan.accepts_rollover)
        self._loading = False
        self._describe(plan)

    def _describe(self, plan: Plan) -> None:
        loans = self.state.plan_loans(plan.plan_id)
        minimum = engine.total_minimum_payment(loans)
        self.budget_hint.setText(f"Contractual minimums: {money(minimum)}/mo")
        types = sorted({SPECS[loan.loan_type].label for loan in loans})
        self.summary.setText(
            f"{len(loans)} loan(s) · {money(engine.total_balance(loans))} · "
            + (", ".join(types) if types else "no loans yet")
        )

    # --- edits ------------------------------------------------------------- #
    def _commit(self) -> None:
        plan = self.plan
        if self._loading or plan is None:
            return
        name = self.name.text().strip() or plan.name
        clash = any(p.name.lower() == name.lower() and p.plan_id != plan.plan_id for p in self.state.plans)
        if clash:
            QMessageBox.warning(self, "Name in use", f"Another plan is already called '{name}'.")
            self.name.setText(plan.name)
            return
        plan.name = name
        plan.monthly_budget = round(self.budget.value(), 2)
        plan.strategy = self.strategy.currentData()
        plan.active = self.active.isChecked()
        plan.rollover = self.rollover.isChecked()
        plan.accepts_rollover = self.accepts.isChecked()
        self.state.save_plan(plan)
        self._reload(select=plan.plan_id)

    def _pick_color(self) -> None:
        plan = self.plan
        if plan is None:
            return
        color = QColorDialog.getColor(QColor(self.state.plan_color(plan)), self, "Plan colour")
        if color.isValid():
            plan.color = color.name()
            self.state.save_plan(plan, recalc=False)
            self._reload(select=plan.plan_id)

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "New plan", "Plan name:", text="New Plan")
        if ok and name.strip():
            plan = self.state.add_plan(name.strip())
            self._reload(select=plan.plan_id)

    def _delete(self) -> None:
        plan = self.plan
        if plan is None:
            return
        loans = self.state.plan_loans(plan.plan_id)
        detail = f"Delete the plan '{plan.name}'?"
        if loans:
            detail += (
                f"\n\nIts {len(loans)} loan(s), payment history and sandbox scenarios will be "
                "deleted too. Move loans to another plan first (Loans tab → Edit) to keep them."
            )
        confirm = QMessageBox.question(
            self, "Delete plan", detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.delete_plan(plan)
            self._reload(select=self.state.current_plan_id)

    def _move(self, step: int) -> None:
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        ids = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        ids[row], ids[target] = ids[target], ids[row]
        self.state.reorder_plans(ids)
        self._reload(select=ids[target])
