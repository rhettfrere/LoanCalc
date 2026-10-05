"""Process-wide themed QApplication."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from loancalc.core.theme import apply_theme

# Qt owns the C++ QApplication; without a module-level reference it can be
# garbage collected and the next widget construction aborts.
_app: QApplication | None = None


def get_app() -> QApplication:
    """Return the themed QApplication, creating it on first use."""
    global _app

    app = QApplication.instance()
    if app is None:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication(sys.argv)
        app.setApplicationName("LoanCalc")
        app.setApplicationDisplayName("LoanCalc — Student Loan Strategy")
        app.setOrganizationName("LoanCalc")
        apply_theme(app)

    _app = app
    return app
