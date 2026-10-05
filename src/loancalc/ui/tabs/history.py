"""Payment history: every logged month and how it was distributed."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from loancalc.domain.models import PaymentRecord
from loancalc.services.state import AppState
from loancalc.ui import theme
from loancalc.ui.widgets import Card, MetricCard, cell, make_table
from loancalc.util.formatting import long_date, money, month_label


class HistoryTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._records: list[PaymentRecord] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(theme.hero("Payment History"))
        self.sub = theme.subtitle("")
        titles.addWidget(self.sub)
        header.addLayout(titles, 1)
        self.all_plans = QCheckBox("Show every plan")
        self.all_plans.toggled.connect(self.refresh)
        header.addWidget(self.all_plans)
        layout.addLayout(header)

        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.card_paid = MetricCard("Total paid", tone="accent")
        self.card_principal = MetricCard("Principal retired", tone="accent")
        self.card_interest = MetricCard("Interest paid", tone="warn")
        self.card_count = MetricCard("Payments logged")
        for card in (self.card_paid, self.card_principal, self.card_interest, self.card_count):
            metrics.addWidget(card)
        layout.addLayout(metrics)

        payments_card = Card("Logged payments", "Select a payment to see its split.")
        self.payments = make_table(
            ["Month", "Plan", "Logged on", "Amount", "To interest", "To principal", "Note"]
        )
        self.payments.itemSelectionChanged.connect(self._show_detail)
        payments_card.add(self.payments, 1)

        self.detail_card = Card("Distribution", "")
        self.detail = make_table(
            ["Loan", "Applied", "Minimum", "Extra", "Interest", "Principal", "Balance after"]
        )
        self.detail_card.add(self.detail, 1)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(payments_card)
        splitter.addWidget(self.detail_card)
        splitter.setSizes([280, 260])
        layout.addWidget(splitter, 1)

        state.historyChanged.connect(self.refresh)
        state.currentPlanChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        everything = self.all_plans.isChecked()
        self._records = self.state.history(all_plans=everything)
        plan_id = None if everything else self.state.current_plan_id
        paid, interest, principal = self.state.store.payment_totals(plan_id)
        names = {plan.plan_id: plan.name for plan in self.state.plans}
        scope = "all plans" if everything else (
            self.state.current_plan.name if self.state.current_plan else "this plan"
        )

        self.card_paid.set_value(money(paid))
        self.card_principal.set_value(money(principal))
        self.card_interest.set_value(money(interest))
        self.card_count.set_value(str(len(self._records)))
        share = interest / paid * 100 if paid else 0.0
        self.card_interest.set_note(f"{share:.1f}% of everything paid so far")
        self.sub.setText(
            f"{len(self._records)} payments recorded for {scope} · {money(paid)} applied to date"
            if self._records
            else f"No payments logged for {scope} yet — use the Action Center to record this month."
        )

        self.payments.setRowCount(len(self._records))
        for row, record in enumerate(self._records):
            values = [
                cell(month_label(record.period), bold=True),
                cell(names.get(record.plan_id, "—"), muted=not everything),
                cell(long_date(record.paid_on), muted=True),
                cell(money(record.total_amount), align_right=True, bold=True),
                cell(money(record.interest_paid), align_right=True, color=theme.WARN),
                cell(money(record.principal_paid), align_right=True, color=theme.ACCENT),
                cell(record.note or "—", muted=not record.note),
            ]
            for column, item in enumerate(values):
                self.payments.setItem(row, column, item)
        self.payments.refit()

        if self._records:
            self.payments.selectRow(0)
        else:
            self.detail.setRowCount(0)
            self.detail_card.set_subtitle("")

    def _show_detail(self) -> None:
        row = self.payments.currentRow()
        if not (0 <= row < len(self._records)):
            return
        record = self._records[row]
        self.detail_card.set_subtitle(
            f"{month_label(record.period)} · {money(record.total_amount)} across "
            f"{len(record.allocations)} loans"
        )
        self.detail.setRowCount(len(record.allocations))
        for index, allocation in enumerate(record.allocations):
            values = [
                cell(allocation.loan_name, bold=allocation.extra_portion > 0),
                cell(money(allocation.amount), align_right=True, bold=True),
                cell(money(allocation.minimum_portion), align_right=True),
                cell(
                    money(allocation.extra_portion) if allocation.extra_portion else "—",
                    align_right=True,
                    color=theme.ACCENT if allocation.extra_portion else "",
                ),
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
                self.detail.setItem(index, column, item)
        self.detail.refit()
