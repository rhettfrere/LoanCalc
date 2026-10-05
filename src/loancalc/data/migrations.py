"""Schema versions and forward-only migrations.

Each step is idempotent and runs inside one transaction. Before upgrading a
database that already holds data, a timestamped copy is written to the backups
folder so nothing is ever lost to a bad migration.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from loancalc.domain.loan_types import SPECS, LoanType, infer_type

SCHEMA_VERSION = 2

_V1 = """
CREATE TABLE IF NOT EXISTS loans (
    loan_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    principal       REAL    NOT NULL,
    accrued_interest REAL   NOT NULL DEFAULT 0,
    annual_rate     REAL    NOT NULL,
    minimum_payment REAL    NOT NULL,
    servicer        TEXT    NOT NULL DEFAULT '',
    sort_order      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments (
    payment_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    period          TEXT    NOT NULL,
    paid_on         TEXT    NOT NULL,
    total_amount    REAL    NOT NULL,
    interest_paid   REAL    NOT NULL,
    principal_paid  REAL    NOT NULL,
    note            TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS payment_allocations (
    allocation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id      INTEGER NOT NULL REFERENCES payments(payment_id) ON DELETE CASCADE,
    loan_id         INTEGER,
    loan_name       TEXT    NOT NULL,
    amount          REAL    NOT NULL,
    minimum_portion REAL    NOT NULL,
    extra_portion   REAL    NOT NULL,
    interest_portion REAL   NOT NULL,
    principal_portion REAL  NOT NULL,
    remaining_balance REAL  NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    monthly_budget  REAL    NOT NULL,
    strategy        TEXT    NOT NULL,
    created_on      TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_overrides (
    scenario_id     INTEGER NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    period          TEXT    NOT NULL,
    amount          REAL    NOT NULL,
    note            TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (scenario_id, period)
);
CREATE INDEX IF NOT EXISTS idx_alloc_payment ON payment_allocations(payment_id);
CREATE INDEX IF NOT EXISTS idx_payments_period ON payments(period);
"""

_V2_TABLES = """
CREATE TABLE IF NOT EXISTS plans (
    plan_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    monthly_budget   REAL    NOT NULL DEFAULT 0,
    strategy         TEXT    NOT NULL DEFAULT 'avalanche',
    active           INTEGER NOT NULL DEFAULT 1,
    rollover         INTEGER NOT NULL DEFAULT 1,
    accepts_rollover INTEGER NOT NULL DEFAULT 1,
    color            TEXT    NOT NULL DEFAULT '',
    sort_order       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scenario_pins (
    pin_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id  INTEGER NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    period       TEXT    NOT NULL,
    amount       REAL    NOT NULL DEFAULT 0,
    mode         TEXT    NOT NULL DEFAULT 'add',
    label        TEXT    NOT NULL DEFAULT '',
    repeat       TEXT    NOT NULL DEFAULT 'once',
    until        TEXT
);
CREATE INDEX IF NOT EXISTS idx_pins_scenario ON scenario_pins(scenario_id);
"""

_V2_COLUMNS = {
    "loans": [
        ("loan_type", "TEXT NOT NULL DEFAULT 'student'"),
        ("plan_id", "INTEGER"),
        ("interest_method", "TEXT"),
        ("term_months", "INTEGER NOT NULL DEFAULT 0"),
        ("escrow_monthly", "REAL NOT NULL DEFAULT 0"),
        ("pmi_monthly", "REAL NOT NULL DEFAULT 0"),
        ("asset_value", "REAL NOT NULL DEFAULT 0"),
        ("original_value", "REAL NOT NULL DEFAULT 0"),
        ("asset_growth", "REAL"),
        ("accrued_through", "TEXT"),
    ],
    "payments": [("plan_id", "INTEGER")],
    "scenarios": [("plan_id", "INTEGER")],
}


def current_version(conn: sqlite3.Connection) -> int:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "settings" not in tables:
        return 0
    row = conn.execute("SELECT value FROM settings WHERE key = 'schema_version'").fetchone()
    try:
        return int(row[0]) if row else 1
    except ValueError:
        return 1


def migrate(conn: sqlite3.Connection, db_path: Path | None = None, backup_dir: Path | None = None) -> int:
    """Bring `conn` up to SCHEMA_VERSION. Returns the version it started at."""
    start = current_version(conn)
    if start >= SCHEMA_VERSION:
        return start

    has_data = start > 0 and conn.execute("SELECT COUNT(*) FROM loans").fetchone()[0] > 0
    if has_data and backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = sqlite3.connect(backup_dir / f"loancalc-v{start}-{stamp}.db")
        with target:
            conn.backup(target)
        target.close()

    conn.executescript(_V1)
    if start < 2:
        _v1_to_v2(conn)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('schema_version', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return start


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add loan types, plans and first-class pins; fold v1 settings into a plan."""
    conn.executescript(_V2_TABLES)
    for table, columns in _V2_COLUMNS.items():
        existing = _columns(conn, table)
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_loans_plan ON loans(plan_id)")

    loans = conn.execute(
        "SELECT loan_id, name, minimum_payment FROM loans WHERE plan_id IS NULL"
    ).fetchall()
    if not loans:
        return

    legacy_budget = float(_setting(conn, "monthly_budget") or 0) or None
    legacy_strategy = _setting(conn, "strategy") or "avalanche"

    by_type: dict[LoanType, list[tuple[int, float]]] = defaultdict(list)
    for loan_id, name, minimum in loans:
        by_type[infer_type(name)].append((loan_id, minimum))

    # The v1 app was student-loan only, so its budget belongs to the biggest group.
    primary = max(by_type, key=lambda t: len(by_type[t]))
    plan_ids: dict[LoanType, int] = {}
    for order, (loan_type, members) in enumerate(sorted(by_type.items(), key=lambda kv: kv[0] != primary)):
        minimum_total = round(sum(m for _, m in members), 2)
        budget = legacy_budget if loan_type == primary and legacy_budget else minimum_total
        cursor = conn.execute(
            "INSERT INTO plans (name, monthly_budget, strategy, color, sort_order)"
            " VALUES (?, ?, ?, ?, ?)",
            (SPECS[loan_type].plan_name, budget,
             legacy_strategy if loan_type == primary else "avalanche",
             SPECS[loan_type].color, order),
        )
        plan_ids[loan_type] = int(cursor.lastrowid)
        conn.executemany(
            "UPDATE loans SET loan_type = ?, plan_id = ? WHERE loan_id = ?",
            [(loan_type.value, plan_ids[loan_type], loan_id) for loan_id, _ in members],
        )
    primary_plan = plan_ids[primary]

    accrued = _setting(conn, "last_accrued_period")
    if accrued:
        conn.execute("UPDATE loans SET accrued_through = ?", (accrued,))

    conn.execute(
        "UPDATE payments SET plan_id = COALESCE("
        " (SELECT l.plan_id FROM payment_allocations a JOIN loans l ON l.loan_id = a.loan_id"
        "  WHERE a.payment_id = payments.payment_id LIMIT 1), ?) WHERE plan_id IS NULL",
        (primary_plan,),
    )
    conn.execute("UPDATE scenarios SET plan_id = ? WHERE plan_id IS NULL", (primary_plan,))
    conn.execute(
        "INSERT INTO scenario_pins (scenario_id, period, amount, mode, label)"
        " SELECT scenario_id, period, amount, 'set', CASE WHEN note = '' THEN 'Pinned' ELSE note END"
        " FROM scenario_overrides"
    )

    baseline = _setting(conn, "baseline")
    if baseline:
        try:
            json.loads(baseline)
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"baseline:{primary_plan}", baseline),
            )
        except ValueError:
            pass
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('current_plan', ?)",
                 (str(primary_plan),))
