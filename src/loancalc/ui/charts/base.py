"""Shared chart infrastructure: themed axes, crosshair, hover card, legend.

Every plot supports scroll-to-zoom, drag-to-pan and right-click-reset out of
the box. Subclasses implement `on_hover` to describe whatever is under the
cursor and use `tooltip()` to format it consistently.
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

from loancalc.ui import theme

pg.setConfigOption("background", theme.SURFACE)
pg.setConfigOption("foreground", theme.TEXT_MUTED)
pg.setConfigOptions(antialias=True)

HINT = "Hover for details · scroll to zoom · drag to pan · right-click for options"


def compact_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:,.2f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:,.1f}k"
    return f"{sign}${value:,.0f}"


def full_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def stamp(day: date) -> float:
    return datetime(day.year, day.month, day.day).timestamp()


def rgba(hex_color: str, alpha: int) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


def nearest(stamps: Sequence[float], x: float) -> int:
    index = bisect.bisect_left(stamps, x)
    if index and (
        index == len(stamps) or abs(stamps[index - 1] - x) < abs(stamps[index] - x)
    ):
        index -= 1
    return max(0, min(index, len(stamps) - 1))


def elide(text: str, limit: int = 32) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def date_marker(when: date, label: str, color: str, position: float = 0.92) -> pg.InfiniteLine:
    """Dashed vertical line with a label, for payoff and milestone dates."""
    return pg.InfiniteLine(
        pos=stamp(when),
        angle=90,
        pen=pg.mkPen(color, width=1.3, style=Qt.PenStyle.DashLine),
        label=label,
        labelOpts={"color": color, "position": position, "fill": rgba(theme.SURFACE, 215)},
    )


class CurrencyAxis(pg.AxisItem):
    """Left axis that labels ticks as $1.2k / $45M instead of raw numbers."""

    def tickStrings(self, values, scale, spacing):  # noqa: N802 - pyqtgraph API
        return [compact_money(value) for value in values]


class PercentAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):  # noqa: N802 - pyqtgraph API
        return [f"{value:.0f}%" for value in values]


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

    def __init__(
        self,
        *,
        date_axis: bool = False,
        legend: bool = False,
        left_axis: pg.AxisItem | None = None,
    ) -> None:
        super().__init__()
        self.category_axis = None if date_axis else CategoryAxis()
        bottom = pg.DateAxisItem(orientation="bottom") if date_axis else self.category_axis
        self.plot = pg.PlotWidget(
            axisItems={"bottom": bottom, "left": left_axis or CurrencyAxis("left")}
        )
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

    @property
    def hidden(self) -> set[str]:
        return self.legend.hidden if self.legend else set()

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

    def place(self, x: float, y: float, html: str, cursor: QPoint) -> None:
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

    def add_band(self, xs, lower, upper, color: str, alpha: int = 165):
        """Filled region between two series; returns the upper curve."""
        item = self.plot.getPlotItem()
        low = pg.PlotCurveItem(xs, lower, pen=pg.mkPen(None))
        high = pg.PlotCurveItem(xs, upper, pen=pg.mkPen(rgba(color, 230), width=1))
        item.addItem(low)
        item.addItem(high)
        item.addItem(pg.FillBetweenItem(low, high, brush=pg.mkBrush(rgba(color, alpha))))
        return high

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
