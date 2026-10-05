"""Loan portfolio: every loan across every plan, with add / edit / move / remove."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from loancalc.domain import engine
from loancalc.domain.models import Loan
from loancalc.services.state import AppState
from loancalc.ui import theme
from loancalc.ui.dialogs.loan_dialog import LoanDialog
from loancalc.ui.widgets import Card, cell, make_table
from loancalc.util.formatting import duration, money, percent

ALL_PLANS = -1


class LoansTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._rows: list[Loan] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(theme.hero("Loan Portfolio"))
        self.sub = theme.subtitle("")
        titles.addWidget(self.sub)
        header.addLayout(titles, 1)
        self.filter = QComboBox()
        self.filter.setMinimumWidth(220)
        self.filter.currentIndexChanged.connect(self._fill)
        header.addWidget(theme.field("Show"))
        header.addWidget(self.filter)
        layout.addLayout(header)

        card = Card("Loans", "Double-click a row to edit it. Change a loan's plan to move it.")
        self.table = make_table(
            ["Loan", "Type", "Plan", "Rate", "Balance", "Minimum", "Term left",
             "Collateral", "Equity", "Share"]
        )
        self.table.doubleClicked.connect(lambda: self._edit())
        card.add(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        add = theme.primary(QPushButton("Add loan"))
        add.clicked.connect(self._add)
        buttons.addWidget(add)
        for label, slot in (("Edit", self._edit), ("Remove", self._remove)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        rebase = QPushButton("Reset baseline to current plan")
        rebase.setToolTip("Treat today's projection for the selected plan as the reference for deviations.")
        rebase.clicked.connect(self._rebase)
        buttons.addWidget(rebase)
        card.add_layout(buttons)
        layout.addWidget(card, 1)

        state.loansChanged.connect(self.refresh)
        state.plansChanged.connect(self.refresh)
        state.currentPlanChanged.connect(self._follow_plan)
        self.refresh()

    # --- events ------------------------------------------------------------ #
    def _selected(self) -> Loan | None:
        row = self.table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _add(self) -> None:
        if not self.state.plans:
            QMessageBox.information(self, "No plans", "Create a plan first (Plans → Manage Plans…).")
            return
        filtered = self.filter.currentData()
        default = filtered if filtered not in (None, ALL_PLANS) else self.state.current_plan_id
        dialog = LoanDialog(self, self.state.plans, default_plan_id=default)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.state.upsert_loan(dialog.result_loan())

    def _edit(self) -> None:
        loan = self._selected()
        if loan is None:
            QMessageBox.information(self, "Select a loan", "Pick a row to edit first.")
            return
        dialog = LoanDialog(self, self.state.plans, loan=loan.copy())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.state.upsert_loan(dialog.result_loan())

    def _remove(self) -> None:
        loan = self._selected()
        if loan is None:
            QMessageBox.information(self, "Select a loan", "Pick a row to remove first.")
            return
        confirm = QMessageBox.question(
            self, "Remove loan",
            f"Remove '{loan.name}' from the portfolio?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.delete_loan(loan)

    def _rebase(self) -> None:
        plan_id = self.filter.currentData()
        plan_id = plan_id if plan_id not in (None, ALL_PLANS) else self.state.current_plan_id
        self.state.capture_baseline(plan_id)
        plan = self.state.plan_by_id(plan_id)
        self.state.statusMessage.emit(f"Baseline reset for {plan.name if plan else 'plan'}.")

    def _follow_plan(self) -> None:
        if self.filter.currentData() not in (None, ALL_PLANS):
            index = self.filter.findData(self.state.current_plan_id)
            if index >= 0:
                self.filter.setCurrentIndex(index)

    # --- rendering --------------------------------------------------------- #
    def refresh(self) -> None:
        current = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("All plans", ALL_PLANS)
        for plan in self.state.plans:
            self.filter.addItem(plan.name, plan.plan_id)
        index = self.filter.findData(current if current is not None else ALL_PLANS)
        self.filter.setCurrentIndex(index if index >= 0 else 0)
        self.filter.blockSignals(False)
        self._fill()

    def _fill(self) -> None:
        plan_id = self.filter.currentData()
        loans = self.state.all_loans if plan_id in (None, ALL_PLANS) else self.state.plan_loans(plan_id)
        order = {plan.plan_id: plan.sort_order for plan in self.state.plans}
        self._rows = sorted(loans, key=lambda l: (order.get(l.plan_id, 999), l.sort_order))
        names = {plan.plan_id: plan.name for plan in self.state.plans}
        colors = {plan.plan_id: self.state.plan_color(plan) for plan in self.state.plans}

        total = engine.total_balance(self._rows)
        self.sub.setText(
            f"{len(self._rows)} loans · {money(total)} outstanding · "
            f"{money(engine.total_minimum_payment(self._rows))} in monthly minimums"
        )

        self.table.setRowCount(len(self._rows))
        for row, loan in enumerate(self._rows):
            share = loan.payoff_amount / total * 100 if total else 0.0
            months = loan.months_left_at_minimum
            equity = loan.equity if loan.is_secured else None
            values = [
                cell(loan.name, bold=True, tooltip=loan.servicer or loan.name),
                cell(loan.spec.label, color=loan.spec.color),
                cell(names.get(loan.plan_id, "—"), color=colors.get(loan.plan_id, "")),
                cell(percent(loan.annual_rate), align_right=True, bold=True,
                     color=theme.WARN if loan.annual_rate >= 0.06 else ""),
                cell(money(loan.payoff_amount), align_right=True, bold=True),
                cell(money(loan.effective_minimum), align_right=True,
                     muted=not loan.minimum_payment,
                     tooltip="" if loan.minimum_payment else "Calculated from the remaining term"),
                cell(duration(months) if months else "—", align_right=True, muted=True),
                cell(money(loan.asset_value) if loan.asset_value else "—", align_right=True, muted=True),
                cell("—" if equity is None else money(equity), align_right=True,
                     color="" if equity is None else (theme.ACCENT if equity >= 0 else theme.DANGER)),
                cell(f"{share:.1f}%", align_right=True, muted=True),
            ]
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
        self.table.refit()
