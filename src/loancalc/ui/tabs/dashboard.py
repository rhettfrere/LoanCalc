"""Plan dashboard: headline numbers, collateral health, and the payoff queue."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from loancalc.domain import amortization, engine
from loancalc.domain.loan_types import LoanType
from loancalc.services.state import AppState
from loancalc.ui import theme
from loancalc.ui.widgets import Card, MetricCard, banner, cell, make_table, money_spinbox
from loancalc.util.formatting import duration, long_date, money, money_compact, percent


class DashboardTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())
        self.empty = banner("This plan has no loans yet. Add one on the Loans tab or import a file.")
        layout.addWidget(self.empty)
        layout.addLayout(self._build_metrics())
        self.collateral = self._build_collateral()
        layout.addWidget(self.collateral)
        layout.addWidget(self._build_queue_card(), 1)

        for signal in (state.scheduleChanged, state.loansChanged, state.currentPlanChanged,
                       state.householdChanged):
            signal.connect(self.refresh)
        self.refresh()

    # --- construction ------------------------------------------------------ #
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.heading = theme.hero("")
        titles.addWidget(self.heading)
        self.headline = theme.subtitle("")
        titles.addWidget(self.headline)
        row.addLayout(titles, 1)

        self.strategy_box = QComboBox()
        for key, label in engine.STRATEGY_LABELS.items():
            self.strategy_box.addItem(label, key)
        self.strategy_box.currentIndexChanged.connect(self._strategy_changed)
        self.strategy_box.setMinimumWidth(260)

        self.budget_box = money_spinbox(0.0, large=True)
        self.budget_box.setMinimumWidth(170)
        self.budget_box.editingFinished.connect(self._budget_changed)

        controls = QHBoxLayout()
        controls.setSpacing(16)
        for label, widget in (("Strategy", self.strategy_box), ("Monthly allocation", self.budget_box)):
            block = QVBoxLayout()
            block.setSpacing(3)
            block.addWidget(theme.field(label))
            block.addWidget(widget)
            controls.addLayout(block)
        row.addLayout(controls)
        return row

    def _build_metrics(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(12)
        self.card_debt = MetricCard("Total debt", tone="warn")
        self.card_minimum = MetricCard("Total minimum / mo")
        self.card_target = MetricCard("Target payment / mo", tone="accent")
        self.card_payoff = MetricCard("Projected payoff", tone="info")
        self.card_interest = MetricCard("Lifetime interest", tone="warn")
        self.card_saved = MetricCard("vs. minimums only", tone="accent")
        cards = (self.card_debt, self.card_minimum, self.card_target,
                 self.card_payoff, self.card_interest, self.card_saved)
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 3, index % 3)
        return grid

    def _build_collateral(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.card_equity = MetricCard("Equity", tone="accent")
        self.card_ltv = MetricCard("Loan-to-value")
        self.card_pmi = MetricCard("PMI", tone="warn")
        self.card_housing = MetricCard("Housing payment / mo", tone="info")
        for card in (self.card_equity, self.card_ltv, self.card_pmi, self.card_housing):
            row.addWidget(card)
        return container

    def _build_queue_card(self) -> Card:
        self.queue_card = Card(
            "Payoff queue",
            "Loans in attack order. The target gets every dollar left after minimums.",
        )
        self.table = make_table(
            ["#", "Loan", "Type", "Rate", "Balance", "Accrued int.", "Minimum", "Term left",
             "Daily int.", "Projected payoff"]
        )
        self.queue_card.add(self.table, 1)
        return self.queue_card

    # --- events ------------------------------------------------------------ #
    def _strategy_changed(self) -> None:
        strategy = self.strategy_box.currentData()
        if strategy != self.state.strategy:
            self.state.set_strategy(strategy)

    def _budget_changed(self) -> None:
        if abs(self.budget_box.value() - self.state.monthly_budget) > 0.004:
            self.state.set_monthly_budget(self.budget_box.value())

    # --- rendering --------------------------------------------------------- #
    def refresh(self) -> None:
        state = self.state
        plan = state.current_plan
        schedule = state.schedule
        minimums = state.minimums_schedule
        loans = state.loans

        self.heading.setText(f"{plan.name} Overview" if plan else "No plan selected")
        self.empty.setVisible(plan is not None and not loans)

        self.budget_box.blockSignals(True)
        self.budget_box.setValue(state.monthly_budget)
        self.budget_box.blockSignals(False)
        self.strategy_box.blockSignals(True)
        self.strategy_box.setCurrentIndex(max(self.strategy_box.findData(state.strategy), 0))
        self.strategy_box.blockSignals(False)

        total = state.total_balance
        minimum = state.total_minimum
        rate = engine.weighted_average_rate(loans)
        daily = engine.daily_interest_cost(loans)
        self.headline.setText(
            f"{len([x for x in loans if x.is_open])} open loans · "
            f"weighted average rate {percent(rate)} · "
            f"interest accruing at {money(daily)} per day"
        )

        self.card_debt.set_value(money(total))
        self.card_debt.set_note(f"{money(daily)}/day in interest")
        self.card_minimum.set_value(money(minimum))
        self.card_minimum.set_note("Contractual floor (P&I for mortgages)")

        self.card_target.set_value(money(state.monthly_budget))
        extra = state.monthly_budget - minimum
        if extra >= 0:
            self.card_target.set_note(f"{money(extra)} of attack capital", "good")
        else:
            self.card_target.set_note(f"{money(-extra)} below the minimums", "bad")

        if schedule and schedule.completed and schedule.payoff_date:
            self.card_payoff.set_value(schedule.payoff_date.strftime("%b %Y"))
            note = f"{duration(schedule.months_to_payoff)} on its own"
            household = state.household_payoff_for(state.current_plan_id)
            if household and household < schedule.payoff_date and state.rollover_enabled:
                note += f" · {household:%b %Y} with household rollover"
                self.card_payoff.set_note(note, "good")
            else:
                self.card_payoff.set_note(note)
        elif total <= 0:
            self.card_payoff.set_value("Paid off")
            self.card_payoff.set_note("")
        else:
            self.card_payoff.set_value("Never")
            self.card_payoff.set_note("Allocation does not outpace interest", "bad")

        self._fill_interest(schedule)

        if minimums and minimums.completed and schedule and schedule.completed:
            saved = minimums.total_cost - schedule.total_cost
            self.card_saved.set_value(money_compact(saved))
            self.card_saved.set_note(
                f"and {duration(minimums.months_to_payoff - schedule.months_to_payoff)} sooner",
                "good",
            )
        else:
            self.card_saved.set_value("—")
            self.card_saved.set_note("")

        self._fill_collateral()
        self._fill_queue()

    def _fill_interest(self, schedule) -> None:
        state = self.state
        lifetime = state.lifetime_interest()
        self.card_interest.set_value(money(lifetime))
        delta = state.interest_delta()
        months_delta = state.payoff_delta_months()
        pmi = f" + {money(schedule.total_fees)} PMI" if schedule and schedule.total_fees else ""
        if delta is None:
            self.card_interest.set_note(f"Baseline not captured yet{pmi}")
        elif delta > 0.5:
            note = f"{money(delta)} better than baseline" + (f" · {months_delta:+d} mo" if months_delta else "")
            self.card_interest.set_note(note + pmi, "good")
        elif delta < -0.5:
            note = f"{money(-delta)} worse than baseline" + (f" · {months_delta:+d} mo" if months_delta else "")
            self.card_interest.set_note(note + pmi, "bad")
        else:
            self.card_interest.set_note(f"Tracking the baseline plan{pmi}")

    def _fill_collateral(self) -> None:
        secured = [loan for loan in self.state.loans if loan.is_secured and loan.is_open]
        self.collateral.setVisible(bool(secured))
        if not secured:
            return
        value = sum(loan.asset_value for loan in secured)
        owed = sum(loan.payoff_amount for loan in secured)
        equity = value - owed
        self.card_equity.set_value(money(equity) if equity >= 0 else f"−{money(-equity)}")
        self.card_equity.set_tone("accent" if equity >= 0 else "warn")
        self.card_equity.set_note(
            f"{money(value)} of {', '.join(sorted({l.spec.asset_label.lower() for l in secured}))}"
            if equity >= 0 else "Underwater — you owe more than it's worth", "" if equity >= 0 else "bad"
        )
        ltv = owed / value if value else 0.0
        self.card_ltv.set_value(percent(ltv, 1))
        self.card_ltv.set_note("Balance ÷ current value")

        mortgages = [loan for loan in secured if loan.loan_type is LoanType.MORTGAGE]
        pmi_loans = [loan for loan in mortgages if loan.pmi_monthly > 0]
        schedule = self.state.schedule
        if pmi_loans:
            active = [loan for loan in pmi_loans if loan.pmi_active]
            if active:
                ends = [schedule.pmi_ends.get(loan.name) for loan in active] if schedule else []
                ends = [e for e in ends if e]
                self.card_pmi.set_value(f"{money(sum(l.pmi_monthly for l in active))}/mo")
                target = sum(
                    amortization.pmi_balance_target(l.original_value or l.asset_value) for l in active
                )
                self.card_pmi.set_note(
                    (f"Ends {max(ends):%b %Y} · " if ends else "") + f"at a {money(target)} balance"
                )
            else:
                self.card_pmi.set_value("Removed")
                self.card_pmi.set_note("Balance is under 78% of the original value", "good")
        else:
            self.card_pmi.set_value("None")
            self.card_pmi.set_note("")
        self.card_pmi.setVisible(bool(mortgages))

        if mortgages:
            housing = sum(loan.housing_payment for loan in mortgages)
            escrow = sum(loan.escrow_monthly for loan in mortgages)
            self.card_housing.set_value(money(housing))
            self.card_housing.set_note(f"P&I + {money(escrow)} escrow" + (" + PMI" if any(l.pmi_active for l in mortgages) else ""))
        else:
            underwater = [loan for loan in secured if loan.equity < 0]
            self.card_housing.set_value(str(len(underwater)) if underwater else "None")
            self.card_housing.set_note("Vehicles currently underwater" if underwater else "No vehicle is underwater")
        self.card_housing.set_caption("Housing payment / mo" if mortgages else "Underwater loans")

    def _fill_queue(self) -> None:
        ranked = self.state.priority_loans()
        schedule = self.state.schedule
        payoffs = schedule.loan_payoff_periods() if schedule else {}

        self.table.setRowCount(len(ranked))
        for row, loan in enumerate(ranked):
            is_target = row == 0
            months_left = loan.months_left_at_minimum
            values = [
                cell("TARGET" if is_target else str(row + 1),
                     bold=is_target, color=theme.ACCENT if is_target else ""),
                cell(loan.name, bold=is_target, tooltip=loan.servicer or loan.name),
                cell(loan.spec.label, color=loan.spec.color),
                cell(percent(loan.annual_rate), align_right=True, bold=True,
                     color=theme.WARN if loan.annual_rate >= 0.06 else ""),
                cell(money(loan.payoff_amount), align_right=True),
                cell(money(loan.accrued_interest), align_right=True, muted=True),
                cell(money(loan.effective_minimum), align_right=True),
                cell(duration(months_left) if months_left else "—", align_right=True, muted=True,
                     tooltip="Time left paying only the minimum"),
                cell(money(loan.daily_interest), align_right=True, muted=True),
                cell(payoffs[loan.name].strftime("%b %Y") if loan.name in payoffs else "—",
                     align_right=True, color=theme.ACCENT if is_target else ""),
            ]
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
        self.table.refit()
