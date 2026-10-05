"""Loan editor that adapts its fields to the loan type."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from loancalc.domain import amortization
from loancalc.domain.loan_types import INTEREST_METHOD_LABELS, SPECS, InterestMethod, LoanType
from loancalc.domain.models import Loan, Plan
from loancalc.ui import theme
from loancalc.ui.widgets import money_spinbox
from loancalc.util.formatting import duration, money


def _percent_box(low: float, high: float, step: float, suffix: str = " %") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(3)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return box


class LoanDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        plans: list[Plan],
        *,
        loan: Loan | None = None,
        default_plan_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit loan" if loan else "Add loan")
        self.setMinimumWidth(520)
        self._loan = loan
        self._growth_touched = loan is not None and loan.asset_growth is not None

        # --- basics -------------------------------------------------------- #
        self.name = QLineEdit(loan.name if loan else "")
        self.name.setPlaceholderText("e.g. Chase Home Mortgage")
        self.type_box = QComboBox()
        for loan_type, spec in SPECS.items():
            self.type_box.addItem(spec.label, loan_type.value)
        self.plan_box = QComboBox()
        for plan in plans:
            self.plan_box.addItem(plan.name, plan.plan_id)
        self.servicer = QLineEdit(loan.servicer if loan else "")
        self.servicer.setPlaceholderText("Optional")

        self.balance = money_spinbox(loan.payoff_amount if loan else 0.0, maximum=50_000_000.0)
        self.rate = _percent_box(0.0, 99.999, 0.125)
        self.minimum = money_spinbox(loan.minimum_payment if loan else 0.0, maximum=1_000_000.0)
        self.term = QSpinBox()
        self.term.setRange(0, 600)
        self.term.setSuffix(" months")
        self.term.setSpecialValueText("No fixed term")
        self.term_hint = theme.status("")
        calc = QPushButton("Calculate from term")
        calc.setToolTip("Fill the minimum with the level P&I payment for this balance, rate and term.")
        calc.clicked.connect(self._calculate_payment)

        basics = QFormLayout()
        basics.setSpacing(9)
        basics.addRow(theme.field("Loan name"), self.name)
        basics.addRow(theme.field("Type"), self.type_box)
        basics.addRow(theme.field("Plan"), self.plan_box)
        basics.addRow(theme.field("Servicer"), self.servicer)
        basics.addRow(theme.field("Current balance"), self.balance)
        basics.addRow(theme.field("Interest rate (APR)"), self.rate)
        minimum_row = QHBoxLayout()
        minimum_row.addWidget(self.minimum, 1)
        minimum_row.addWidget(calc)
        basics.addRow(theme.field("Minimum / P&I payment"), minimum_row)
        term_row = QVBoxLayout()
        term_row.setSpacing(2)
        term_row.addWidget(self.term)
        term_row.addWidget(self.term_hint)
        basics.addRow(theme.field("Remaining term"), term_row)

        # --- mortgage ------------------------------------------------------ #
        self.escrow = money_spinbox(loan.escrow_monthly if loan else 0.0, maximum=50_000.0)
        self.pmi = money_spinbox(loan.pmi_monthly if loan else 0.0, maximum=10_000.0)
        self.housing_hint = theme.status("")
        self.mortgage_box = QGroupBox("MORTGAGE")
        mortgage = QFormLayout(self.mortgage_box)
        mortgage.setSpacing(9)
        mortgage.addRow(theme.field("Escrow (taxes + insurance) / mo"), self.escrow)
        mortgage.addRow(theme.field("PMI / mo"), self.pmi)
        mortgage.addRow(self.housing_hint)

        # --- collateral ---------------------------------------------------- #
        self.asset = money_spinbox(loan.asset_value if loan else 0.0, maximum=50_000_000.0)
        self.original = money_spinbox(loan.original_value if loan else 0.0, maximum=50_000_000.0)
        self.growth = _percent_box(-60.0, 30.0, 0.5, " % / yr")
        self.growth.valueChanged.connect(self._growth_changed)
        self.collateral_box = QGroupBox("COLLATERAL")
        collateral = QFormLayout(self.collateral_box)
        collateral.setSpacing(9)
        self.asset_label = theme.field("Current value")
        self.original_label = theme.field("Original value (purchase / appraisal)")
        self.growth_label = theme.field("Annual change")
        collateral.addRow(self.asset_label, self.asset)
        collateral.addRow(self.original_label, self.original)
        collateral.addRow(self.growth_label, self.growth)
        self._collateral_form = collateral

        # --- advanced ------------------------------------------------------ #
        self.method = QComboBox()
        self.method.addItem("Default for this loan type", None)
        for method, label in INTEREST_METHOD_LABELS.items():
            self.method.addItem(label, method.value)
        advanced = QGroupBox("ADVANCED")
        advanced_form = QFormLayout(advanced)
        advanced_form.addRow(theme.field("Interest accrual"), self.method)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        theme.primary(buttons.button(QDialogButtonBox.StandardButton.Save))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(basics)
        layout.addWidget(self.mortgage_box)
        layout.addWidget(self.collateral_box)
        layout.addWidget(advanced)
        layout.addWidget(buttons)

        # --- initial values ------------------------------------------------ #
        loan_type = loan.loan_type if loan else LoanType.STUDENT
        self.type_box.setCurrentIndex(max(self.type_box.findData(loan_type.value), 0))
        plan_id = loan.plan_id if loan else default_plan_id
        self.plan_box.setCurrentIndex(max(self.plan_box.findData(plan_id), 0))
        self.rate.setValue(loan.annual_rate * 100 if loan else 0.0)
        self.term.setValue(loan.term_months if loan else 0)
        if loan and loan.interest_method:
            self.method.setCurrentIndex(max(self.method.findData(loan.interest_method.value), 0))
        if loan and loan.asset_growth is not None:
            self.growth.blockSignals(True)
            self.growth.setValue(loan.asset_growth * 100)
            self.growth.blockSignals(False)

        self.type_box.currentIndexChanged.connect(self._type_changed)
        for widget in (self.balance, self.rate, self.minimum, self.escrow, self.pmi,
                       self.asset, self.original):
            widget.valueChanged.connect(self._update_hints)
        self.term.valueChanged.connect(self._update_hints)
        self._type_changed()

    # --- behaviour --------------------------------------------------------- #
    @property
    def loan_type(self) -> LoanType:
        return LoanType(self.type_box.currentData())

    def _growth_changed(self) -> None:
        self._growth_touched = True

    def _type_changed(self) -> None:
        spec = SPECS[self.loan_type]
        self.mortgage_box.setVisible(spec.has_escrow)
        self.collateral_box.setVisible(spec.secured)
        self.asset_label.setText(spec.asset_label or "Current value")
        self.growth_label.setText("Annual appreciation" if spec.asset_growth >= 0 else "Annual depreciation")
        self._collateral_form.setRowVisible(self.original, self.loan_type is LoanType.MORTGAGE)
        if not self._growth_touched:
            self.growth.blockSignals(True)
            self.growth.setValue(spec.asset_growth * 100)
            self.growth.blockSignals(False)
        self.adjustSize()
        self._update_hints()

    def _calculate_payment(self) -> None:
        if self.term.value() <= 0:
            QMessageBox.information(self, "Need a term", "Enter the remaining term in months first.")
            return
        self.minimum.setValue(
            amortization.scheduled_payment(self.balance.value(), self.rate.value() / 100, self.term.value())
        )

    def _update_hints(self) -> None:
        balance, rate = self.balance.value(), self.rate.value() / 100
        minimum = self.minimum.value()
        term = self.term.value()
        if minimum > 0:
            months = amortization.remaining_term(balance, rate, minimum)
            self.term_hint.setText(
                "Payment never covers the interest." if months is None
                else f"At {money(minimum)}/mo this is paid off in {duration(months)}."
            )
        elif term > 0:
            payment = amortization.scheduled_payment(balance, rate, term)
            self.term_hint.setText(f"Scheduled P&I: {money(payment)}/mo (used as the minimum).")
        else:
            self.term_hint.setText("Enter a minimum payment or a remaining term.")

        if SPECS[self.loan_type].has_escrow:
            pi = minimum or (amortization.scheduled_payment(balance, rate, term) if term else 0.0)
            basis = self.original.value() or self.asset.value()
            pmi = self.pmi.value() if amortization.pmi_applies(balance, basis) else 0.0
            text = f"Total housing payment: {money(pi + self.escrow.value() + pmi)}/mo"
            if self.pmi.value() > 0 and basis > 0:
                target = amortization.pmi_balance_target(basis)
                text += (
                    f" · PMI ends when the balance reaches {money(target)}"
                    if balance > target else " · PMI should already be cancelled"
                )
            self.housing_hint.setText(text)

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing name", "Give the loan a name.")
            return
        if self.plan_box.currentData() is None:
            QMessageBox.warning(self, "No plan", "Create a plan first (Plans → Manage plans).")
            return
        if self.minimum.value() <= 0 and self.term.value() <= 0 and self.balance.value() > 0:
            QMessageBox.warning(
                self, "Payment needed",
                "Enter a minimum payment, or a remaining term so it can be calculated.",
            )
            return
        self.accept()

    def result_loan(self) -> Loan:
        """Apply the dialog values to the edited loan, or build a new one."""
        loan = self._loan or Loan(name="", principal=0.0, annual_rate=0.0, minimum_payment=0.0)
        spec = SPECS[self.loan_type]
        balance_changed = abs(self.balance.value() - loan.payoff_amount) > 0.004
        loan.name = self.name.text().strip()
        loan.loan_type = self.loan_type
        loan.plan_id = self.plan_box.currentData()
        loan.servicer = self.servicer.text().strip()
        if balance_changed or self._loan is None:
            # A typed balance is the full payoff; restate it as principal.
            loan.principal = round(self.balance.value(), 2)
            loan.accrued_interest = 0.0
        loan.annual_rate = round(self.rate.value() / 100.0, 6)
        loan.minimum_payment = round(self.minimum.value(), 2)
        loan.term_months = self.term.value()
        method = self.method.currentData()
        loan.interest_method = InterestMethod(method) if method else None
        loan.escrow_monthly = round(self.escrow.value(), 2) if spec.has_escrow else 0.0
        loan.pmi_monthly = round(self.pmi.value(), 2) if spec.has_escrow else 0.0
        if spec.secured:
            loan.asset_value = round(self.asset.value(), 2)
            loan.original_value = round(self.original.value(), 2) if spec.has_escrow else 0.0
            growth = round(self.growth.value() / 100.0, 5)
            loan.asset_growth = None if abs(growth - spec.asset_growth) < 1e-6 else growth
        else:
            loan.asset_value = loan.original_value = 0.0
            loan.asset_growth = None
        return loan
