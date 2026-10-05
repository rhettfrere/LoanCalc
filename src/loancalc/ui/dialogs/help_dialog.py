"""In-app guides: import/export reference, loan types, plans & household."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from loancalc.data.ingest import COLUMN_ALIASES, EXPORT_HEADERS, REQUIRED
from loancalc.data.paths import backup_dir, database_path
from loancalc.domain.loan_types import INTEREST_METHOD_LABELS, SPECS
from loancalc.ui import theme

_CSS = f"""
<style>
body {{ font-family: 'Segoe UI'; font-size: 13px; color: {theme.TEXT}; }}
h2 {{ font-size: 17px; margin: 14px 0 6px 0; }}
h3 {{ font-size: 14px; margin: 14px 0 4px 0; color: {theme.ACCENT}; }}
table {{ border-collapse: collapse; margin: 6px 0; }}
th {{ text-align: left; background: {theme.HOVER}; padding: 5px 9px; font-size: 12px; }}
td {{ padding: 4px 9px; border-bottom: 1px solid {theme.BORDER}; vertical-align: top; font-size: 12px; }}
code {{ font-family: Consolas; background: {theme.HOVER}; }}
.muted {{ color: {theme.TEXT_MUTED}; }}
</style>
"""

_FIELD_NOTES = {
    "name": "Unique within a plan — used to match rows when merging.",
    "balance": "Current payoff amount. <code>$12,345.67</code>, <code>12345.67</code> all work.",
    "rate": "Annual rate: <code>5.5%</code>, <code>5.5</code> or <code>0.055</code>.",
    "minimum": "Monthly minimum (for mortgages: principal &amp; interest only, no escrow). "
               "Leave blank if you give a remaining term — it will be calculated.",
    "type": "Student, Mortgage, Auto, Personal, Credit Card, Other. Guessed from the name if missing.",
    "plan": "Which plan the loan joins. Defaults by type (e.g. <i>Mortgage</i>). New names create new plans.",
    "servicer": "Free text.",
    "term": "Months left on the contract. <code>5y</code> / <code>5 years</code> are converted.",
    "escrow": "Mortgage only. Taxes + insurance collected monthly. Shown, never reduces debt.",
    "pmi": "Mortgage only. Charged until the balance reaches 78% of the original value.",
    "asset_value": "Mortgage / auto. Today's home or vehicle value — powers the equity chart.",
    "original_value": "Mortgage. Purchase price or original appraisal — PMI is measured against this.",
    "growth": "Annual appreciation (<code>3%</code>) or depreciation (<code>-15%</code>). "
              "A header containing 'depreciation' makes the value negative.",
    "method": "Override interest accrual: <code>simple</code>, <code>monthly</code> or <code>compound</code>.",
}


def _import_export_html() -> str:
    rows = []
    for field, header in EXPORT_HEADERS.items():
        aliases = ", ".join(COLUMN_ALIASES[field][:6])
        required = "<b>Required</b>" if field in REQUIRED else "<span class='muted'>Optional</span>"
        rows.append(
            f"<tr><td><b>{header}</b></td><td>{required}</td>"
            f"<td>{_FIELD_NOTES.get(field, '')}<br/><span class='muted'>Also accepts: {aliases}</span></td></tr>"
        )
    return f"""{_CSS}
<h2>Importing loans</h2>
<p><b>File → Import Loans…</b> (Ctrl+O) accepts <code>.csv</code>, <code>.tsv</code> or
<code>.txt</code> — the delimiter (comma, tab, semicolon) is detected automatically. You will see a
preview of every row and choose how to apply it:</p>
<ul>
<li><b>Merge</b> (default) — new loans are added; a loan whose <i>name</i> already exists in the same
<i>plan</i> is updated in place. Ideal for refreshing balances from a new statement or adding a
mortgage to an existing student-loan setup.</li>
<li><b>Replace</b> — wipes every plan, loan, payment and scenario first. Use for a fresh start or
when loading someone else's data.</li>
</ul>
<p>Start from <b>File → Save Import Template…</b>: it contains every column below with example
student, mortgage, auto and credit-card rows. Headers are matched case-insensitively and ignore
spaces and punctuation, so most servicer exports work unedited.</p>
<h3>Columns</h3>
<table width="100%"><tr><th>Column</th><th></th><th>Notes</th></tr>{''.join(rows)}</table>

<h2>Exporting</h2>
<table width="100%">
<tr><th>File menu item</th><th>What you get</th></tr>
<tr><td><b>Export Loans…</b></td><td>Every loan in every plan, using the import headers above —
re-importable as-is and easy to share or edit in Excel.</td></tr>
<tr><td><b>Export Plan Schedule…</b></td><td>Month-by-month forecast for the plan you're viewing:
payment, interest, principal, PMI, escrow, balance and payoffs.</td></tr>
<tr><td><b>Export Household Schedule…</b></td><td>The combined forecast for all active plans,
with each plan's balance and the amount rolled over each month.</td></tr>
<tr><td><b>Export Payment History…</b></td><td>Every logged payment, one row per loan it touched.</td></tr>
<tr><td><b>Save Import Template…</b></td><td>A blank-ready CSV with every supported column.</td></tr>
</table>

