"""Import preview: see what will be read and choose merge vs replace."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from loancalc.data.ingest import EXPORT_HEADERS, ImportResult
from loancalc.domain.loan_types import SPECS
from loancalc.domain.models import Plan
from loancalc.ui import theme
from loancalc.ui.widgets import Card, cell, make_table
from loancalc.util.formatting import money, percent


class ImportDialog(QDialog):
    def __init__(self, parent: QWidget, path: Path, result: ImportResult, plans: list[Plan]) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Import {path.name}")
        self.setMinimumSize(900, 560)

        existing = {plan.name.lower() for plan in plans}
        target_plans = {
            (name or SPECS[loan.loan_type].plan_name)
            for loan, name in zip(result.loans, result.plan_names, strict=True)
        }
        new_plans = sorted(p for p in target_plans if p.lower() not in existing)

        mapped = ", ".join(
            f"{EXPORT_HEADERS.get(field, field)} ← “{column}”"
            for field, column in result.columns.items()
        )
        summary = (
            f"<b>{len(result.loans)} loan(s)</b> across {len(target_plans)} plan(s)."
            + (f" New plan(s): {', '.join(new_plans)}." if new_plans else "")
            + (
                f" {result.inferred_types} loan type(s) were guessed from the loan name — "
                "add a <i>Loan Type</i> column to control this."
                if result.inferred_types else ""
            )
        )

        preview = Card("Preview", "")
        table = make_table(["Loan", "Type", "Plan", "Balance", "Rate", "Minimum", "Term", "Collateral"])
        table.setRowCount(len(result.loans))
        for row, (loan, plan_name) in enumerate(zip(result.loans, result.plan_names, strict=True)):
            values = [
                cell(loan.name, bold=True),
                cell(SPECS[loan.loan_type].label, color=SPECS[loan.loan_type].color),
                cell(plan_name or SPECS[loan.loan_type].plan_name),
                cell(money(loan.principal), align_right=True),
                cell(percent(loan.annual_rate, 3), align_right=True),
                cell(
                    money(loan.effective_minimum) + ("" if loan.minimum_payment else " (from term)"),
                    align_right=True, muted=not loan.minimum_payment,
                ),
                cell(f"{loan.term_months} mo" if loan.term_months else "—", align_right=True),
                cell(money(loan.asset_value) if loan.asset_value else "—", align_right=True),
            ]
            for column, item in enumerate(values):
                table.setItem(row, column, item)
        table.refit()
        preview.add(table, 1)

        mode = Card("How should this be applied?", "")
        self.merge = QRadioButton(
            "Merge into my data — add new loans; update loans whose name already exists in the "
            "same plan (use this to refresh balances from a new statement)"
        )
        self.replace = QRadioButton(
            "Replace everything — delete all current plans, loans, payment history and "
            "sandbox scenarios first"
        )
        self.merge.setChecked(True)
        self.warning = theme.warn("Replace cannot be undone. Use File → Back Up Data… first if unsure.")
        self.warning.setVisible(False)
        self.replace.toggled.connect(self.warning.setVisible)
        mode.add(self.merge)
        mode.add(self.replace)
        mode.add(self.warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Import")
        theme.primary(ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(theme.title(path.name))
        layout.addWidget(theme.subtitle(summary))
        columns_label = theme.subtitle(f"Columns matched: {mapped}")
        layout.addWidget(columns_label)
        layout.addWidget(preview, 1)
        layout.addWidget(mode)
        layout.addWidget(buttons)

    @property
    def replace_all(self) -> bool:
        return self.replace.isChecked()
