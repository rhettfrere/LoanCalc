"""Charts for a single plan: burn-down, lifetime cost, payment mix, scenarios."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pyqtgraph as pg
from PySide6.QtCore import QPoint, Qt

from loancalc.domain.models import Schedule
from loancalc.domain.periods import add_months
from loancalc.ui import theme
from loancalc.ui.charts.base import (
    InteractiveChart,
    compact_money,
    date_marker,
    elide,
    full_money,
    nearest,
    rgba,
    stamp,
)

#: Too many stacked bands turn into mush; the rest roll up into "Other loans".
MAX_SERIES = 9


def _condense(schedule: Schedule) -> list[tuple[str, list[float]]]:
    """Keep the largest loans as their own bands; roll the tail into one."""
    _, series = schedule.balance_series()
    ranked = sorted(series.items(), key=lambda kv: max(kv[1] or [0.0]), reverse=True)
    ranked = [(name, values) for name, values in ranked if max(values or [0.0]) > 0]
    if len(ranked) <= MAX_SERIES:
        return ranked
    head, tail = ranked[:MAX_SERIES], ranked[MAX_SERIES:]
    other = [sum(values[i] for _, values in tail) for i in range(len(schedule.months))]
    return head + [("Other loans", other)]


class BurndownChart(InteractiveChart):
    """Stacked area of every balance melting away, with a month-by-month readout."""

    def __init__(self) -> None:
        super().__init__(date_axis=True, legend=True)
        self.plot.getPlotItem().setLabel("left", "Outstanding balance")
        self._stamps: list[float] = []
        self._periods: list[date] = []
        self._bands: list[tuple[str, str, list[float]]] = []
        self._totals: list[float] = []
        self._schedule: Schedule | None = None
        self._colors: dict[str, str] = {}
        if self.legend is not None:
            self.legend.changed.connect(self._redraw)

    def render(self, schedule: Schedule | None, colors: dict[str, str] | None = None) -> None:
        """`colors` optionally pins a colour per loan name (e.g. by loan type)."""
        self._schedule = schedule
        self._colors = colors or {}
        if schedule is None or not schedule.months:
            self.show_message("No projection yet — add loans to see the burn-down.")
            return
        bands = _condense(schedule)
        if not bands:
            self.show_message("All loans are paid off. Nothing left to burn down.")
            return
        if self.legend is not None:
            self.legend.set_series([(name, self._color(i, name)) for i, (name, _) in enumerate(bands)])
        self._redraw()

    def _color(self, index: int, name: str) -> str:
        return self._colors.get(name) or theme.CHART_SERIES[index % len(theme.CHART_SERIES)]

    def _redraw(self) -> None:
        schedule = self._schedule
        if schedule is None or not schedule.months:
            return
        all_bands = _condense(schedule)
        palette = {name: self._color(i, name) for i, (name, _) in enumerate(all_bands)}

        self.clear()
        self._periods = [month.period for month in schedule.months]
        self._stamps = [stamp(period) for period in self._periods]
        self._bands = [
            (name, palette[name], values) for name, values in all_bands if name not in self.hidden
        ]

        lower = [0.0] * len(self._stamps)
        for _, color, values in self._bands:
            upper = [low + value for low, value in zip(lower, values)]
            self.add_band(self._stamps, lower, upper, color)
            lower = upper
        self._totals = lower

        item = self.plot.getPlotItem()
        item.addItem(pg.PlotCurveItem(self._stamps, self._totals, pen=pg.mkPen(theme.TEXT, width=2)))
        if schedule.payoff_date:
            item.addItem(
                date_marker(schedule.payoff_date, f"Debt-free {schedule.payoff_date:%b %Y}", theme.ACCENT),
                ignoreBounds=True,
            )
        for name, ends in schedule.pmi_ends.items():
            item.addItem(
                date_marker(ends, f"PMI ends {ends:%b %Y}", theme.CHART_FEES, position=0.75),
                ignoreBounds=True,
            )
        item.vb.setLimits(yMin=0)
        item.enableAutoRange()

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._stamps or self._schedule is None:
            return
        index = nearest(self._stamps, x)
        month = self._schedule.months[index]

        rows = [
            (color, elide(name), full_money(values[index]))
            for name, color, values in self._bands
            if values[index] > 0
        ]
        rows.append(("", "<b>Total balance</b>", f"<b>{full_money(self._totals[index])}</b>"))

        footer = (
            f"Paid {full_money(month.total_paid)} &nbsp;·&nbsp; "
            f"interest {full_money(month.interest_paid)} &nbsp;·&nbsp; "
            f"principal {full_money(month.principal_paid)}"
        )
        if month.fees_paid:
            footer += f"<br/>PMI {full_money(month.fees_paid)}"
        if month.escrow_paid:
            footer += f"{' · ' if month.fees_paid else '<br/>'}escrow {full_money(month.escrow_paid)}"
        closed = month.loans_closed
        if closed:
            names = ", ".join(elide(name, 28) for name in closed)
            footer += f"<br/><b style='color:{theme.ACCENT};'>Paid off: {names}</b>"

        self.place(
            self._stamps[index],
            self._totals[index],
            self.tooltip(self._periods[index].strftime("%B %Y").upper(), rows, footer),
            cursor,
        )


class PrincipalInterestChart(InteractiveChart):
    """Lifetime principal vs interest (and PMI), your plan next to minimums-only."""

    SEGMENTS = (
        ("Principal", "principal", theme.CHART_PRINCIPAL),
        ("Interest", "interest", theme.CHART_INTEREST),
        ("PMI", "fees", theme.CHART_FEES),
    )

    def __init__(self) -> None:
        super().__init__(legend=True)
        self.plot.getPlotItem().setLabel("left", "Lifetime cost")
        self._bars: list[dict] = []
        self._items: dict[str, pg.BarGraphItem] = {}
        if self.legend is not None:
            self.legend.changed.connect(self._apply_visibility)

    def render(self, plan: Schedule | None, minimums: Schedule | None) -> None:
        if plan is None or not plan.months:
            self.show_message("No projection yet.")
            return

        self.clear()
        entries = [("Your plan", plan)]
        if minimums and minimums.months:
            entries.append(("Minimums only", minimums))

        self._bars = [
            {
                "label": label,
                "sub": f"{compact_money(schedule.monthly_budget)}/mo",
                "principal": schedule.total_principal,
                "interest": schedule.total_interest,
                "fees": schedule.total_fees,
                "months": schedule.months_to_payoff,
                "payoff": schedule.payoff_date,
                "complete": schedule.completed,
            }
            for label, schedule in entries
        ]
        has_fees = any(bar["fees"] > 0 for bar in self._bars)
        segments = [s for s in self.SEGMENTS if s[1] != "fees" or has_fees]
        if self.legend is not None:
            self.legend.set_series([(name, color) for name, _, color in segments])

        if self.category_axis is not None:
            self.category_axis.set_labels([f"{bar['label']}\n{bar['sub']}" for bar in self._bars])

        item = self.plot.getPlotItem()
        positions = list(range(len(self._bars)))
        base = [0.0] * len(self._bars)
        self._items.clear()
        for name, key, color in segments:
            heights = [bar[key] for bar in self._bars]
            bars = pg.BarGraphItem(
                x=positions, height=heights, y0=list(base), width=0.45,
                brush=pg.mkBrush(rgba(color, 220)), pen=pg.mkPen(color),
            )
            item.addItem(bars)
            self._items[name] = bars
            base = [b + h for b, h in zip(base, heights)]

        for position, total in zip(positions, base):
            label = pg.TextItem(compact_money(total), color=theme.TEXT, anchor=(0.5, 1.3))
            label.setPos(position, total)
            item.addItem(label)

        item.vb.setLimits(yMin=0)
        item.setXRange(-0.6, len(self._bars) - 0.4, padding=0.05)
        item.enableAutoRange(axis="y")
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        for name, key, color in self.SEGMENTS:
            bars = self._items.get(name)
            if bars is not None:
                bars.setOpts(brush=pg.mkBrush(rgba(color, 25 if name in self.hidden else 220)))

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._bars:
            return
        index = round(x)
        if index < 0 or index >= len(self._bars) or abs(x - index) > 0.3:
            self.clear_hover()
            return

        bar = self._bars[index]
        total = bar["principal"] + bar["interest"] + bar["fees"]
        cost = bar["interest"] + bar["fees"]
        share = cost / total * 100 if total else 0.0
        rows = [
            (theme.CHART_PRINCIPAL, "Principal", full_money(bar["principal"])),
            (theme.CHART_INTEREST, "Interest", full_money(bar["interest"])),
        ]
        if bar["fees"]:
            rows.append((theme.CHART_FEES, "PMI", full_money(bar["fees"])))
        rows.append(("", "<b>Total paid</b>", f"<b>{full_money(total)}</b>"))
        footer = (
            f"Debt-free {bar['payoff']:%b %Y} &nbsp;·&nbsp; {bar['months']} payments"
            f"<br/>{share:.1f}% of every dollar is the cost of borrowing"
            if bar["complete"] and bar["payoff"]
            else "This allocation never clears the debt."
        )
        self.place(index, total, self.tooltip(f"{bar['label'].upper()} · {bar['sub']}", rows, footer), cursor)


class ScenarioChart(InteractiveChart):
    """Total balance over time for several plans at once.

    Projections start from today's real balances, so everything already paid
    and every dollar of interest accrued so far is baked in.
    """

    def __init__(self) -> None:
        super().__init__(date_axis=True, legend=True)
        self.plot.getPlotItem().setLabel("left", "Total balance")
        self._plans: list[tuple[str, Schedule, str, bool]] = []
        self._periods: list[date] = []
        self._stamps: list[float] = []
        if self.legend is not None:
            self.legend.changed.connect(self._redraw)

    def render(self, plans: Sequence[tuple[str, Schedule, str, bool]]) -> None:
        """`plans` is a sequence of (name, schedule, colour, dashed)."""
        self._plans = [entry for entry in plans if entry[1] and entry[1].months]
        if not self._plans:
            self.show_message("Nothing to compare yet.")
            return
        if self.legend is not None:
            self.legend.set_series([(name, color) for name, _, color, _ in self._plans])
        self._redraw()

    @property
    def _longest(self) -> int:
        return max(len(schedule.months) for _, schedule, _, _ in self._plans)

    def _redraw(self) -> None:
        if not self._plans:
            return
        self.clear()
        longest = self._longest
        start = self._plans[0][1].months[0].period
        self._periods = [add_months(start, offset) for offset in range(longest + 1)]
        self._stamps = [stamp(period) for period in self._periods]

        item = self.plot.getPlotItem()
        for name, schedule, color, dashed in self._plans:
            if name in self.hidden:
                continue
            pen = pg.mkPen(
                color, width=2.4,
                style=Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine,
            )
            item.addItem(pg.PlotCurveItem(self._stamps, self._series_for(schedule, longest), pen=pen))
            if schedule.completed and schedule.payoff_date:
                item.addItem(
                    pg.ScatterPlotItem(
                        [self._stamps[len(schedule.months)]], [0.0], size=11, symbol="o",
                        brush=pg.mkBrush(color), pen=pg.mkPen(theme.SURFACE, width=2),
                    )
                )
        item.vb.setLimits(yMin=0)
        item.enableAutoRange()

    @staticmethod
    def _series_for(schedule: Schedule, longest: int) -> list[float]:
        """Starting balance, then each month's ending balance, padded with zeros."""
        values = [schedule.starting_balance] + [month.ending_balance for month in schedule.months]
        values += [0.0] * (longest + 1 - len(values))
        return values[: longest + 1]

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._stamps or not self._plans:
            return
        index = nearest(self._stamps, x)
        longest = self._longest

        rows: list[tuple[str, str, str]] = []
        values: list[float] = []
        for name, schedule, color, _ in self._plans:
            if name in self.hidden:
                continue
            value = self._series_for(schedule, longest)[index]
            values.append(value)
            rows.append((color, elide(name, 26), "Paid off" if value <= 0 else full_money(value)))

        spread = (
            f"Spread between plans: {full_money(max(values) - min(values))}"
            if len(values) > 1 else ""
        )
        self.place(
            self._stamps[index],
            max(values or [0.0]),
            self.tooltip(self._periods[index].strftime("%B %Y").upper(), rows, spread),
            cursor,
        )


