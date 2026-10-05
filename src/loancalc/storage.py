"""SQLite persistence for loans, payment history, and settings.

A single file under the user's local app data keeps balances, every logged
payment and its per-loan split, plus the original baseline plan used to score
deviations. All statements are parameterised.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

from loancalc.models import Allocation, Baseline, Loan, PaymentRecord, Scenario

SCHEMA_VERSION = 1

_SCHEMA = """
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


class Store:
    """Thin repository over the SQLite file. Safe to use from the GUI thread."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self.set_setting("schema_version", str(SCHEMA_VERSION))

    def close(self) -> None:
        self._conn.close()

    # --- loans ------------------------------------------------------------- #
    def is_empty(self) -> bool:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM loans").fetchone()
        return row["n"] == 0

    def load_loans(self) -> list[Loan]:
        rows = self._conn.execute(
            "SELECT * FROM loans ORDER BY sort_order, loan_id"
        ).fetchall()
        return [
            Loan(
                loan_id=row["loan_id"],
                name=row["name"],
                principal=row["principal"],
                accrued_interest=row["accrued_interest"],
                annual_rate=row["annual_rate"],
                minimum_payment=row["minimum_payment"],
                servicer=row["servicer"],
                sort_order=row["sort_order"],
            )
            for row in rows
        ]

    def replace_loans(self, loans: Sequence[Loan]) -> list[Loan]:
        """Swap in a brand new loan set (import / reset) and return it with ids."""
        with self._conn:
            self._conn.execute("DELETE FROM loans")
            for index, loan in enumerate(loans):
                cursor = self._conn.execute(
                    "INSERT INTO loans (name, principal, accrued_interest, annual_rate,"
                    " minimum_payment, servicer, sort_order)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        loan.name,
                        loan.principal,
                        loan.accrued_interest,
                        loan.annual_rate,
                        loan.minimum_payment,
                        loan.servicer,
                        index,
                    ),
                )
                loan.loan_id = int(cursor.lastrowid or 0)
                loan.sort_order = index
        return list(loans)

    def save_loans(self, loans: Iterable[Loan]) -> None:
        """Persist balances/terms for loans that already have ids."""
        with self._conn:
            for loan in loans:
                if loan.loan_id is None:
                    cursor = self._conn.execute(
                        "INSERT INTO loans (name, principal, accrued_interest, annual_rate,"
                        " minimum_payment, servicer, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            loan.name,
                            loan.principal,
                            loan.accrued_interest,
                            loan.annual_rate,
                            loan.minimum_payment,
                            loan.servicer,
                            loan.sort_order,
                        ),
                    )
                    loan.loan_id = int(cursor.lastrowid or 0)
                else:
                    self._conn.execute(
                        "UPDATE loans SET name = ?, principal = ?, accrued_interest = ?,"
                        " annual_rate = ?, minimum_payment = ?, servicer = ?, sort_order = ?"
                        " WHERE loan_id = ?",
                        (
                            loan.name,
                            loan.principal,
                            loan.accrued_interest,
                            loan.annual_rate,
                            loan.minimum_payment,
                            loan.servicer,
                            loan.sort_order,
                            loan.loan_id,
                        ),
                    )

    def delete_loan(self, loan_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM loans WHERE loan_id = ?", (loan_id,))

    # --- payments ---------------------------------------------------------- #
    def record_payment(self, record: PaymentRecord) -> PaymentRecord:
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO payments (period, paid_on, total_amount, interest_paid,"
                " principal_paid, note) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.period.isoformat(),
                    record.paid_on.isoformat(),
                    record.total_amount,
                    record.interest_paid,
                    record.principal_paid,
                    record.note,
                ),
            )
            payment_id = int(cursor.lastrowid or 0)
            self._conn.executemany(
                "INSERT INTO payment_allocations (payment_id, loan_id, loan_name, amount,"
                " minimum_portion, extra_portion, interest_portion, principal_portion,"
                " remaining_balance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        payment_id,
                        allocation.loan_id,
                        allocation.loan_name,
                        allocation.amount,
                        allocation.minimum_portion,
                        allocation.extra_portion,
                        allocation.interest_portion,
                        allocation.principal_portion,
                        allocation.remaining_balance,
                    )
                    for allocation in record.allocations
                    if allocation.amount > 0
                ],
            )
        record.payment_id = payment_id
        return record

    def payments(self) -> list[PaymentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM payments ORDER BY period DESC, payment_id DESC"
        ).fetchall()
        records: list[PaymentRecord] = []
        for row in rows:
            allocations = self._conn.execute(
                "SELECT * FROM payment_allocations WHERE payment_id = ? ORDER BY amount DESC",
                (row["payment_id"],),
            ).fetchall()
            records.append(
                PaymentRecord(
                    payment_id=row["payment_id"],
                    period=date.fromisoformat(row["period"]),
                    paid_on=date.fromisoformat(row["paid_on"]),
                    total_amount=row["total_amount"],
                    interest_paid=row["interest_paid"],
                    principal_paid=row["principal_paid"],
                    note=row["note"],
                    allocations=[
                        Allocation(
                            loan_id=a["loan_id"],
                            loan_name=a["loan_name"],
                            amount=a["amount"],
                            minimum_portion=a["minimum_portion"],
                            extra_portion=a["extra_portion"],
                            interest_portion=a["interest_portion"],
                            principal_portion=a["principal_portion"],
                            remaining_balance=a["remaining_balance"],
                        )
                        for a in allocations
                    ],
                )
            )
        return records

    def payment_totals(self) -> tuple[float, float, float]:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(total_amount), 0) AS paid,"
            " COALESCE(SUM(interest_paid), 0) AS interest,"
            " COALESCE(SUM(principal_paid), 0) AS principal FROM payments"
        ).fetchone()
        return row["paid"], row["interest"], row["principal"]

    def clear_payments(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM payment_allocations")
            self._conn.execute("DELETE FROM payments")

    # --- settings ---------------------------------------------------------- #
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_float(self, key: str, default: float) -> float:
        raw = self.get_setting(key)
        try:
            return float(raw) if raw is not None else default
        except ValueError:
            return default

    # --- scenarios --------------------------------------------------------- #
    def scenarios(self) -> list[Scenario]:
        rows = self._conn.execute(
            "SELECT * FROM scenarios ORDER BY scenario_id"
        ).fetchall()
        result: list[Scenario] = []
        for row in rows:
            pins = self._conn.execute(
                "SELECT period, amount, note FROM scenario_overrides"
                " WHERE scenario_id = ? ORDER BY period",
                (row["scenario_id"],),
            ).fetchall()
            result.append(
                Scenario(
                    scenario_id=row["scenario_id"],
                    name=row["name"],
                    monthly_budget=row["monthly_budget"],
                    strategy=row["strategy"],
                    created_on=date.fromisoformat(row["created_on"]),
                    overrides={
                        date.fromisoformat(pin["period"]): pin["amount"] for pin in pins
                    },
                    notes={
                        date.fromisoformat(pin["period"]): pin["note"]
                        for pin in pins
                        if pin["note"]
                    },
                )
            )
        return result

    def save_scenario(self, scenario: Scenario) -> Scenario:
        with self._conn:
            if scenario.scenario_id is None:
                cursor = self._conn.execute(
                    "INSERT INTO scenarios (name, monthly_budget, strategy, created_on)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        scenario.name,
                        scenario.monthly_budget,
                        scenario.strategy,
                        scenario.created_on.isoformat(),
                    ),
                )
                scenario.scenario_id = int(cursor.lastrowid or 0)
            else:
                self._conn.execute(
                    "UPDATE scenarios SET name = ?, monthly_budget = ?, strategy = ?"
                    " WHERE scenario_id = ?",
                    (
                        scenario.name,
                        scenario.monthly_budget,
                        scenario.strategy,
                        scenario.scenario_id,
                    ),
                )
            self._conn.execute(
                "DELETE FROM scenario_overrides WHERE scenario_id = ?",
                (scenario.scenario_id,),
            )
            self._conn.executemany(
                "INSERT INTO scenario_overrides (scenario_id, period, amount, note)"
                " VALUES (?, ?, ?, ?)",
                [
                    (
                        scenario.scenario_id,
                        period.isoformat(),
                        amount,
                        scenario.notes.get(period, ""),
                    )
                    for period, amount in sorted(scenario.overrides.items())
                ],
            )
        return scenario

    def delete_scenario(self, scenario_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM scenario_overrides WHERE scenario_id = ?", (scenario_id,)
            )
            self._conn.execute(
                "DELETE FROM scenarios WHERE scenario_id = ?", (scenario_id,)
            )

    # --- baseline ---------------------------------------------------------- #
    def save_baseline(self, baseline: Baseline) -> None:
        self.set_setting(
            "baseline",
            json.dumps(
                {
                    "captured_on": baseline.captured_on.isoformat(),
                    "monthly_budget": baseline.monthly_budget,
                    "strategy": baseline.strategy,
                    "total_interest": baseline.total_interest,
                    "payoff_date": baseline.payoff_date.isoformat()
                    if baseline.payoff_date
                    else None,
                    "starting_balance": baseline.starting_balance,
                }
            ),
        )

    def load_baseline(self) -> Baseline | None:
        raw = self.get_setting("baseline")
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return Baseline(
                captured_on=date.fromisoformat(payload["captured_on"]),
                monthly_budget=float(payload["monthly_budget"]),
                strategy=payload["strategy"],
                total_interest=float(payload["total_interest"]),
                payoff_date=date.fromisoformat(payload["payoff_date"])
                if payload.get("payoff_date")
                else None,
                starting_balance=float(payload["starting_balance"]),
            )
        except (ValueError, KeyError, TypeError):
            return None
