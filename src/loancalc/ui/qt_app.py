"""Process-wide themed QApplication."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from loancalc.data.paths import icon_path
from loancalc.ui.theme import apply_theme

# Qt owns the C++ QApplication; without a module-level reference it can be
# garbage collected and the next widget construction aborts.
_app: QApplication | None = None


def get_app() -> QApplication:
    """Return the themed QApplication, creating it on first use."""
    global _app

    app = QApplication.instance()
    if app is None:
        if sys.platform == "win32":
            # Without an explicit AppUserModelID the taskbar shows python.exe's icon.
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LoanCalc.Desktop")
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication(sys.argv)
        app.setApplicationName("LoanCalc")
        app.setApplicationDisplayName("LoanCalc")
        app.setOrganizationName("LoanCalc")
        icon = icon_path()
        if icon is not None:
            app.setWindowIcon(QIcon(str(icon)))
        apply_theme(app)

    _app = app
    return app
