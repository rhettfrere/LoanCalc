"""Interactive pyqtgraph charts with crosshair tracking and hover tooltips.

Every plot supports scroll-to-zoom, drag-to-pan and right-click-reset out of
the box. On top of that each chart publishes a themed hover card that follows
the cursor and reports the exact values under it, plus a clickable legend that
shows and hides individual series.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from datetime import date, datetime

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loancalc.core import theme
from loancalc.models import Schedule

pg.setConfigOption("background", theme.SURFACE)
pg.setConfigOption("foreground", theme.TEXT_MUTED)
pg.setConfigOptions(antialias=True)

#: Too many stacked bands turn into mush; the rest roll up into "Other loans".
MAX_SERIES = 9

HINT = "Hover for details · scroll to zoom · drag to pan · right-click for options"


def compact_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:,.2f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:,.1f}k"
    return f"{sign}${value:,.0f}"


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _stamp(day: date) -> float:
    return datetime(day.year, day.month, day.day).timestamp()


def _add_months(period: date, count: int) -> date:
    total = (period.year * 12 + period.month - 1) + count
    return date(total // 12, total % 12 + 1, 1)


def _rgba(hex_color: str, alpha: int) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


def _nearest(stamps: Sequence[float], x: float) -> int:
    index = bisect.bisect_left(stamps, x)
    if index and (
        index == len(stamps) or abs(stamps[index - 1] - x) < abs(stamps[index] - x)
    ):
        index -= 1
    return max(0, min(index, len(stamps) - 1))


def _elide(text: str, limit: int = 32) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class CurrencyAxis(pg.AxisItem):
    """Left axis that labels ticks as $1.2k / $45M instead of raw numbers."""

    def tickStrings(self, values, scale, spacing):  # noqa: N802 - pyqtgraph API
        return [compact_money(value) for value in values]


class CategoryAxis(pg.AxisItem):
    """Bottom axis driven by fixed string labels."""

    def __init__(self, **kwargs) -> None:
        super().__init__(orientation="bottom", **kwargs)

    def set_labels(self, labels: Sequence[str]) -> None:
        self.setTicks([[(index, label) for index, label in enumerate(labels)]])


class HoverCard(QFrame):
    """Floating, theme-styled readout that follows the cursor inside a plot."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            f"background-color: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER_STRONG};"
            " border-radius: 6px;"
        )
        self.setMaximumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self._label = QLabel()
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(400)
        self._label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self._label)
        self.hide()

    def show_html(self, html: str, cursor: QPoint) -> None:
        self._label.setText(html)
        self.adjustSize()
        bounds = self.parentWidget().rect()
        x = cursor.x() + 16
        y = cursor.y() + 16
        if x + self.width() > bounds.width() - 4:
            x = cursor.x() - self.width() - 16
        if y + self.height() > bounds.height() - 4:
            y = bounds.height() - self.height() - 4
        self.move(QPoint(max(4, x), max(4, y)))
        self.show()
        self.raise_()


