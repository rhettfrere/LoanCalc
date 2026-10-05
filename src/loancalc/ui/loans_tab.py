"""Loan editor: add, edit, and remove tradelines."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from loancalc.core import theme
from loancalc.formatting import money, percent
from loancalc.models import Loan
from loancalc.state import AppState
from loancalc.ui.widgets import Card, cell, make_table, money_spinbox


class LoanDialog(QDialog):
    """Create or edit one loan."""

    def __init__(self, parent: QWidget, loan: Loan | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit loan" if loan else "Add loan")
        self.setMinimumWidth(420)
        self._loan = loan

        self.name = QLineEdit(loan.name if loan else "")
        self.name.setPlaceholderText("e.g. MOHELA 1-03 Direct Loan - Unsubsidized")
        self.servicer = QLineEdit(loan.servicer if loan else "")
        self.servicer.setPlaceholderText("Optional")
        self.balance = money_spinbox(loan.payoff_amount if loan else 0.0)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0.0, 99.999)
        self.rate.setDecimals(3)
        self.rate.setSingleStep(0.125)
        self.rate.setSuffix(" %")
        self.rate.setValue(loan.annual_rate * 100 if loan else 0.0)
        self.minimum = money_spinbox(loan.minimum_payment if loan else 0.0, maximum=100_000.0)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow(theme.field("Loan name"), self.name)
        form.addRow(theme.field("Servicer"), self.servicer)
        form.addRow(theme.field("Current balance"), self.balance)
        form.addRow(theme.field("Interest rate"), self.rate)
        form.addRow(theme.field("Minimum payment"), self.minimum)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        theme.primary(buttons.button(QDialogButtonBox.StandardButton.Save))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing name", "Give the loan a name.")
            return
        self.accept()

    def result_loan(self) -> Loan:
        """Apply the dialog values to the edited loan, or build a new one."""
        loan = self._loan or Loan(name="", principal=0.0, annual_rate=0.0, minimum_payment=0.0)
        new_balance = round(self.balance.value(), 2)
        # Editing the balance restates principal; accrued interest is reset so the
        # number the user typed is exactly what they owe.
        loan.name = self.name.text().strip()
        loan.servicer = self.servicer.text().strip()
        loan.principal = new_balance
        loan.accrued_interest = 0.0
        loan.annual_rate = round(self.rate.value() / 100.0, 6)
        loan.minimum_payment = round(self.minimum.value(), 2)
        return loan


class LoansTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(theme.hero("Loan Portfolio"))
        self.sub = theme.subtitle("")
        header.addWidget(self.sub)
        layout.addLayout(header)

        card = Card("Loans", "Double-click a row to edit it.")
        self.table = make_table(
            ["Loan", "Servicer", "Rate", "Principal", "Accrued interest", "Payoff", "Minimum", "Share"]
        )
        self.table.doubleClicked.connect(lambda: self._edit())
        card.add(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, slot in (
            ("Add loan", self._add),
            ("Edit", self._edit),
            ("Remove", self._remove),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        rebase = QPushButton("Reset baseline to current plan")
        rebase.setToolTip("Treat today's projection as the reference for future deviations.")
        rebase.clicked.connect(self._rebase)
        buttons.addWidget(rebase)
        card.add_layout(buttons)

        layout.addWidget(card, 1)

        state.loansChanged.connect(self.refresh)
        state.scheduleChanged.connect(self.refresh)
        self.refresh()

    # --- events ------------------------------------------------------------ #
    def _selected(self) -> Loan | None:
        row = self.table.currentRow()
        ordered = self.state.loans
        return ordered[row] if 0 <= row < len(ordered) else None

    def _add(self) -> None:
        dialog = LoanDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.state.upsert_loan(dialog.result_loan())

    def _edit(self) -> None:
        loan = self._selected()
        if loan is None:
            QMessageBox.information(self, "Select a loan", "Pick a row to edit first.")
            return
        dialog = LoanDialog(self, loan)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.state.upsert_loan(dialog.result_loan())

    def _remove(self) -> None:
        loan = self._selected()
        if loan is None:
            QMessageBox.information(self, "Select a loan", "Pick a row to remove first.")
            return
        confirm = QMessageBox.question(
            self,
            "Remove loan",
            f"Remove '{loan.name}' from the portfolio?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.delete_loan(loan)

    def _rebase(self) -> None:
        self.state.capture_baseline()
        self.state.statusMessage.emit("Baseline reset to the current plan.")

    # --- rendering --------------------------------------------------------- #
    def refresh(self) -> None:
        loans = self.state.loans
        total = self.state.total_balance
        self.sub.setText(
            f"{len(loans)} loans · {money(total)} outstanding · "
            f"{money(self.state.total_minimum)} in monthly minimums"
        )

        self.table.setRowCount(len(loans))
        for row, loan in enumerate(loans):
            share = loan.payoff_amount / total * 100 if total else 0.0
            values = [
                cell(loan.name),
                cell(loan.servicer or "—", muted=not loan.servicer),
                cell(percent(loan.annual_rate), align_right=True, bold=True,
                     color=theme.WARN if loan.annual_rate >= 0.06 else ""),
                cell(money(loan.principal), align_right=True),
                cell(money(loan.accrued_interest), align_right=True, muted=True),
                cell(money(loan.payoff_amount), align_right=True, bold=True),
                cell(money(loan.minimum_payment), align_right=True),
                cell(f"{share:.1f}%", align_right=True, muted=True),
            ]
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
        self.table.refit()