class MonthlySplitChart(InteractiveChart):
    """Monthly interest versus principal — shows exactly where the crossover is."""

    def __init__(self) -> None:
        super().__init__(date_axis=True, legend=True)
        self.plot.getPlotItem().setLabel("left", "Monthly payment split")
        self._stamps: list[float] = []
        self._schedule: Schedule | None = None
        if self.legend is not None:
            self.legend.set_series(
                [("Principal", theme.CHART_PRINCIPAL), ("Interest", theme.CHART_INTEREST)]
            )
            self.legend.changed.connect(self._redraw)

    def render(self, schedule: Schedule | None) -> None:
        self._schedule = schedule
        if schedule is None or not schedule.months:
            self.show_message("No projection yet.")
            return
        self._redraw()

    def _redraw(self) -> None:
        schedule = self._schedule
        if schedule is None or not schedule.months:
            return
        self.clear()
        self._stamps = [stamp(month.period) for month in schedule.months]

        lower = [0.0] * len(self._stamps)
        for name, values, color in (
            ("Principal", [m.principal_paid for m in schedule.months], theme.CHART_PRINCIPAL),
            ("Interest", [m.interest_paid for m in schedule.months], theme.CHART_INTEREST),
        ):
            if name in self.hidden:
                continue
            upper = [low + value for low, value in zip(lower, values)]
            self.add_band(self._stamps, lower, upper, color)
            lower = upper

        item = self.plot.getPlotItem()
        item.vb.setLimits(yMin=0)
        item.enableAutoRange()

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._stamps or self._schedule is None:
            return
        index = nearest(self._stamps, x)
        month = self._schedule.months[index]
        rows = [
            (theme.CHART_PRINCIPAL, "Principal", full_money(month.principal_paid)),
            (theme.CHART_INTEREST, "Interest", full_money(month.interest_paid)),
            ("", "<b>Payment</b>", f"<b>{full_money(month.total_paid)}</b>"),
            ("", "Balance after", full_money(month.ending_balance)),
        ]
        share = month.interest_paid / month.total_paid * 100 if month.total_paid else 0.0
        self.place(
            self._stamps[index],
            month.total_paid,
            self.tooltip(
                month.period.strftime("%B %Y").upper(), rows,
                f"{share:.1f}% of this payment is interest",
            ),
            cursor,
        )
