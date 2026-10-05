"""Monthly Action Center: enter this month's capital, see the split, log it.

The preview recalculates live against untouched copies of the loans, so the
user can dial the number up and down before committing anything.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from loancalc import engine
from loancalc.core import theme
from loancalc.formatting import duration, long_date, money, month_label, percent
from loancalc.models import MonthResult
from loancalc.state import AppState
from loancalc.ui.widgets import (
    Card,
    MetricCard,
    cell,
    make_table,
    money_spinbox,
)


class ActionCenterTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._preview: MonthResult | None = None
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_input_card())
        layout.addWidget(self._build_impact_row())
        layout.addWidget(self._build_split_card(), 1)

        state.loansChanged.connect(self.refresh)
        state.scheduleChanged.connect(self.refresh)
        self.refresh()

    # --- construction ------------------------------------------------------ #
    def _build_header(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(2)
        self.heading = theme.hero("This Month's Payment")
        self.sub = theme.subtitle("")
        column.addWidget(self.heading)
        column.addWidget(self.sub)
        return column

    def _build_input_card(self) -> Card:
        card = Card(
            "Capital allocated",
            "Pay more or less than target — the engine re-plans the whole payoff instantly.",
        )

        self.period_box = QComboBox()
        self.period_box.setMinimumWidth(210)
        self.period_box.currentIndexChanged.connect(self._period_changed)

        self.amount = money_spinbox(self.state.monthly_budget, large=True)
        self.amount.setMinimumWidth(200)
        self.amount.valueChanged.connect(self._recalculate_preview)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(theme.field("Month"))
        row.addWidget(self.period_box)
        row.addWidget(self.amount)
        for label, factor in (("Target", 1.0), ("Minimums only", 0.0)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, f=factor: self._quick_fill(f))
            row.addWidget(button)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional note (e.g. tax refund, tight month)")
        row.addWidget(self.note, 1)

        self.log_button = theme.primary(QPushButton("Log Payment"))
        self.log_button.setMinimumWidth(150)
        self.log_button.clicked.connect(self._log_payment)
        row.addWidget(self.log_button)

        card.add_layout(row)
        self.warning = theme.warn("")
        self.warning.setVisible(False)
        card.add(self.warning)
        return card

    def _build_impact_row(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.card_interest_now = MetricCard("Interest accrued this month", tone="warn")
        self.card_to_principal = MetricCard("Goes to principal", tone="accent")
        self.card_new_payoff = MetricCard("Payoff after this month", tone="info")
        self.card_swing = MetricCard("Lifetime interest impact")

        for card in (
            self.card_interest_now,
            self.card_to_principal,
            self.card_new_payoff,
            self.card_swing,
        ):
            row.addWidget(card)
        return container

    def _build_split_card(self) -> Card:
        self.split_card = Card(
            "Distribution preview",
            "Minimums are covered first; everything left attacks the target loan.",
        )
        self.table = make_table(
            ["Loan", "Rate", "Balance", "Minimum", "Extra", "Total applied",
             "To interest", "To principal", "New balance"]
        )
        self.split_card.add(self.table, 1)
        return self.split_card

    # --- events ------------------------------------------------------------ #
    def selected_period(self) -> date:
        value = self.period_box.currentData()
        return date.fromisoformat(value) if value else self.state.current_period

    def _period_changed(self) -> None:
        if self._loading:
            return
        self._sync_amount()
        self._recalculate_preview()

    def _quick_fill(self, factor: float) -> None:
        if factor == 0.0:
            self.amount.setValue(self.state.total_minimum)
        else:
            self.amount.setValue(self.state.monthly_budget * factor)

    def _log_payment(self) -> None:
        amount = round(self.amount.value(), 2)
        if amount <= 0:
            QMessageBox.information(self, "Nothing to log", "Enter an amount above zero.")
            return

        period = self.selected_period()
        already = self.state.paid_in_period(period)
        detail = (
            f"Apply {money(amount)} to {month_label(period)}?\n\n"
            f"Balances and payoff projections will be updated and the split saved "
            f"to your payment history."
        )
        if already > 0:
            detail += f"\n\nYou have already logged {money(already)} for {month_label(period)}."
        if amount < self.state.total_minimum:
            detail += (
                f"\n\nWarning: this is below the {money(self.state.total_minimum)} "
                "total minimum. Some loans will be short."
            )

        confirm = QMessageBox.question(
            self, "Confirm payment", detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        record, result = self.state.log_payment(amount, self.note.text().strip(), period)
        self.note.clear()
        closed = result.loans_closed
        message = (
            f"Logged {money(record.total_amount)} for {month_label(period)} — "
            f"{money(record.principal_paid)} to principal, "
            f"{money(record.interest_paid)} to interest."
        )
        if closed:
            message += f" Paid off: {', '.join(closed)}."
        self.state.statusMessage.emit(message)
        QMessageBox.information(self, "Payment logged", message)

    # --- rendering --------------------------------------------------------- #
    def refresh(self) -> None:
        current = self.state.current_period
        selected = self.selected_period() if self.period_box.count() else current

        self._loading = True
        self.period_box.clear()
        # Three months back for catch-up, twelve ahead for planning.
        for offset in range(-3, 13):
            period = engine.add_months(current, offset)
            suffix = (
                "  (current)" if offset == 0 else "  (past)" if offset < 0 else "  (future)"
            )
            self.period_box.addItem(f"{month_label(period)}{suffix}", period.isoformat())
        index = self.period_box.findData(selected.isoformat())
        self.period_box.setCurrentIndex(index if index >= 0 else 3)
        self._loading = False

        self.heading.setText(f"{month_label(current)} Action Center")
        pieces = [
            f"Today is {long_date(date.today())}",
            f"target {money(self.state.monthly_budget)}",
            f"minimums {money(self.state.total_minimum)}",
            f"balance {money(self.state.total_balance)}",
        ]
        paid = self.state.paid_this_period()
        if paid > 0:
            pieces.append(f"{money(paid)} already logged this month")
        self.sub.setText(" · ".join(pieces))

        self.log_button.setEnabled(self.state.total_balance > 0)
        self._sync_amount()
        self._recalculate_preview()

    def _sync_amount(self) -> None:
        period = self.selected_period()
        paid = self.state.paid_in_period(period)
        remaining = max(self.state.monthly_budget - paid, 0.0)
        self.amount.blockSignals(True)
        self.amount.setValue(remaining if paid > 0 else self.state.monthly_budget)
        self.amount.blockSignals(False)

    def _recalculate_preview(self) -> None:
        amount = round(self.amount.value(), 2)
        period = self.selected_period()
        self.split_card.set_subtitle(
            f"Applying to {month_label(period)}. Minimums are covered first; "
            "everything left attacks the target loan."
        )
        if not self.state.loans or self.state.total_balance <= 0:
            self.table.setRowCount(0)
            self.warning.setVisible(False)
            for card in (
                self.card_interest_now, self.card_to_principal,
                self.card_new_payoff, self.card_swing,
            ):
                card.set_value("—")
                card.set_note("")
            return

        result = self.state.preview_payment(amount, period)
        self._preview = result
        self._fill_table(result)
        self._fill_impact(result, amount, period)

        if result.shortfall > 0:
            self.warning.setText(
                f"{money(result.shortfall)} short of the required minimums — "
                "the lowest-priority loans will not be fully covered and may go delinquent."
            )
            self.warning.setVisible(True)
        elif amount > self.state.total_balance:
            self.warning.setText(
                f"Only {money(result.total_paid)} is needed to clear every loan. "
                f"{money(amount - result.total_paid)} will not be applied."
            )
            self.warning.setVisible(True)
        elif self.state.period_accrued(period):
            self.warning.setText(
                f"Interest for {month_label(period)} has already been charged, so this "
                "payment goes straight against the current balances."
            )
            self.warning.setVisible(True)
        else:
            self.warning.setVisible(False)

    def _fill_table(self, result: MonthResult) -> None:
        rows = self.state.allocation_rows(result)
        self.table.setRowCount(len(rows))
        rates = {loan.name: loan.annual_rate for loan in self.state.loans}
        balances = {loan.name: loan.payoff_amount for loan in self.state.loans}

        for index, allocation in enumerate(rows):
            is_target = allocation.extra_portion > 0
            values = [
                cell(allocation.loan_name, bold=is_target),
                cell(percent(rates.get(allocation.loan_name, 0.0)), align_right=True),
                cell(money(balances.get(allocation.loan_name, 0.0)), align_right=True),
                cell(money(allocation.minimum_portion), align_right=True),
                cell(
                    money(allocation.extra_portion) if allocation.extra_portion else "—",
                    align_right=True, bold=is_target,
                    color=theme.ACCENT if is_target else "",
                ),
                cell(money(allocation.amount), align_right=True, bold=True),
                cell(money(allocation.interest_portion), align_right=True, color=theme.WARN),
                cell(money(allocation.principal_portion), align_right=True, color=theme.ACCENT),
                cell(
                    "PAID OFF" if allocation.is_payoff else money(allocation.remaining_balance),
                    align_right=True,
                    bold=allocation.is_payoff,
                    color=theme.ACCENT if allocation.is_payoff else "",
                ),
            ]
            for column, item in enumerate(values):
                self.table.setItem(index, column, item)
        self.table.refit()

    def _fill_impact(self, result: MonthResult, amount: float, period: date) -> None:
        self.card_interest_now.set_value(money(result.interest_charged))
        self.card_interest_now.set_note(
            f"{money(engine.daily_interest_cost(self.state.loans))} per day at current balances"
        )

        self.card_to_principal.set_value(money(result.principal_paid))
        share = result.principal_paid / result.total_paid * 100 if result.total_paid else 0.0
        self.card_to_principal.set_note(f"{share:.1f}% of this payment")

        projection = engine.simulate(
            self.state.loans,
            self.state.monthly_budget,
            start_period=period,
            strategy=self.state.strategy,
            first_month_budget=amount,
            skip_first_accrual=self.state.period_accrued(period),
        )
        if projection.completed and projection.payoff_date:
            self.card_new_payoff.set_value(projection.payoff_date.strftime("%b %Y"))
            self.card_new_payoff.set_note(
                f"{duration(projection.months_to_payoff)} · {long_date(projection.payoff_date)}"
            )
        else:
            self.card_new_payoff.set_value("Never")
            self.card_new_payoff.set_note("Payment does not outpace interest", "bad")

        current = self.state.schedule
        if current and current.completed and projection.completed:
            swing = current.total_interest - projection.total_interest
            months = current.months_to_payoff - projection.months_to_payoff
            self.card_swing.set_value(
                ("Saves " if swing >= 0 else "Costs ") + money(abs(swing))
            )
            self.card_swing.set_tone("accent" if swing >= 0 else "warn")
            if months:
                self.card_swing.set_note(
                    f"{duration(abs(months))} {'earlier' if months > 0 else 'later'} "
                    "than the current plan",
                    "good" if months > 0 else "bad",
                )
            else:
                self.card_swing.set_note("Same payoff month as the current plan")
        else:
            self.card_swing.set_value("—")
            self.card_swing.set_note("")