class SeriesLegend(QWidget):
    """Clickable colour chips that show and hide individual series."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._hidden: set[str] = set()

        strip = QWidget()
        self._row = QHBoxLayout(strip)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(6)
        self._row.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(38)
        scroll.setWidget(strip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    @property
    def hidden(self) -> set[str]:
        return set(self._hidden)

    def set_series(self, series: Sequence[tuple[str, str]]) -> None:
        while self._row.count() > 1:
            item = self._row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._hidden &= {name for name, _ in series}

        for index, (name, color) in enumerate(series):
            swatch = QPixmap(10, 10)
            swatch.fill(QColor(color))
            button = QPushButton(QIcon(swatch), name)
            button.setCheckable(True)
            button.setChecked(name not in self._hidden)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"Click to hide or show '{name}'")
            button.setStyleSheet(
                "QPushButton { border: 1px solid %s; border-radius: 11px;"
                " padding: 3px 11px; font-size: 11px; background: %s; color: %s;"
                " font-weight: 600; min-height: 14px; }"
                "QPushButton:!checked { color: %s; background: %s; }"
                % (theme.BORDER, theme.SURFACE, theme.TEXT, theme.TEXT_MUTED, theme.HOVER)
            )
            button.toggled.connect(lambda visible, key=name: self._toggle(key, visible))
            self._row.insertWidget(index, button)

    def _toggle(self, name: str, visible: bool) -> None:
        if visible:
            self._hidden.discard(name)
        else:
            self._hidden.add(name)
        self.changed.emit()


class InteractiveChart(QWidget):
    """Base plot: themed axes, crosshair, hover card, legend and reset control."""

    def __init__(self, *, date_axis: bool = False, legend: bool = False) -> None:
        super().__init__()
        self.category_axis = None if date_axis else CategoryAxis()
        bottom = pg.DateAxisItem(orientation="bottom") if date_axis else self.category_axis
        self.plot = pg.PlotWidget(axisItems={"bottom": bottom, "left": CurrencyAxis("left")})
        self.plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot.setMinimumHeight(240)
        self.plot.setStyleSheet(
            f"border: 1px solid {theme.BORDER}; border-radius: 6px; background: {theme.SURFACE};"
        )

        item = self.plot.getPlotItem()
        item.showGrid(x=False, y=True, alpha=0.18)
        for side in ("left", "bottom"):
            item.getAxis(side).setTextPen(theme.TEXT_MUTED)
            item.getAxis(side).setPen(theme.BORDER)
        item.setMenuEnabled(True)
        item.vb.setDefaultPadding(0.03)

        self.vline = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen(theme.BORDER_STRONG, width=1, style=Qt.PenStyle.DashLine),
        )
        self.vline.setZValue(50)
        self.vline.hide()
        item.addItem(self.vline, ignoreBounds=True)

        self.marker = pg.ScatterPlotItem(
            size=9, brush=pg.mkBrush(theme.SURFACE), pen=pg.mkPen(theme.TEXT, width=2)
        )
        self.marker.setZValue(60)
        self.marker.hide()
        item.addItem(self.marker, ignoreBounds=True)

        self.hover = HoverCard(self.plot)

        footer = QHBoxLayout()
        footer.setContentsMargins(2, 0, 2, 0)
        hint = QLabel(HINT)
        hint.setProperty("role", "metricNote")
        reset = theme.quiet(QPushButton("Reset view"))
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self.reset_view)
        footer.addWidget(hint)
        footer.addStretch(1)
        footer.addWidget(reset)

        self.legend = SeriesLegend() if legend else None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if self.legend is not None:
            layout.addWidget(self.legend)
        layout.addWidget(self.plot, 1)
        layout.addLayout(footer)

        self._proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved, rateLimit=60, slot=self._mouse_moved
        )
        self.plot.installEventFilter(self)

    # --- interaction ------------------------------------------------------- #
    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Leave:
            self.clear_hover()
        return super().eventFilter(watched, event)

    def reset_view(self) -> None:
        self.plot.getPlotItem().enableAutoRange()
        self.clear_hover()

    def clear_hover(self) -> None:
        self.hover.hide()
        self.vline.hide()
        self.marker.hide()

    def _mouse_moved(self, event) -> None:
        position: QPointF = event[0]
        if not self.plot.sceneBoundingRect().contains(position):
            self.clear_hover()
            return
        point = self.plot.getPlotItem().vb.mapSceneToView(position)
        # QGraphicsView.mapFromScene returns QPoint on some Qt builds, QPointF on others.
        mapped = self.plot.mapFromScene(position)
        cursor = mapped if isinstance(mapped, QPoint) else mapped.toPoint()
        self.on_hover(point.x(), point.y(), cursor)

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        """Subclasses translate the cursor position into a tooltip."""
        self.clear_hover()

    def _place(self, x: float, y: float, html: str, cursor: QPoint) -> None:
        self.vline.setPos(x)
        self.vline.show()
        self.marker.setData([x], [y])
        self.marker.show()
        self.hover.show_html(html, cursor)

    # --- rendering helpers ------------------------------------------------- #
    def clear(self) -> None:
        item = self.plot.getPlotItem()
        for child in list(item.items):
            if child not in (self.vline, self.marker):
                item.removeItem(child)
        self.clear_hover()

    def show_message(self, message: str) -> None:
        self.clear()
        text = pg.TextItem(message, color=theme.TEXT_MUTED, anchor=(0.5, 0.5))
        self.plot.getPlotItem().addItem(text)
        text.setPos(0.5, 0.5)
        self.plot.getPlotItem().vb.autoRange()
        if self.legend is not None:
            self.legend.set_series([])

    @staticmethod
    def tooltip(header: str, rows: Sequence[tuple[str, str, str]], footer: str = "") -> str:
        """Build hover-card HTML from (swatch colour, label, value) rows."""
        parts = [
            f'<div style="font-size:11px;color:{theme.TEXT_MUTED};'
            f'letter-spacing:0.6px;font-weight:700;">{header}</div>',
            '<table cellspacing="0" cellpadding="0" style="margin-top:4px;">',
        ]
        for color, label, value in rows:
            dot = (
                f'<span style="color:{color};font-size:13px;">&#9632;</span>&nbsp;'
                if color
                else ""
            )
            parts.append(
                f'<tr><td style="padding:1px 14px 1px 0;font-size:12px;color:{theme.TEXT};">'
                f"{dot}{label}</td>"
                f'<td style="padding:1px 0;font-size:12px;font-weight:600;'
                f'color:{theme.TEXT};" align="right">{value}</td></tr>'
            )
        parts.append("</table>")
        if footer:
            parts.append(
                f'<div style="margin-top:5px;font-size:11px;'
                f'color:{theme.TEXT_MUTED};">{footer}</div>'
            )
        return "".join(parts)


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
        if self.legend is not None:
            self.legend.changed.connect(self._redraw)

    def render(self, schedule: Schedule | None) -> None:
        self._schedule = schedule
        if schedule is None or not schedule.months:
            self.show_message("No projection yet — add loans to see the burn-down.")
            return
        bands = _condense(schedule)
        if not bands:
            self.show_message("All loans are paid off. Nothing left to burn down.")
            return
        if self.legend is not None:
            self.legend.set_series(
                [
                    (name, theme.CHART_SERIES[index % len(theme.CHART_SERIES)])
                    for index, (name, _) in enumerate(bands)
                ]
            )
        self._redraw()

    def _redraw(self) -> None:
        schedule = self._schedule
        if schedule is None or not schedule.months:
            return
        hidden = self.legend.hidden if self.legend else set()
        all_bands = _condense(schedule)
        palette = {
            name: theme.CHART_SERIES[index % len(theme.CHART_SERIES)]
            for index, (name, _) in enumerate(all_bands)
        }

        self.clear()
        self._periods = [month.period for month in schedule.months]
        self._stamps = [_stamp(period) for period in self._periods]
        self._bands = [
            (name, palette[name], values)
            for name, values in all_bands
            if name not in hidden
        ]

        item = self.plot.getPlotItem()
        lower_values = [0.0] * len(self._stamps)
        for _, color, values in self._bands:
            upper_values = [low + value for low, value in zip(lower_values, values)]
            lower = pg.PlotCurveItem(self._stamps, lower_values, pen=pg.mkPen(None))
            upper = pg.PlotCurveItem(
                self._stamps, upper_values, pen=pg.mkPen(_rgba(color, 230), width=1)
            )
            item.addItem(lower)
            item.addItem(upper)
            item.addItem(
                pg.FillBetweenItem(lower, upper, brush=pg.mkBrush(_rgba(color, 165)))
            )
            lower_values = upper_values

        self._totals = lower_values
        item.addItem(
            pg.PlotCurveItem(self._stamps, self._totals, pen=pg.mkPen(theme.TEXT, width=2))
        )

        if schedule.payoff_date:
            item.addItem(
                pg.InfiniteLine(
                    pos=_stamp(schedule.payoff_date),
                    angle=90,
                    pen=pg.mkPen(theme.ACCENT, width=1.4, style=Qt.PenStyle.DashLine),
                    label=f"Debt-free {schedule.payoff_date:%b %Y}",
                    labelOpts={
                        "color": theme.ACCENT,
                        "position": 0.92,
                        "fill": _rgba(theme.SURFACE, 215),
                    },
                ),
                ignoreBounds=True,
            )

        item.vb.setLimits(yMin=0)
        item.enableAutoRange()

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._stamps or self._schedule is None:
            return
        index = _nearest(self._stamps, x)
        month = self._schedule.months[index]

        rows = [
            (color, _elide(name), _money(values[index]))
            for name, color, values in self._bands
            if values[index] > 0
        ]
        rows.append(("", "<b>Total balance</b>", f"<b>{_money(self._totals[index])}</b>"))

        footer = (
            f"Paid {_money(month.total_paid)} &nbsp;·&nbsp; "
            f"interest {_money(month.interest_paid)} &nbsp;·&nbsp; "
            f"principal {_money(month.principal_paid)}"
        )
        closed = month.loans_closed
        if closed:
            names = ", ".join(_elide(name, 28) for name in closed)
            footer += f"<br/><b style='color:{theme.ACCENT};'>Paid off: {names}</b>"

        self._place(
            self._stamps[index],
            self._totals[index],
            self.tooltip(self._periods[index].strftime("%B %Y").upper(), rows, footer),
            cursor,
        )


class PrincipalInterestChart(InteractiveChart):
    """Lifetime principal versus interest, your plan next to minimums-only."""

    def __init__(self) -> None:
        super().__init__(legend=True)
        self.plot.getPlotItem().setLabel("left", "Lifetime cost")
        self._bars: list[dict] = []
        self._principal_item: pg.BarGraphItem | None = None
        self._interest_item: pg.BarGraphItem | None = None
        if self.legend is not None:
            self.legend.set_series(
                [("Principal", theme.CHART_PRINCIPAL), ("Interest", theme.CHART_INTEREST)]
            )
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
                "months": schedule.months_to_payoff,
                "payoff": schedule.payoff_date,
                "complete": schedule.completed,
            }
            for label, schedule in entries
        ]

        if self.category_axis is not None:
            self.category_axis.set_labels(
                [f"{bar['label']}\n{bar['sub']}" for bar in self._bars]
            )

        item = self.plot.getPlotItem()
        positions = list(range(len(self._bars)))
        principal = [bar["principal"] for bar in self._bars]
        interest = [bar["interest"] for bar in self._bars]

        self._principal_item = pg.BarGraphItem(
            x=positions, height=principal, width=0.45,
            brush=pg.mkBrush(_rgba(theme.CHART_PRINCIPAL, 220)),
            pen=pg.mkPen(theme.CHART_PRINCIPAL),
        )
        self._interest_item = pg.BarGraphItem(
            x=positions, height=interest, y0=principal, width=0.45,
            brush=pg.mkBrush(_rgba(theme.CHART_INTEREST, 220)),
            pen=pg.mkPen(theme.CHART_INTEREST),
        )
        item.addItem(self._principal_item)
        item.addItem(self._interest_item)

        for position, bar in zip(positions, self._bars):
            total = bar["principal"] + bar["interest"]
            label = pg.TextItem(compact_money(total), color=theme.TEXT, anchor=(0.5, 1.3))
            label.setPos(position, total)
            item.addItem(label)

        item.vb.setLimits(yMin=0)
        item.setXRange(-0.6, len(self._bars) - 0.4, padding=0.05)
        item.enableAutoRange(axis="y")
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        if self._principal_item is None or self._interest_item is None:
            return
        hidden = self.legend.hidden if self.legend else set()
        self._principal_item.setOpts(
            brush=pg.mkBrush(_rgba(theme.CHART_PRINCIPAL, 25 if "Principal" in hidden else 220))
        )
        self._interest_item.setOpts(
            brush=pg.mkBrush(_rgba(theme.CHART_INTEREST, 25 if "Interest" in hidden else 220))
        )

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._bars:
            return
        index = round(x)
        if index < 0 or index >= len(self._bars) or abs(x - index) > 0.3:
            self.clear_hover()
            return

        bar = self._bars[index]
        total = bar["principal"] + bar["interest"]
        share = bar["interest"] / total * 100 if total else 0.0
        rows = [
            (theme.CHART_PRINCIPAL, "Principal", _money(bar["principal"])),
            (theme.CHART_INTEREST, "Interest", _money(bar["interest"])),
            ("", "<b>Total paid</b>", f"<b>{_money(total)}</b>"),
        ]
        footer = (
            f"Debt-free {bar['payoff']:%b %Y} &nbsp;·&nbsp; {bar['months']} payments"
            f"<br/>{share:.1f}% of every dollar goes to interest"
            if bar["complete"] and bar["payoff"]
            else "This allocation never clears the debt."
        )
        self._place(
            index, total, self.tooltip(f"{bar['label'].upper()} · {bar['sub']}", rows, footer), cursor
        )


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
        live = [entry for entry in plans if entry[1] and entry[1].months]
        self._plans = list(live)
        if not live:
            self.show_message("Nothing to compare yet.")
            return
        if self.legend is not None:
            self.legend.set_series([(name, color) for name, _, color, _ in live])
        self._redraw()

    def _redraw(self) -> None:
        if not self._plans:
            return
        hidden = self.legend.hidden if self.legend else set()
        self.clear()

        longest = max(len(schedule.months) for _, schedule, _, _ in self._plans)
        start = self._plans[0][1].months[0].period
        self._periods = [_add_months(start, offset) for offset in range(longest + 1)]
        self._stamps = [_stamp(period) for period in self._periods]

        item = self.plot.getPlotItem()
        for name, schedule, color, dashed in self._plans:
            if name in hidden:
                continue
            values = self._series_for(schedule, longest)
            pen = pg.mkPen(
                color,
                width=2.4,
                style=Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine,
            )
            item.addItem(pg.PlotCurveItem(self._stamps, values, pen=pen))
            if schedule.completed and schedule.payoff_date:
                payoff_index = len(schedule.months)
                item.addItem(
                    pg.ScatterPlotItem(
                        [self._stamps[payoff_index]], [0.0],
                        size=11, symbol="o",
                        brush=pg.mkBrush(color), pen=pg.mkPen(theme.SURFACE, width=2),
                    )
                )

        item.vb.setLimits(yMin=0)
        item.enableAutoRange()

    @staticmethod
    def _series_for(schedule: Schedule, longest: int) -> list[float]:
        """Starting balance, then each month's ending balance, padded with zeros."""
        values = [schedule.starting_balance]
        values += [month.ending_balance for month in schedule.months]
        values += [0.0] * (longest + 1 - len(values))
        return values[: longest + 1]

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._stamps or not self._plans:
            return
        hidden = self.legend.hidden if self.legend else set()
        index = _nearest(self._stamps, x)
        longest = max(len(schedule.months) for _, schedule, _, _ in self._plans)

        rows: list[tuple[str, str, str]] = []
        best = 0.0
        for name, schedule, color, _ in self._plans:
            if name in hidden:
                continue
            value = self._series_for(schedule, longest)[index]
            done = index > len(schedule.months)
            rows.append(
                (
                    color,
                    _elide(name, 26),
                    "Paid off" if value <= 0 and not done else _money(value),
                )
            )
            best = max(best, value)

        spread = ""
        values = [
            self._series_for(schedule, longest)[index]
            for name, schedule, _, _ in self._plans
            if name not in hidden
        ]
        if len(values) > 1:
            spread = f"Spread between plans: {_money(max(values) - min(values))}"

        self._place(
            self._stamps[index],
            best,
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
        hidden = self.legend.hidden if self.legend else set()

        self.clear()
        self._stamps = [_stamp(month.period) for month in schedule.months]

        item = self.plot.getPlotItem()
        lower_values = [0.0] * len(self._stamps)
        lower = pg.PlotCurveItem(self._stamps, lower_values, pen=pg.mkPen(None))
        item.addItem(lower)

        for name, values, color in (
            ("Principal", [m.principal_paid for m in schedule.months], theme.CHART_PRINCIPAL),
            ("Interest", [m.interest_paid for m in schedule.months], theme.CHART_INTEREST),
        ):
            if name in hidden:
                continue
            upper_values = [low + value for low, value in zip(lower_values, values)]
            upper = pg.PlotCurveItem(
                self._stamps, upper_values, pen=pg.mkPen(_rgba(color, 230), width=1.2)
            )
            item.addItem(upper)
            item.addItem(pg.FillBetweenItem(lower, upper, brush=pg.mkBrush(_rgba(color, 165))))
            lower, lower_values = upper, upper_values

        item.vb.setLimits(yMin=0)
        item.enableAutoRange()

    def on_hover(self, x: float, y: float, cursor: QPoint) -> None:
        if not self._stamps or self._schedule is None:
            return
        index = _nearest(self._stamps, x)
        month = self._schedule.months[index]
        rows = [
            (theme.CHART_PRINCIPAL, "Principal", _money(month.principal_paid)),
            (theme.CHART_INTEREST, "Interest", _money(month.interest_paid)),
            ("", "<b>Payment</b>", f"<b>{_money(month.total_paid)}</b>"),
            ("", "Balance after", _money(month.ending_balance)),
        ]
        share = month.interest_paid / month.total_paid * 100 if month.total_paid else 0.0
        self._place(
            self._stamps[index],
            month.total_paid,
            self.tooltip(
                month.period.strftime("%B %Y").upper(),
                rows,
                f"{share:.1f}% of this payment is interest",
            ),
            cursor,
        )
