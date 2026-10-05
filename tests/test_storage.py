from __future__ import annotations

import sqlite3
from datetime import date

from loancalc.data.migrations import _V1, SCHEMA_VERSION
from loancalc.data.storage import Store
from loancalc.domain.loan_types import LoanType
from loancalc.domain.models import Loan, Pin, PinMode, PinRepeat, Plan, Scenario


def _make_v1(path):
    conn = sqlite3.connect(path)
    conn.executescript(_V1)
    conn.executemany(
        "INSERT INTO loans (name, principal, annual_rate, minimum_payment) VALUES (?, ?, ?, ?)",
        [("MOHELA 1-01 Direct Loan", 1000, 0.05, 20), ("Chase Mortgage", 200000, 0.06, 1300)],
    )
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        [("schema_version", "1"), ("monthly_budget", "5000"), ("strategy", "snowball"),
         ("last_accrued_period", "2026-09-01"),
         ("baseline", '{"captured_on": "2026-09-01", "monthly_budget": 5000, "strategy": "snowball",'
                      ' "total_interest": 10, "payoff_date": null, "starting_balance": 1000}')],
    )
    conn.execute(
        "INSERT INTO scenarios (name, monthly_budget, strategy, created_on) VALUES ('Old', 2000, 'avalanche', '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO scenario_overrides (scenario_id, period, amount, note) VALUES (1, '2027-04-01', 5000, 'Tax refund')"
    )
    conn.commit()
    conn.close()


def test_v1_migration_preserves_everything(tmp_path):
    db = tmp_path / "v1.db"
    _make_v1(db)
    store = Store(db, backup_dir=tmp_path / "backups")
    assert store.migrated_from == 1
    assert len(list((tmp_path / "backups").iterdir())) == 1

    plans = {plan.name: plan for plan in store.plans()}
    assert set(plans) == {"Student Loans", "Mortgage"}
    loans = {loan.name: loan for loan in store.load_loans()}
    assert loans["Chase Mortgage"].loan_type is LoanType.MORTGAGE
    assert loans["Chase Mortgage"].plan_id == plans["Mortgage"].plan_id
    assert all(loan.accrued_through == date(2026, 9, 1) for loan in loans.values())

    primary = next(p for p in plans.values() if p.monthly_budget == 5000)
    assert primary.strategy == "snowball"
    assert store.load_baseline(primary.plan_id) is not None

    scenario = store.scenarios()[0]
    assert scenario.plan_id == primary.plan_id
    assert scenario.pins[0].mode is PinMode.SET and scenario.pins[0].label == "Tax refund"
    assert store.get_setting("schema_version") == str(SCHEMA_VERSION)
    store.close()

    reopened = Store(db, backup_dir=tmp_path / "backups")
    assert reopened.migrated_from == SCHEMA_VERSION
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_round_trip_plans_loans_scenarios(tmp_path):
    store = Store(tmp_path / "fresh.db")
    plan = store.save_plan(Plan("Mortgage", 2000, rollover=False))
    loan = Loan("Home", 1000, 0.05, 0, loan_type=LoanType.MORTGAGE, plan_id=plan.plan_id,
                term_months=120, escrow_monthly=300, pmi_monthly=50, asset_value=2000,
                original_value=1900, asset_growth=0.02, accrued_through=date(2026, 10, 1))
    store.save_loans([loan])
    assert store.load_loans()[0] == loan

    scenario = Scenario("Plan", 2500, plan_id=plan.plan_id, pins=[
        Pin(date(2027, 4, 1), 3000, PinMode.ADD, "Refund", PinRepeat.YEARLY, date(2030, 4, 1)),
    ])
    store.save_scenario(scenario)
    loaded = store.scenarios(plan.plan_id)[0]
    assert loaded.pins[0].repeat is PinRepeat.YEARLY and loaded.pins[0].until == date(2030, 4, 1)
    assert store.plans()[0].rollover is False


def test_backup_and_restore(tmp_path):
    store = Store(tmp_path / "a.db")
    plan = store.save_plan(Plan("P", 100))
    store.save_loans([Loan("L", 10, 0.05, 5, plan_id=plan.plan_id)])
    store.backup_to(tmp_path / "backup.db")
    store.wipe()
    assert store.is_empty()
    store.restore_from(tmp_path / "backup.db")
    assert [loan.name for loan in store.load_loans()] == ["L"]
