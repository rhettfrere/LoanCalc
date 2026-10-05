"""SQLite repository for plans, loans, payments, scenarios and settings.

All statements are parameterised. Schema creation and upgrades live in
`migrations.py`; this module only reads and writes the current shape.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

from loancalc.data.migrations import SCHEMA_VERSION, current_version, migrate
from loancalc.domain.loan_types import InterestMethod, LoanType
from loancalc.domain.models import (
    DEFAULT_PRESETS,
    Allocation,
    Baseline,
    Loan,
    PaymentRecord,
    Pin,
    PinMode,
    PinPreset,
    PinRepeat,
    Plan,
    Scenario,
)

_LOAN_COLUMNS = (
    "name", "principal", "accrued_interest", "annual_rate", "minimum_payment",
    "servicer", "sort_order", "loan_type", "plan_id", "interest_method",
    "term_months", "escrow_monthly", "pmi_monthly", "asset_value",
    "original_value", "asset_growth", "accrued_through",
)


class StoreError(RuntimeError):
    pass


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class Store:
    """Thin repository over the SQLite file. Safe to use from the GUI thread."""

    def __init__(self, path: Path, backup_dir: Path | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._backup_dir = backup_dir
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self.migrated_from = migrate(self._conn, self.path, backup_dir)

    def close(self) -> None:
        self._conn.close()

    # --- plans ------------------------------------------------------------- #
    def plans(self) -> list[Plan]:
        rows = self._conn.execute("SELECT * FROM plans ORDER BY sort_order, plan_id").fetchall()
        return [
            Plan(
                plan_id=row["plan_id"],
                name=row["name"],
                monthly_budget=row["monthly_budget"],
                strategy=row["strategy"],
                active=bool(row["active"]),
                rollover=bool(row["rollover"]),
                accepts_rollover=bool(row["accepts_rollover"]),
                color=row["color"],
                sort_order=row["sort_order"],
            )
            for row in rows
        ]

    def save_plan(self, plan: Plan) -> Plan:
        values = (
            plan.name, plan.monthly_budget, plan.strategy, int(plan.active),
            int(plan.rollover), int(plan.accepts_rollover), plan.color, plan.sort_order,
        )
        with self._conn:
            if plan.plan_id is None:
                cursor = self._conn.execute(
                    "INSERT INTO plans (name, monthly_budget, strategy, active, rollover,"
                    " accepts_rollover, color, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
                plan.plan_id = int(cursor.lastrowid or 0)
            else:
                self._conn.execute(
                    "UPDATE plans SET name = ?, monthly_budget = ?, strategy = ?, active = ?,"
                    " rollover = ?, accepts_rollover = ?, color = ?, sort_order = ?"
                    " WHERE plan_id = ?",
                    (*values, plan.plan_id),
                )
        return plan

    def delete_plan(self, plan_id: int) -> None:
        """Remove a plan with its loans, payments and scenarios."""
        with self._conn:
            self._conn.execute(
                "DELETE FROM payment_allocations WHERE payment_id IN"
                " (SELECT payment_id FROM payments WHERE plan_id = ?)", (plan_id,)
            )
            self._conn.execute("DELETE FROM payments WHERE plan_id = ?", (plan_id,))
            self._conn.execute(
                "DELETE FROM scenario_pins WHERE scenario_id IN"
                " (SELECT scenario_id FROM scenarios WHERE plan_id = ?)", (plan_id,)
            )
            self._conn.execute("DELETE FROM scenarios WHERE plan_id = ?", (plan_id,))
            self._conn.execute("DELETE FROM loans WHERE plan_id = ?", (plan_id,))
            self._conn.execute("DELETE FROM plans WHERE plan_id = ?", (plan_id,))
            self._conn.execute("DELETE FROM settings WHERE key = ?", (f"baseline:{plan_id}",))

    # --- loans ------------------------------------------------------------- #
    def is_empty(self) -> bool:
        return self._conn.execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 0

    def load_loans(self) -> list[Loan]:
        rows = self._conn.execute(
            "SELECT * FROM loans ORDER BY plan_id, sort_order, loan_id"
        ).fetchall()
        return [self._loan(row) for row in rows]

    @staticmethod
    def _loan(row: sqlite3.Row) -> Loan:
        return Loan(
            loan_id=row["loan_id"],
            name=row["name"],
            principal=row["principal"],
            accrued_interest=row["accrued_interest"],
            annual_rate=row["annual_rate"],
            minimum_payment=row["minimum_payment"],
            servicer=row["servicer"],
            sort_order=row["sort_order"],
            loan_type=LoanType(row["loan_type"]),
            plan_id=row["plan_id"],
            interest_method=InterestMethod(row["interest_method"]) if row["interest_method"] else None,
            term_months=row["term_months"],
            escrow_monthly=row["escrow_monthly"],
            pmi_monthly=row["pmi_monthly"],
            asset_value=row["asset_value"],
            original_value=row["original_value"],
            asset_growth=row["asset_growth"],
            accrued_through=_date(row["accrued_through"]),
        )

    @staticmethod
    def _loan_values(loan: Loan) -> tuple:
        return (
            loan.name, loan.principal, loan.accrued_interest, loan.annual_rate,
            loan.minimum_payment, loan.servicer, loan.sort_order, loan.loan_type.value,
            loan.plan_id, loan.interest_method.value if loan.interest_method else None,
            loan.term_months, loan.escrow_monthly, loan.pmi_monthly, loan.asset_value,
            loan.original_value, loan.asset_growth, _iso(loan.accrued_through),
        )

    def save_loans(self, loans: Iterable[Loan]) -> None:
        """Insert new loans and update existing ones."""
        insert = (
            f"INSERT INTO loans ({', '.join(_LOAN_COLUMNS)})"
            f" VALUES ({', '.join('?' * len(_LOAN_COLUMNS))})"
        )
        update = (
            f"UPDATE loans SET {', '.join(f'{c} = ?' for c in _LOAN_COLUMNS)} WHERE loan_id = ?"
        )
        with self._conn:
            for loan in loans:
                if loan.loan_id is None:
                    cursor = self._conn.execute(insert, self._loan_values(loan))
                    loan.loan_id = int(cursor.lastrowid or 0)
                else:
                    self._conn.execute(update, (*self._loan_values(loan), loan.loan_id))

    def delete_loan(self, loan_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM loans WHERE loan_id = ?", (loan_id,))

    def wipe(self) -> None:
        """Remove every plan, loan, payment and scenario (settings are kept)."""
        with self._conn:
            for table in ("payment_allocations", "payments", "scenario_pins",
                          "scenario_overrides", "scenarios", "loans", "plans"):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.execute("DELETE FROM settings WHERE key LIKE 'baseline:%'")

    # --- payments ---------------------------------------------------------- #
    def record_payment(self, record: PaymentRecord) -> PaymentRecord:
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO payments (period, paid_on, total_amount, interest_paid,"
                " principal_paid, note, plan_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.period.isoformat(), record.paid_on.isoformat(),
                    record.total_amount, record.interest_paid, record.principal_paid,
                    record.note, record.plan_id,
                ),
            )
            payment_id = int(cursor.lastrowid or 0)
            self._conn.executemany(
                "INSERT INTO payment_allocations (payment_id, loan_id, loan_name, amount,"
                " minimum_portion, extra_portion, interest_portion, principal_portion,"
                " remaining_balance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        payment_id, a.loan_id, a.loan_name, a.amount, a.minimum_portion,
                        a.extra_portion, a.interest_portion, a.principal_portion,
                        a.remaining_balance,
                    )
                    for a in record.allocations
                    if a.amount > 0
                ],
            )
        record.payment_id = payment_id
        return record

    def payments(self, plan_id: int | None = None) -> list[PaymentRecord]:
        sql = "SELECT * FROM payments"
        params: tuple = ()
        if plan_id is not None:
            sql += " WHERE plan_id = ?"
            params = (plan_id,)
        rows = self._conn.execute(sql + " ORDER BY period DESC, payment_id DESC", params).fetchall()
        records: list[PaymentRecord] = []
        for row in rows:
            allocations = self._conn.execute(
                "SELECT * FROM payment_allocations WHERE payment_id = ? ORDER BY amount DESC",
                (row["payment_id"],),
            ).fetchall()
            records.append(
                PaymentRecord(
                    payment_id=row["payment_id"],
                    plan_id=row["plan_id"],
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

    def paid_in_period(self, period: date, plan_id: int | None = None) -> float:
        sql = "SELECT COALESCE(SUM(total_amount), 0) FROM payments WHERE period = ?"
        params: tuple = (period.isoformat(),)
        if plan_id is not None:
            sql += " AND plan_id = ?"
            params += (plan_id,)
        return round(self._conn.execute(sql, params).fetchone()[0], 2)

    def payment_totals(self, plan_id: int | None = None) -> tuple[float, float, float]:
        sql = (
            "SELECT COALESCE(SUM(total_amount), 0), COALESCE(SUM(interest_paid), 0),"
            " COALESCE(SUM(principal_paid), 0) FROM payments"
        )
        params: tuple = ()
        if plan_id is not None:
            sql += " WHERE plan_id = ?"
            params = (plan_id,)
        paid, interest, principal = self._conn.execute(sql, params).fetchone()
        return paid, interest, principal

    def clear_payments(self, plan_id: int | None = None) -> None:
        with self._conn:
            if plan_id is None:
                self._conn.execute("DELETE FROM payment_allocations")
                self._conn.execute("DELETE FROM payments")
            else:
                self._conn.execute(
                    "DELETE FROM payment_allocations WHERE payment_id IN"
                    " (SELECT payment_id FROM payments WHERE plan_id = ?)", (plan_id,)
                )
                self._conn.execute("DELETE FROM payments WHERE plan_id = ?", (plan_id,))

    # --- scenarios --------------------------------------------------------- #
    def scenarios(self, plan_id: int | None = None) -> list[Scenario]:
        sql = "SELECT * FROM scenarios"
        params: tuple = ()
        if plan_id is not None:
            sql += " WHERE plan_id = ?"
            params = (plan_id,)
        rows = self._conn.execute(sql + " ORDER BY scenario_id", params).fetchall()
        return [
            Scenario(
                scenario_id=row["scenario_id"],
                plan_id=row["plan_id"],
                name=row["name"],
                monthly_budget=row["monthly_budget"],
                strategy=row["strategy"],
                created_on=date.fromisoformat(row["created_on"]),
                pins=self._pins(row["scenario_id"]),
            )
            for row in rows
        ]

    def _pins(self, scenario_id: int) -> list[Pin]:
        rows = self._conn.execute(
            "SELECT * FROM scenario_pins WHERE scenario_id = ? ORDER BY period, pin_id",
            (scenario_id,),
        ).fetchall()
        return [
            Pin(
                pin_id=row["pin_id"],
                period=date.fromisoformat(row["period"]),
                amount=row["amount"],
                mode=PinMode(row["mode"]),
                label=row["label"],
                repeat=PinRepeat(row["repeat"]),
                until=_date(row["until"]),
            )
            for row in rows
        ]

    def save_scenario(self, scenario: Scenario) -> Scenario:
        with self._conn:
            if scenario.scenario_id is None:
                cursor = self._conn.execute(
                    "INSERT INTO scenarios (name, monthly_budget, strategy, created_on, plan_id)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (scenario.name, scenario.monthly_budget, scenario.strategy,
                     scenario.created_on.isoformat(), scenario.plan_id),
                )
                scenario.scenario_id = int(cursor.lastrowid or 0)
            else:
                self._conn.execute(
                    "UPDATE scenarios SET name = ?, monthly_budget = ?, strategy = ?, plan_id = ?"
                    " WHERE scenario_id = ?",
                    (scenario.name, scenario.monthly_budget, scenario.strategy,
                     scenario.plan_id, scenario.scenario_id),
                )
            self._conn.execute(
                "DELETE FROM scenario_pins WHERE scenario_id = ?", (scenario.scenario_id,)
            )
            for pin in scenario.pins:
                cursor = self._conn.execute(
                    "INSERT INTO scenario_pins (scenario_id, period, amount, mode, label,"
                    " repeat, until) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (scenario.scenario_id, pin.period.isoformat(), pin.amount,
                     pin.mode.value, pin.label, pin.repeat.value, _iso(pin.until)),
                )
                pin.pin_id = int(cursor.lastrowid or 0)
        return scenario

    def delete_scenario(self, scenario_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM scenario_pins WHERE scenario_id = ?", (scenario_id,))
            self._conn.execute("DELETE FROM scenarios WHERE scenario_id = ?", (scenario_id,))

    # --- settings ---------------------------------------------------------- #
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_bool(self, key: str, default: bool) -> bool:
        raw = self.get_setting(key)
        return default if raw is None else raw == "1"

    def set_bool(self, key: str, value: bool) -> None:
        self.set_setting(key, "1" if value else "0")

    # --- pin presets ------------------------------------------------------- #
    def load_presets(self) -> list[PinPreset]:
        raw = self.get_setting("pin_presets")
        if not raw:
            return [PinPreset(p.label, p.mode, p.amount, p.repeat) for p in DEFAULT_PRESETS]
        try:
            return [
                PinPreset(
                    label=item["label"],
                    mode=PinMode(item.get("mode", "add")),
                    amount=float(item.get("amount", 0)),
                    repeat=PinRepeat(item.get("repeat", "once")),
                )
                for item in json.loads(raw)
            ]
        except (ValueError, KeyError, TypeError):
            return list(DEFAULT_PRESETS)

    def save_presets(self, presets: Sequence[PinPreset]) -> None:
        self.set_setting(
            "pin_presets",
            json.dumps(
                [
                    {"label": p.label, "mode": p.mode.value, "amount": p.amount,
                     "repeat": p.repeat.value}
                    for p in presets
                ]
            ),
        )

    # --- baselines --------------------------------------------------------- #
    def save_baseline(self, plan_id: int, baseline: Baseline) -> None:
        self.set_setting(
            f"baseline:{plan_id}",
            json.dumps(
                {
                    "captured_on": baseline.captured_on.isoformat(),
                    "monthly_budget": baseline.monthly_budget,
                    "strategy": baseline.strategy,
                    "total_interest": baseline.total_interest,
                    "payoff_date": _iso(baseline.payoff_date),
                    "starting_balance": baseline.starting_balance,
                }
            ),
        )

    def load_baseline(self, plan_id: int) -> Baseline | None:
        raw = self.get_setting(f"baseline:{plan_id}")
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return Baseline(
                captured_on=date.fromisoformat(payload["captured_on"]),
                monthly_budget=float(payload["monthly_budget"]),
                strategy=payload["strategy"],
                total_interest=float(payload["total_interest"]),
                payoff_date=_date(payload.get("payoff_date")),
                starting_balance=float(payload["starting_balance"]),
            )
        except (ValueError, KeyError, TypeError):
            return None

    # --- whole-database backup / restore ---------------------------------- #
    def backup_to(self, target: Path) -> None:
        destination = sqlite3.connect(Path(target))
        try:
            with destination:
                self._conn.backup(destination)
        finally:
            destination.close()

    def restore_from(self, source: Path) -> None:
        """Replace this database's contents with a LoanCalc backup file."""
        incoming = sqlite3.connect(f"file:{Path(source).as_posix()}?mode=ro", uri=True)
        try:
            tables = {
                row[0] for row in incoming.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"loans", "settings"} <= tables:
                raise StoreError("That file is not a LoanCalc backup.")
            if current_version(incoming) > SCHEMA_VERSION:
                raise StoreError("That backup was made by a newer version of LoanCalc.")
            incoming.backup(self._conn)
        except sqlite3.DatabaseError as exc:
            raise StoreError(f"Could not read the backup: {exc}") from exc
        finally:
            incoming.close()
        self._conn.row_factory = sqlite3.Row
        migrate(self._conn, self.path, self._backup_dir)
