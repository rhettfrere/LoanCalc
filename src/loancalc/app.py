"""Application bootstrap."""
from __future__ import annotations

import sys
import traceback
from types import TracebackType

from PySide6.QtWidgets import QMessageBox

from loancalc.core.logging_setup import get_logger
from loancalc.core.qt_app import get_app
from loancalc.paths import database_path
from loancalc.state import AppState
from loancalc.storage import Store
from loancalc.ui.main_window import MainWindow

log = get_logger(__name__)


def _install_excepthook() -> None:
    """A windowed build has no console, so surface crashes in a dialog."""

    def hook(
        kind: type[BaseException], value: BaseException, tb: TracebackType | None
    ) -> None:
        log.error("Unhandled exception", exc_info=(kind, value, tb))
        QMessageBox.critical(
            None,
            "LoanCalc error",
            f"{kind.__name__}: {value}\n\n" + "".join(traceback.format_tb(tb))[-1500:],
        )

    sys.excepthook = hook


def run() -> int:
    app = get_app()
    _install_excepthook()

    store = Store(database_path())
    state = AppState(store)
    window = MainWindow(state)
    window.show()
    log.info("LoanCalc started with %d loans", len(state.loans))

    code = app.exec()
    store.close()
    return code
