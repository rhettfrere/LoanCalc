"""Household charts: how every active plan moves together over time."""
from __future__ import annotations

from datetime import date

import pyqtgraph as pg
from PySide6.QtCore import QPoint, Qt

from loancalc.domain.household import HouseholdSchedule
from loancalc.ui import theme
from loancalc.ui.charts.base import (
    InteractiveChart,
    date_marker,
    elide,
    full_money,
    nearest,
    stamp,
)


class _HouseholdBase(InteractiveChart):
    def __init__(self, label: str) -> None:
        super().__init__(date_axis=True, legend=True)
        self.plot.getPlotItem().setLabel("left", label)
        self._schedule: HouseholdSchedule | None = None
        self._compare: HouseholdSchedule | None = None
        self._colors: dict[int, str] = {}
        self._stamps: list[float] = []
        self._periods: list[date] = []
        self._layers: list[tuple[int, str, str, list[float]]] = []
        self._totals: list[float] = []
        if self.legend is not None:
            self.legend.changed.connect(self._redraw)

    def render(
        self,
        schedule: HouseholdSchedule | None,
        colors: dict[int, str],
        compare: HouseholdSchedule | None = None,
    ) -> None:
        self._schedule, self._colors, self._compare = schedule, colors, compare
        if schedule is None or not schedule.months:
            self.show_message("No active plans with debt. Add loans or activate a plan.")
            return
        if self.legend is not None:
            entries = [(o.plan.name, colors.get(k, theme.TEXT)) for k, o in schedule.outcomes.items()]
            if compare is not None and compare is not schedule:
                entries.append((self._compare_label(), theme.TEXT_MUTED))
            self.legend.set_series(entries)
        self._redraw()

    def _compare_label(self) -> str:
        return "Without rollover"

    def _values(self, key: int) -> list[float]:
        raise NotImplementedError

    def _redraw(self) -> None:
        schedule = self._schedule
        if schedule is None or not schedule.months:
            return
        self.clear()
        self._periods = [month.period for month in schedule.months]
        self._stamps = [stamp(period) for period in self._periods]

        self._layers = []
        lower = [0.0] * len(self._stamps)
        for key, outcome in schedule.outcomes.items():
            name = outcome.plan.name
            if name in self.hidden:
                continue
            values = self._values(key)
            if max(values or [0.0]) <= 0:
                continue
            color = self._colors.get(key, theme.TEXT)
            upper = [low + value for low, value in zip(lower, values)]
            self.add_band(self._stamps, lower, upper, color)
            self._layers.append((key, name, color, values))
            lower = upper
        self._totals = lower

        item = self.plot.getPlotItem()
        item.addItem(pg.PlotCurveItem(self._stamps, self._totals, pen=pg.mkPen(theme.TEXT, width=1.8)))
        self._decorate(item)
        item.vb.setLimits(yMin=0)
        item.enableAutoRange()

    def _decorate(self, item) -> None:
        schedule = self._schedule
        for month in schedule.months:
            for name in month.plans_completed:
                key = next((k for k, o in schedule.outcomes.items() if o.plan.name == name), None)
                color = self._colors.get(key, theme.ACCENT)
                item.addItem(date_marker(month.period, f"{name} done", color, 0.9), ignoreBounds=True)


class HouseholdBalanceChart(_HouseholdBase):
    """Stacked balance by plan, with the no-rollover total as a dashed reference."""

    def __init__(self) -> None:
        super().__init__("Household balance")

    def _values(self, key: int) -> list[float]:
        return self._schedule.outcomes[key].balances

    def _decorate(self, item) -> None:
        super()._decorate(item)
        compare = self._compare
        if compare is None or compare is self._schedule or self._compare_label() in self.hidden:
            return
        stamps = [stamp(month.period) for month in compare.months]
        totals = [month.ending_balance for month in compare.months]
        item.addItem(
            pg.PlotCurveItem(
                stamps, totals,
                pen=pg.mkPen(theme.TEXT_MUTED, width=1.8, style=Qt.PenStyle.DashLine),
            )
        )

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._stamps or self._schedule is None:
            return
        index = nearest(self._stamps, x)
        month = self._schedule.months[index]
        rows = [
            (color, elide(name, 26), full_money(values[index]))
            for _, name, color, values in self._layers
            if values[index] > 0
        ]
        rows.append(("", "<b>Household balance</b>", f"<b>{full_money(self._totals[index])}</b>"))
        compare = self._compare
        if compare is not None and compare is not self._schedule:
            other = compare.months[index].ending_balance if index < len(compare.months) else 0.0
            rows.append((theme.TEXT_MUTED, "Without rollover", full_money(other)))
        footer = (
            f"Paid {full_money(month.total_paid)} · interest {full_money(month.interest_paid)}"
        )
        if month.rolled:
            footer += f"<br/><b style='color:{theme.ACCENT};'>{full_money(month.rolled)} rolled over from finished plans</b>"
        if month.plans_completed:
            footer += f"<br/><b style='color:{theme.ACCENT};'>Paid off: {', '.join(month.plans_completed)}</b>"
        self.place(
            self._stamps[index], self._totals[index],
            self.tooltip(self._periods[index].strftime("%B %Y").upper(), rows, footer), cursor,
        )


class HouseholdCashFlowChart(_HouseholdBase):
    """Where each month's money goes — finished plans hand their budget onward."""

    def __init__(self) -> None:
        super().__init__("Monthly payments by plan")

    def _values(self, key: int) -> list[float]:
        return self._schedule.outcomes[key].paid

    def _compare_label(self) -> str:
        return ""

    def render(self, schedule, colors, compare=None) -> None:
        super().render(schedule, colors, None)

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._stamps or self._schedule is None:
            return
        index = nearest(self._stamps, x)
        month = self._schedule.months[index]
        rows = [
            (color, elide(name, 26), full_money(values[index]))
            for _, name, color, values in self._layers
            if values[index] > 0
        ]
        rows.append(("", "<b>Total paid</b>", f"<b>{full_money(self._totals[index])}</b>"))
        footer = ""
        if month.rolled:
            footer = f"Includes {full_money(month.rolled)} redirected from finished plans"
        self.place(
            self._stamps[index], self._totals[index],
            self.tooltip(self._periods[index].strftime("%B %Y").upper(), rows, footer), cursor,
        )
