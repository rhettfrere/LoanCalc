"""Collateral charts for secured debt (mortgages, auto loans).

Plots the asset's projected value against the loan balance under your plan and
under the contractual schedule. Equity is shaded green, being underwater (owing
more than the asset is worth — common early in an auto loan) is shaded red,
and for mortgages the 80% / 78% LTV PMI thresholds are drawn as guides.
"""
from __future__ import annotations

from datetime import date

import pyqtgraph as pg
from PySide6.QtCore import QPoint, Qt

from loancalc.domain import amortization
from loancalc.domain.loan_types import LoanType
from loancalc.domain.models import Loan, Schedule
from loancalc.domain.periods import add_months
from loancalc.ui import theme
from loancalc.ui.charts.base import (
    InteractiveChart,
    date_marker,
    full_money,
    nearest,
    rgba,
    stamp,
)


def _loan_series(loan: Loan, schedule: Schedule | None, length: int) -> list[float]:
    values = [loan.payoff_amount]
    if schedule is not None:
        values += [month.balances.get(loan.name, 0.0) for month in schedule.months]
    values += [0.0] * (length - len(values))
    return values[:length]


class EquityChart(InteractiveChart):
    def __init__(self) -> None:
        super().__init__(date_axis=True, legend=True)
        self.plot.getPlotItem().setLabel("left", "Value / balance")
        self._loan: Loan | None = None
        self._periods: list[date] = []
        self._stamps: list[float] = []
        self._asset: list[float] = []
        self._plan: list[float] = []
        self._scheduled: list[float] = []
        self._plan_schedule: Schedule | None = None
        self._scheduled_schedule: Schedule | None = None
        if self.legend is not None:
            self.legend.changed.connect(self._redraw)

    def render(self, loan: Loan | None, plan: Schedule | None, scheduled: Schedule | None) -> None:
        self._loan, self._plan_schedule, self._scheduled_schedule = loan, plan, scheduled
        if loan is None or loan.asset_value <= 0:
            self.show_message(
                "Add a home or vehicle value to a mortgage or auto loan to see its equity."
            )
            return
        series = [
            ("Asset value", theme.CHART_ASSET),
            ("Balance (your plan)", theme.TEXT),
            ("Balance (scheduled)", theme.TEXT_MUTED),
        ]
        if loan.loan_type is LoanType.MORTGAGE and loan.pmi_monthly > 0:
            series.append(("PMI thresholds", theme.CHART_FEES))
        if self.legend is not None:
            self.legend.set_series(series)
        self._redraw()

    def _redraw(self) -> None:
        loan = self._loan
        if loan is None or loan.asset_value <= 0:
            return
        plan, scheduled = self._plan_schedule, self._scheduled_schedule
        source = next((s for s in (plan, scheduled) if s and s.months), None)
        if source is None:
            self.show_message("No projection yet.")
            return
        length = 1 + max(len(s.months) for s in (plan, scheduled) if s)
        start = source.months[0].period

        self.clear()
        # Index 0 is "today"; index n is the end of month n.
        self._periods = [add_months(start, offset) for offset in range(length)]
        self._stamps = [stamp(period) for period in self._periods]
        self._asset = [
            amortization.asset_value_at(loan.asset_value, loan.growth, offset)
            for offset in range(length)
        ]
        self._plan = _loan_series(loan, plan, length)
        self._scheduled = _loan_series(loan, scheduled, length)

        item = self.plot.getPlotItem()
        hidden = self.hidden
        if "Asset value" not in hidden and "Balance (your plan)" not in hidden:
            pairs = list(zip(self._asset, self._plan))
            self.add_band(
                self._stamps, self._plan, [max(a, b) for a, b in pairs],
                theme.CHART_EQUITY, alpha=70,
            )
            self.add_band(
                self._stamps, [min(a, b) for a, b in pairs], [b if b > a else min(a, b) for a, b in pairs],
                theme.DANGER, alpha=60,
            )

        if "Asset value" not in hidden:
            item.addItem(pg.PlotCurveItem(self._stamps, self._asset, pen=pg.mkPen(theme.CHART_ASSET, width=2.4)))
        if "Balance (scheduled)" not in hidden:
            item.addItem(
                pg.PlotCurveItem(
                    self._stamps, self._scheduled,
                    pen=pg.mkPen(theme.TEXT_MUTED, width=1.6, style=Qt.PenStyle.DashLine),
                )
            )
        if "Balance (your plan)" not in hidden:
            item.addItem(pg.PlotCurveItem(self._stamps, self._plan, pen=pg.mkPen(theme.TEXT, width=2.4)))

        if loan.loan_type is LoanType.MORTGAGE and loan.pmi_monthly > 0 and "PMI thresholds" not in hidden:
            basis = loan.original_value or loan.asset_value
            for ltv, label in (
                (amortization.PMI_REQUEST_LTV, "80% LTV — request PMI removal"),
                (amortization.PMI_AUTO_CANCEL_LTV, "78% LTV — PMI cancels"),
            ):
                item.addItem(
                    pg.InfiniteLine(
                        pos=basis * ltv, angle=0,
                        pen=pg.mkPen(theme.CHART_FEES, width=1, style=Qt.PenStyle.DotLine),
                        label=label,
                        labelOpts={"color": theme.CHART_FEES, "position": 0.86,
                                   "fill": rgba(theme.SURFACE, 215)},
                    ),
                    ignoreBounds=True,
                )
            if plan and loan.name in plan.pmi_ends:
                ends = plan.pmi_ends[loan.name]
                item.addItem(date_marker(ends, f"PMI ends {ends:%b %Y}", theme.CHART_FEES, 0.6), ignoreBounds=True)

        if plan:
            payoff = plan.loan_payoff_periods().get(loan.name)
            if payoff:
                item.addItem(date_marker(payoff, f"Paid off {payoff:%b %Y}", theme.ACCENT), ignoreBounds=True)

        item.vb.setLimits(yMin=0)
        item.enableAutoRange()

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        loan = self._loan
        if not self._stamps or loan is None:
            return
        index = nearest(self._stamps, x)
        asset, balance, scheduled = self._asset[index], self._plan[index], self._scheduled[index]
        equity = asset - balance
        rows = [
            (theme.CHART_ASSET, loan.spec.asset_label or "Asset value", full_money(asset)),
            (theme.TEXT, "Balance (your plan)", full_money(balance)),
            (theme.TEXT_MUTED, "Balance (scheduled)", full_money(scheduled)),
            (theme.CHART_EQUITY if equity >= 0 else theme.DANGER,
             "<b>Equity</b>" if equity >= 0 else "<b>Underwater</b>",
             f"<b>{full_money(abs(equity))}</b>"),
        ]
        notes = []
        if asset > 0:
            notes.append(f"Loan-to-value {balance / asset * 100:.1f}%")
        if loan.loan_type is LoanType.MORTGAGE and loan.pmi_monthly > 0:
            basis = loan.original_value or loan.asset_value
            notes.append("PMI active" if amortization.pmi_applies(balance, basis) else "No PMI")
        ahead = scheduled - balance
        if ahead > 0.5:
            notes.append(f"{full_money(ahead)} ahead of schedule")
        self.place(
            self._stamps[index], max(asset, balance),
            self.tooltip(self._periods[index].strftime("%B %Y").upper(), rows, " · ".join(notes)),
            cursor,
        )