<h2>Backups</h2>
<p><b>File → Back Up Data…</b> saves <i>everything</i> — plans, loans, payment history, sandbox
scenarios, pins, presets and settings — into one <code>.db</code> file.
<b>Restore From Backup…</b> replaces the current data with a backup. This is the best way to move
LoanCalc to another computer.</p>
<p class='muted'>Live data: <code>{database_path()}</code><br/>
Automatic pre-upgrade backups: <code>{backup_dir()}</code></p>
"""


def _loan_types_html() -> str:
    rows = "".join(
        f"<tr><td><b style='color:{spec.color}'>{spec.label}</b></td>"
        f"<td>{INTEREST_METHOD_LABELS[spec.interest_method]}</td>"
        f"<td>{'Yes' if spec.amortizing else '—'}</td>"
        f"<td>{spec.asset_label or '—'}"
        f"{f' ({spec.asset_growth * 100:+.0f}%/yr default)' if spec.secured else ''}</td>"
        f"<td>{spec.description}</td></tr>"
        for spec in SPECS.values()
    )
    return f"""{_CSS}
<h2>Loan types</h2>
<p>Each loan's type decides how its interest accrues and which extra details apply.</p>
<table width="100%"><tr><th>Type</th><th>Interest</th><th>Fixed term</th><th>Collateral</th>
<th>Notes</th></tr>{rows}</table>
<h3>Mortgages</h3>
<ul>
<li>The minimum is your <b>principal &amp; interest</b>. Leave it blank and give the remaining term to
have it calculated.</li>
<li><b>Escrow</b> is shown as part of your housing payment but never reduces the debt.</li>
<li><b>PMI</b> is charged until the balance reaches 78% of the original value (you can request
removal at 80%). Prepaying moves that date forward — the burn-down and equity charts mark it.</li>
<li>The <b>Equity</b> chart projects home value at the appreciation rate against your balance.</li>
</ul>
<h3>Auto loans</h3>
<ul>
<li>Simple daily interest, so paying early in the cycle helps.</li>
<li>Vehicles depreciate (default −15%/yr); the Equity chart shades months where you are
<b>underwater</b> (owe more than the car is worth).</li>
</ul>
"""


def _plans_html() -> str:
    return f"""{_CSS}
<h2>Plans</h2>
<p>A <b>plan</b> is a group of loans paid from one monthly budget with one strategy — for example
<i>Student Loans</i> at $5,000/mo avalanche, <i>Mortgage</i> at its P&amp;I, <i>Auto</i> at its
minimum. Pick the plan to view in the bar above the tabs; the Dashboard, Action Center, Sandbox,
Visualizations and History tabs all follow that selection.</p>
<p>Manage plans from <b>Plans → Manage Plans…</b>: rename, set budgets and strategies, choose colours,
reorder, and switch plans on or off.</p>
<h2>Household</h2>
<p>The <b>Household</b> tab runs every <b>active</b> plan together on one calendar and shows how they
affect each other:</p>
<ul>
<li><b>Rollover</b> — when a plan is paid off, its budget isn't lost; it moves to the plans still in
debt. Each plan can opt out of giving (<i>roll this plan's budget</i>) or receiving
(<i>accept rollover</i>).</li>
<li><b>Where freed money goes</b> — <i>Highest rate anywhere</i> (cheapest overall) or <i>Next plan in
priority order</i> (follow your own ordering).</li>
<li>The dashed line is the same household <b>without</b> rollover, so the gap is exactly what the
plans do for each other.</li>
</ul>
<h2>Sandbox pins</h2>
<p>Pins change a single month — or the same month every year — in a what-if scenario:</p>
<ul>
<li><b>Add</b> — extra on top of the base payment (tax refund, bonus).</li>
<li><b>Replace</b> — pay exactly this amount that month.</li>
<li><b>Minimums only</b> — a lean month.</li>
</ul>
<p>Add, edit, duplicate or delete pins from the pin list; build your own one-click presets with
<b>Manage presets…</b>.</p>
"""


class HelpDialog(QDialog):
    PAGES = ("Import & Export", "Loan types", "Plans & Household")

    def __init__(self, parent: QWidget, page: str = "Import & Export") -> None:
        super().__init__(parent)
        self.setWindowTitle("LoanCalc guide")
        self.resize(880, 680)

        tabs = QTabWidget()
        for title, builder in zip(self.PAGES, (_import_export_html, _loan_types_html, _plans_html), strict=True):
            browser = QTextBrowser()
            browser.setOpenExternalLinks(False)
            browser.setHtml(builder())
            browser.setStyleSheet(f"background: {theme.SURFACE}; border: none; padding: 8px;")
            tabs.addTab(browser, title)
        tabs.setCurrentIndex(self.PAGES.index(page) if page in self.PAGES else 0)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)
