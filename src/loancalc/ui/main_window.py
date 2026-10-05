"""Main window: plan selector, tabs, menus and the status line."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from loancalc import __version__
from loancalc.data import export
from loancalc.data.ingest import IngestError, load_loans
from loancalc.data.paths import backup_dir, database_path
from loancalc.data.storage import StoreError
from loancalc.services.state import AppState
from loancalc.ui import theme
from loancalc.ui.dialogs.help_dialog import HelpDialog
from loancalc.ui.dialogs.import_dialog import ImportDialog
from loancalc.ui.dialogs.loan_dialog import LoanDialog
from loancalc.ui.dialogs.plan_dialog import PlanManagerDialog
from loancalc.ui.tabs.action_center import ActionCenterTab
from loancalc.ui.tabs.dashboard import DashboardTab
from loancalc.ui.tabs.history import HistoryTab
from loancalc.ui.tabs.household import HouseholdTab
from loancalc.ui.tabs.loans import LoansTab
from loancalc.ui.tabs.sandbox import SandboxTab
from loancalc.ui.tabs.visualizations import VisualizationsTab
from loancalc.util.formatting import money
from loancalc.util.logging_setup import get_logger

log = get_logger(__name__)

IMPORT_FILTER = "Loan data (*.csv *.tsv *.txt);;All files (*.*)"
CSV_FILTER = "CSV files (*.csv)"
BACKUP_FILTER = "LoanCalc backup (*.db);;All files (*.*)"


class MainWindow(QMainWindow):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.setWindowTitle("LoanCalc — Debt Payoff Planner")
        self.resize(1440, 920)
        self.setMinimumSize(1100, 720)

        self.household = HouseholdTab(state)
        self.dashboard = DashboardTab(state)
        self.action_center = ActionCenterTab(state)
        self.sandbox = SandboxTab(state)
        self.charts = VisualizationsTab(state)
        self.loans = LoansTab(state)
        self.history = HistoryTab(state)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for widget, label, tip in (
            (self.household, "Household", "All active plans together, with rollover between them"),
            (self.dashboard, "Dashboard", "Overview of the selected plan"),
            (self.action_center, "Action Center", "Log this month's payment for the selected plan"),
            (self.sandbox, "Sandbox", "What-if scenarios and pins for the selected plan"),
            (self.charts, "Visualizations", "Charts for the selected plan"),
            (self.loans, "Loans", "Every loan in every plan"),
            (self.history, "History", "Logged payments"),
        ):
            index = self.tabs.addTab(widget, label)
            self.tabs.setTabToolTip(index, tip)
        self.tabs.currentChanged.connect(self._tab_changed)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_plan_bar())
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self._build_menu()

        self.status_label = QLabel("Ready")
        self.status_label.setProperty("role", "status")
        self.statusBar().addWidget(self.status_label, 1)
        self.balance_label = QLabel()
        self.balance_label.setProperty("role", "metric")
        self.statusBar().addPermanentWidget(self.balance_label)

        self.household.openPlan.connect(self._open_plan)
        self.household.managePlans.connect(self._manage_plans)
        state.statusMessage.connect(self._set_status)
        state.householdChanged.connect(self._update_balance)
        state.plansChanged.connect(self._refresh_plans)
        state.currentPlanChanged.connect(self._refresh_plans)

        self._refresh_plans()
        self._update_balance()
        self.tabs.setCurrentWidget(self.household if len(state.plans) > 1 else self.dashboard)
        if state.store.migrated_from == 1:
            self._set_status(
                f"Upgraded your data to support multiple loan types — a backup was saved to {backup_dir()}"
            )

    # ===================================================================== #
    # Plan bar
    # ===================================================================== #
    def _build_plan_bar(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background: {theme.SURFACE}; border-bottom: 1px solid {theme.BORDER}; }}"
            " QLabel { border: none; }"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(10)
        row.addWidget(theme.field("Plan"))
        self.plan_combo = QComboBox()
        self.plan_combo.setMinimumWidth(240)
        self.plan_combo.setToolTip("The Dashboard, Action Center, Sandbox, Visualizations and History tabs follow this plan.")
        self.plan_combo.currentIndexChanged.connect(self._plan_selected)
        row.addWidget(self.plan_combo)
        self.plan_summary = theme.status("")
        row.addWidget(self.plan_summary, 1)
        add_loan = QPushButton("Add loan…")
        add_loan.clicked.connect(self._add_loan)
        manage = QPushButton("Manage plans…")
        manage.clicked.connect(self._manage_plans)
        row.addWidget(add_loan)
        row.addWidget(manage)
        self.plan_bar = bar
        return bar

    def _refresh_plans(self) -> None:
        self.plan_combo.blockSignals(True)
        self.plan_combo.clear()
        for plan in self.state.plans:
            label = plan.name + ("" if plan.active else "  (inactive)")
            self.plan_combo.addItem(label, plan.plan_id)
        index = self.plan_combo.findData(self.state.current_plan_id)
        self.plan_combo.setCurrentIndex(max(index, 0))
        self.plan_combo.blockSignals(False)
        self._update_plan_summary()
        self._rebuild_plan_menu()

    def _update_plan_summary(self) -> None:
        plan = self.state.current_plan
        if plan is None:
            self.plan_summary.setText("No plans yet — import loans or add one.")
            return
        loans = self.state.loans
        schedule = self.state.schedule
        payoff = (
            f" · debt-free {schedule.payoff_date:%b %Y}"
            if schedule and schedule.completed and schedule.payoff_date else ""
        )
        self.plan_summary.setText(
            f"{len(loans)} loans · {money(self.state.total_balance)} · "
            f"{money(plan.monthly_budget)}/mo{payoff}"
        )

    def _plan_selected(self) -> None:
        plan_id = self.plan_combo.currentData()
        if plan_id is not None:
            self.state.set_current_plan(plan_id)

    def _open_plan(self, plan_id: int) -> None:
        self.state.set_current_plan(plan_id)
        self.tabs.setCurrentWidget(self.dashboard)

    def _tab_changed(self) -> None:
        # The household view spans every plan, so the plan picker would only confuse.
        self.plan_bar.setVisible(self.tabs.currentWidget() is not self.household)

    def _manage_plans(self) -> None:
        PlanManagerDialog(self, self.state).exec()

    def _add_loan(self) -> None:
        if not self.state.plans:
            plan_name, ok = QInputDialog.getText(self, "First plan", "Name your first plan:", text="My Loans")
            if not ok or not plan_name.strip():
                return
            self.state.add_plan(plan_name.strip())
        dialog = LoanDialog(self, self.state.plans, default_plan_id=self.state.current_plan_id)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.state.upsert_loan(dialog.result_loan())

    # ===================================================================== #
    # Menus
    # ===================================================================== #
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.setToolTipsVisible(True)
        self._action(
            file_menu, "&Import Loans…", self._import, QKeySequence.StandardKey.Open,
            "Load loans from a CSV / TSV / TXT file. You'll preview the rows and choose to "
            "merge with or replace your current data.",
        )
        self._action(
            file_menu, "Save Import &Template…", self._save_template, None,
            "Write a CSV containing every supported column with example student, mortgage, "
            "auto and credit-card rows — fill it in and import it.",
        )
        file_menu.addSeparator()
        export_menu = file_menu.addMenu("&Export")
        export_menu.setToolTipsVisible(True)
        self._action(export_menu, "&Loans…", self._export_loans, None,
                     "Every loan in every plan, in the import format (re-importable).")
        self._action(export_menu, "&Plan Schedule…", self._export_schedule, None,
                     "Month-by-month forecast for the selected plan.")
        self._action(export_menu, "&Household Schedule…", self._export_household, None,
                     "Combined forecast for all active plans, with rollover.")
        self._action(export_menu, "Payment &History…", self._export_payments, None,
                     "Every logged payment, one row per loan.")
        file_menu.addSeparator()
        self._action(file_menu, "&Back Up Data…", self._backup, None,
                     "Save everything — plans, loans, history, scenarios, pins, settings — to one file.")
        self._action(file_menu, "&Restore From Backup…", self._restore, None,
                     "Replace all current data with a backup file.")
        file_menu.addSeparator()
        self._action(file_menu, "Reset to Bundled &Data…", self._reset_sample, None,
                     "Discard everything and reload the starter dataset that ships with the app.")
        self._action(file_menu, "Clear Plan's Payment &History…", self._clear_history, None,
                     "Delete logged payments for the selected plan (balances stay as they are).")
        file_menu.addSeparator()
        self._action(file_menu, "E&xit", self.close, QKeySequence.StandardKey.Quit)

        self.plans_menu = self.menuBar().addMenu("&Plans")
        self.plans_menu.setToolTipsVisible(True)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.setToolTipsVisible(True)
        self._action(help_menu, "&Import && Export Guide", lambda: self._help("Import & Export"),
                     QKeySequence("F1"), "Supported files, every column, merge vs replace, exports and backups.")
        self._action(help_menu, "&Loan Types", lambda: self._help("Loan types"), None,
                     "How student, mortgage, auto, personal and credit-card loans are modelled.")
        self._action(help_menu, "&Plans, Household && Pins", lambda: self._help("Plans & Household"), None,
                     "Plans, rollover between plans, and sandbox pins.")
        help_menu.addSeparator()
        self._action(help_menu, "Where Is My &Data?", self._show_data_location)
        self._action(help_menu, "&About", self._about)

    def _rebuild_plan_menu(self) -> None:
        menu = self.plans_menu
        menu.clear()
        group = QActionGroup(self)
        for plan in self.state.plans:
            action = QAction(plan.name + ("" if plan.active else "  (inactive)"), self)
            action.setCheckable(True)
            action.setChecked(plan.plan_id == self.state.current_plan_id)
            action.triggered.connect(lambda _=False, pid=plan.plan_id: self.state.set_current_plan(pid))
            group.addAction(action)
            menu.addAction(action)
        menu.addSeparator()
        self._action(menu, "&New Plan…", self._new_plan, None, "Create an empty plan, e.g. 'Mortgage'.")
        self._action(menu, "&Manage Plans…", self._manage_plans, QKeySequence("Ctrl+P"),
                     "Rename, reorder, colour, budget, strategy, active and rollover settings.")
        menu.addSeparator()
        self._action(menu, "Reset &Baseline for This Plan", self._rebase, None,
                     "Treat today's projection as the reference that deviations are scored against.")
        self._action(menu, "Re&calculate", self.state.recalculate, QKeySequence("F5"))

    def _action(self, menu: QMenu, text: str, slot, shortcut=None, tip: str = "") -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # ===================================================================== #
    # File operations
    # ===================================================================== #
    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import loans", str(Path.home()), IMPORT_FILTER)
        if not path:
            return
        try:
            result = load_loans(path)
        except IngestError as exc:
            log.warning("Import failed for %s: %s", path, exc)
            box = QMessageBox(QMessageBox.Icon.Critical, "Import failed", str(exc), parent=self)
            guide = box.addButton("Open import guide", QMessageBox.ButtonRole.HelpRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() is guide:
                self._help("Import & Export")
            return

        dialog = ImportDialog(self, Path(path), result, self.state.plans)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        summary = self.state.apply_import(result, replace=dialog.replace_all)
        self.state.statusMessage.emit(f"Imported {Path(path).name}: {summary.describe()}")
        QMessageBox.information(self, "Import complete", summary.describe() + ".")

    def _save_path(self, title: str, name: str, file_filter: str = CSV_FILTER) -> Path | None:
        path, _ = QFileDialog.getSaveFileName(self, title, str(Path.home() / name), file_filter)
        return Path(path) if path else None

    def _save_template(self) -> None:
        path = self._save_path("Save import template", "loancalc_import_template.csv")
        if path:
            export.export_template(path)
            self._set_status(f"Template saved to {path.name} — fill it in, then File → Import Loans…")

    def _export_loans(self) -> None:
        path = self._save_path("Export loans", "loans.csv")
        if path:
            count = export.export_loans(path, self.state.all_loans, self.state.plans)
            self._set_status(f"Exported {count} loans to {path.name}")

    def _export_schedule(self) -> None:
        schedule, plan = self.state.schedule, self.state.current_plan
        if not schedule or not schedule.months or plan is None:
            QMessageBox.information(self, "Nothing to export", "The selected plan has no projection.")
            return
        safe = "".join(ch if ch.isalnum() else "_" for ch in plan.name).strip("_").lower()
        path = self._save_path("Export plan schedule", f"{safe}_schedule.csv")
        if path:
            count = export.export_schedule(path, schedule)
            self._set_status(f"Exported {count} months to {path.name}")

    def _export_household(self) -> None:
        household = self.state.household
        if not household or not household.months:
            QMessageBox.information(self, "Nothing to export", "No active plans carry debt.")
            return
        path = self._save_path("Export household schedule", "household_schedule.csv")
        if path:
            count = export.export_household(path, household)
            self._set_status(f"Exported {count} months to {path.name}")

    def _export_payments(self) -> None:
        payments = self.state.history(all_plans=True)
        if not payments:
            QMessageBox.information(self, "Nothing to export", "No payments have been logged yet.")
            return
        path = self._save_path("Export payment history", "payment_history.csv")
        if path:
            count = export.export_payments(path, payments, self.state.plans)
            self._set_status(f"Exported {count} rows to {path.name}")

    def _backup(self) -> None:
        path = self._save_path("Back up LoanCalc data", "loancalc_backup.db", BACKUP_FILTER)
        if path:
            self.state.backup_to(path)
            QMessageBox.information(self, "Backup saved", f"Everything was saved to:\n{path}")

    def _restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", str(Path.home()), BACKUP_FILTER)
        if not path:
            return
        confirm = QMessageBox.question(
            self, "Restore backup",
            "Replace ALL current plans, loans, history and scenarios with this backup?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.state.restore_from(Path(path))
        except StoreError as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))

    def _reset_sample(self) -> None:
        confirm = QMessageBox.question(
            self, "Reset data",
            "Restore the bundled starter dataset?\n\nAll current plans, loans, payment history "
            "and scenarios will be discarded.",
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
        plan = self.state.current_plan
        if plan is None:
            return
        confirm = QMessageBox.question(
            self, "Clear history",
            f"Delete every logged payment for '{plan.name}'? Loan balances stay as they are.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.clear_history()
            self._set_status(f"Payment history cleared for {plan.name}.")

    def _new_plan(self) -> None:
        name, ok = QInputDialog.getText(self, "New plan", "Plan name:", text="New Plan")
        if ok and name.strip():
            self.state.add_plan(name.strip())

    def _rebase(self) -> None:
        self.state.capture_baseline()
        self._set_status("Baseline reset to the current plan.")

    # ===================================================================== #
    # Help
    # ===================================================================== #
    def _help(self, page: str) -> None:
        HelpDialog(self, page).exec()

    def _show_data_location(self) -> None:
        QMessageBox.information(
            self, "Data location",
            f"Your plans, loans, payments and settings live in:\n\n{database_path()}\n\n"
            f"Automatic pre-upgrade backups:\n{backup_dir()}\n\n"
            "Use File → Back Up Data… to copy everything to another computer.",
        )

    def _about(self) -> None:
        QMessageBox.about(
            self, "About LoanCalc",
            f"<b>LoanCalc {__version__}</b><br/><br/>"
            "Debt payoff planning for student loans, mortgages, auto loans, personal loans "
            "and credit cards — per plan or as a whole household.<br/><br/>"
            f"<span style='color:{theme.TEXT_MUTED}'>Built with PySide6, pandas and pyqtgraph.</span>",
        )

    # ===================================================================== #
    # Status
    # ===================================================================== #
    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _update_balance(self) -> None:
        self._update_plan_summary()
        household = self.state.household
        payoff = (
            household.payoff_date.strftime("%b %Y")
            if household and household.completed and household.payoff_date else "—"
        )
        self.balance_label.setText(
            f"Household {money(self.state.household_balance)}   ·   Debt-free {payoff}"
        )
