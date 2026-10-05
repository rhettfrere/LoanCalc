"""Main window: menu bar, tabs, and the status line."""
from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QWidget,
)

from loancalc import __version__
from loancalc.core import theme
from loancalc.core.logging_setup import get_logger
from loancalc.formatting import money
from loancalc.ingest import IngestError
from loancalc.paths import database_path
from loancalc.state import AppState
from loancalc.ui.action_center import ActionCenterTab
from loancalc.ui.charts_tab import ChartsTab
from loancalc.ui.dashboard import DashboardTab
from loancalc.ui.history_tab import HistoryTab
from loancalc.ui.loans_tab import LoansTab
from loancalc.ui.sandbox import SandboxTab

log = get_logger(__name__)

IMPORT_FILTER = "Loan data (*.csv *.tsv *.txt);;All files (*.*)"


class MainWindow(QMainWindow):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.setWindowTitle("LoanCalc — Student Loan Strategy")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 720)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.dashboard = DashboardTab(state)
        self.action_center = ActionCenterTab(state)
        self.sandbox = SandboxTab(state)
        self.charts = ChartsTab(state)
        self.loans = LoansTab(state)
        self.history = HistoryTab(state)
        for widget, label in (
            (self.dashboard, "Dashboard"),
            (self.action_center, "Action Center"),
            (self.sandbox, "Sandbox"),
            (self.charts, "Visualizations"),
            (self.loans, "Loans"),
            (self.history, "History"),
        ):
            self.tabs.addTab(widget, label)

        self.setCentralWidget(self.tabs)
        self._build_menu()

        self.status_label = QLabel("Ready")
        self.status_label.setProperty("role", "status")
        self.statusBar().addWidget(self.status_label)
        self.balance_label = QLabel()
        self.balance_label.setProperty("role", "metric")
        self.statusBar().addPermanentWidget(self.balance_label)

        state.statusMessage.connect(self._set_status)
        state.scheduleChanged.connect(self._update_balance)
        self._update_balance()

    # --- menu -------------------------------------------------------------- #
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self._action(file_menu, "&Import User Data…", self._import, QKeySequence.StandardKey.Open)
        self._action(file_menu, "&Export Loans…", self._export_loans)
        self._action(file_menu, "Export &Schedule…", self._export_schedule)
        file_menu.addSeparator()
        self._action(file_menu, "&Reset to Bundled Data…", self._reset_sample)
        self._action(file_menu, "Clear Payment &History…", self._clear_history)
        file_menu.addSeparator()
        self._action(file_menu, "E&xit", self.close, QKeySequence.StandardKey.Quit)

        plan_menu = self.menuBar().addMenu("&Plan")
        self._action(plan_menu, "Re&calculate", self.state.recalculate, QKeySequence("F5"))
        self._action(plan_menu, "Reset &Baseline to Current Plan", self._rebase)

        help_menu = self.menuBar().addMenu("&Help")
        self._action(help_menu, "Where is my &data?", self._show_data_location)
        self._action(help_menu, "&About", self._about)

    def _action(self, menu, text: str, slot, shortcut=None) -> None:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)

    # --- file operations --------------------------------------------------- #
    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import loan data", str(Path.home()), IMPORT_FILTER
        )
        if not path:
            return
        confirm = QMessageBox.question(
            self,
            "Replace portfolio",
            "Importing replaces your current loans and clears logged payments.\n\n"
            "The file needs columns for loan name, balance, interest rate and "
            "minimum payment (CSV or TSV).\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            count = self.state.import_file(path)
        except IngestError as exc:
            log.warning("Import failed for %s: %s", path, exc)
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        QMessageBox.information(
            self, "Import complete", f"Loaded {count} loans from {Path(path).name}."
        )

    def _export_loans(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export loans", str(Path.home() / "loans.csv"), "CSV files (*.csv)"
        )
        if not path:
            return
        from loancalc.ingest import loans_to_frame

        loans_to_frame(self.state.loans).to_csv(path, index=False)
        self._set_status(f"Exported {len(self.state.loans)} loans to {Path(path).name}")

    def _export_schedule(self) -> None:
        schedule = self.state.schedule
        if not schedule or not schedule.months:
            QMessageBox.information(self, "Nothing to export", "There is no projection yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export schedule", str(Path.home() / "payoff_schedule.csv"), "CSV files (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["Month", "Starting balance", "Interest charged", "Payment",
                 "To interest", "To principal", "Ending balance", "Loans paid off"]
            )
            for month in schedule.months:
                writer.writerow(
                    [
                        month.period.isoformat(),
                        f"{month.starting_balance:.2f}",
                        f"{month.interest_charged:.2f}",
                        f"{month.total_paid:.2f}",
                        f"{month.interest_paid:.2f}",
                        f"{month.principal_paid:.2f}",
                        f"{month.ending_balance:.2f}",
                        "; ".join(month.loans_closed),
                    ]
                )
        self._set_status(f"Exported {len(schedule.months)} months to {Path(path).name}")

    def _reset_sample(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Reset data",
            "Restore the bundled starter dataset?\n\n"
            "Your current loans and payment history will be discarded.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.state.reset_to_sample()
        except IngestError as exc:
            QMessageBox.critical(self, "Reset failed", str(exc))

    def _clear_history(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Clear history",
            "Delete every logged payment? Loan balances stay as they are.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.state.store.clear_payments()
        self.state.store.set_setting("last_accrued_period", "")
        self.state.recalculate()
        self.state.historyChanged.emit()
        self._set_status("Payment history cleared.")

    def _rebase(self) -> None:
        self.state.capture_baseline()
        self._set_status("Baseline reset to the current plan.")

    # --- help -------------------------------------------------------------- #
    def _show_data_location(self) -> None:
        QMessageBox.information(
            self,
            "Data location",
            f"Your loans, payments and settings live in:\n\n{database_path()}\n\n"
            "Delete that file to start completely fresh.",
        )

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About LoanCalc",
            f"<b>LoanCalc {__version__}</b><br/><br/>"
            "Student loan tracking and repayment strategy.<br/>"
            "Avalanche and snowball payoff simulation with daily interest accrual.<br/><br/>"
            f"<span style='color:{theme.TEXT_MUTED}'>Built with PySide6, pandas and pyqtgraph."
            "</span>",
        )

    # --- status ------------------------------------------------------------ #
    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _update_balance(self) -> None:
        schedule = self.state.schedule
        payoff = (
            schedule.payoff_date.strftime("%b %Y")
            if schedule and schedule.completed and schedule.payoff_date
            else "—"
        )
        self.balance_label.setText(
            f"Balance {money(self.state.total_balance)}   ·   Debt-free {payoff}"
        )
