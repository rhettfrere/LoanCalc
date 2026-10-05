"""Reusable presentation widgets built on the shared theme."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from loancalc.ui import theme

#: Columns shrink to this before the table gives up and scrolls.
MIN_COLUMN_WIDTH = 46


class MetricCard(QFrame):
    """Headline number with a caption and an optional delta note."""

    def __init__(self, label: str, *, tone: str = "", note: str = "") -> None:
        super().__init__()
        self.setProperty("role", "card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(3)

        self._caption = QLabel(label.upper())
        self._caption.setProperty("role", "metricLabel")

        self._value = QLabel("—")
        self._value.setProperty("role", "metricValue")
        if tone:
            self._value.setProperty("tone", tone)

        self._note = QLabel(note)
        self._note.setProperty("role", "metricNote")
        self._note.setVisible(bool(note))

        layout.addWidget(self._caption)
        layout.addWidget(self._value)
        layout.addWidget(self._note)

    def set_value(self, text: str) -> None:
        self._value.setText(text)

    def set_caption(self, text: str) -> None:
        self._caption.setText(text.upper())

    def set_note(self, text: str, tone: str = "") -> None:
        self._note.setText(text)
        self._note.setProperty("tone", tone)
        self._note.setVisible(bool(text))
        theme.restyle(self._note)

    def set_tone(self, tone: str) -> None:
        self._value.setProperty("tone", tone)
        theme.restyle(self._value)


class Card(QFrame):
    """Titled surface that hosts a table, chart, or form."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setProperty("role", "card")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 16)
        self._layout.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(theme.section(title))
        if subtitle:
            self._subtitle = theme.subtitle(subtitle)
            header.addWidget(self._subtitle)
        else:
            self._subtitle = None
        self._layout.addLayout(header)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self._layout.addWidget(widget, stretch)

    def add_layout(self, layout, stretch: int = 0) -> None:
        self._layout.addLayout(layout, stretch)

    def set_subtitle(self, text: str) -> None:
        if self._subtitle is not None:
            self._subtitle.setText(text)


class DataTable(QTableWidget):
    """Table whose columns fill the viewport but stay user-draggable.

    Columns are sized to their content, then any leftover width is handed out
    in proportion so there is no dead space on the right. The moment the user
    drags a divider the table stops re-fitting until new data arrives.
    """

    def __init__(self, headers: list[str], *, editable: bool = False) -> None:
        super().__init__(0, len(headers))
        self._fitting = False
        self._user_sized = False

        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        if not editable:
            self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsMovable(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(MIN_COLUMN_WIDTH)
        header.sectionResized.connect(self._section_resized)
        header.sectionDoubleClicked.connect(self.refit)
        for index, label in enumerate(headers):
            item = self.horizontalHeaderItem(index)
            if item is not None:
                item.setToolTip(label)

    def _section_resized(self, *_args) -> None:
        if not self._fitting:
            self._user_sized = True

    def refit(self, *_args) -> None:
        """Re-measure and redistribute column widths."""
        self._user_sized = False
        self.autofit()

    def autofit(self) -> None:
        columns = self.columnCount()
        if self._fitting or self._user_sized or columns == 0:
            return
        self._fitting = True
        try:
            header = self.horizontalHeader()
            floors = [MIN_COLUMN_WIDTH] * columns
            widths = [
                max(self.sizeHintForColumn(index) + 16, header.sectionSizeHint(index) + 8)
                for index in range(columns)
            ]
            available = self.viewport().width()
            total = sum(widths) or 1

            if total < available:
                surplus = available - total
                widths = [width + surplus * width / total for width in widths]
            elif total > available:
                # Give back the slack above each column's floor, proportionally,
                # so the table fits instead of growing a scrollbar.
                slack = [width - floor for width, floor in zip(widths, floors)]
                spare = sum(slack)
                if spare > 0:
                    take = min(total - available, spare)
                    widths = [
                        width - take * portion / spare
                        for width, portion in zip(widths, slack)
                    ]

            for index, width in enumerate(widths):
                self.setColumnWidth(index, int(width))
        finally:
            self._fitting = False

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.autofit()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.autofit()

    def setRowCount(self, rows: int) -> None:  # noqa: N802 - Qt API
        super().setRowCount(rows)
        self._user_sized = False


def make_table(headers: list[str], *, editable: bool = False) -> DataTable:
    """A consistently configured, self-fitting table."""
    return DataTable(headers, editable=editable)


def cell(
    text: str,
    *,
    align_right: bool = False,
    bold: bool = False,
    color: str = "",
    muted: bool = False,
    tooltip: str = "",
) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    alignment = Qt.AlignmentFlag.AlignVCenter
    alignment |= Qt.AlignmentFlag.AlignRight if align_right else Qt.AlignmentFlag.AlignLeft
    item.setTextAlignment(alignment)
    if bold:
        font = item.font()
        font.setWeight(QFont.Weight.DemiBold)
        item.setFont(font)
    if color or muted:
        item.setForeground(QBrush(QColor(color or theme.TEXT_MUTED)))
    # Columns can shrink to fit, so keep the full text reachable on hover.
    item.setToolTip(tooltip or (text if len(text) > 16 else ""))
    return item


def money_spinbox(value: float = 0.0, maximum: float = 1_000_000.0, *, large: bool = False):
    box = QDoubleSpinBox()
    box.setRange(0.0, maximum)
    box.setDecimals(2)
    box.setSingleStep(100.0)
    box.setPrefix("$ ")
    box.setGroupSeparatorShown(True)
    box.setValue(value)
    box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if large:
        box.setProperty("scale", "large")
    return box


def labeled_row(label: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    row.addWidget(theme.field(label))
    row.addWidget(widget, 1)
    return row


def banner(text: str) -> QFrame:
    frame = QFrame()
    frame.setProperty("role", "banner")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 10)
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    return frame
