"""CSV exports. Every loan export uses the import headers, so it round-trips."""
from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from loancalc.data.ingest import EXPORT_HEADERS
from loancalc.domain.household import HouseholdSchedule
from loancalc.domain.loan_types import SPECS
from loancalc.domain.models import Loan, PaymentRecord, Plan, Schedule

_TEMPLATE_ROWS = [
    {
        "name": "MOHELA 1-03 Direct Loan - Unsubsidized", "type": "Student", "plan": "Student Loans",
        "servicer": "MOHELA", "balance": "$6,625.99", "rate": "5.50%", "minimum": "$77.65",
    },
    {
        "name": "Chase Home Mortgage", "type": "Mortgage", "plan": "Mortgage", "servicer": "Chase",
        "balance": "$285,000.00", "rate": "6.25%", "minimum": "", "term": "348",
        "escrow": "$425.00", "pmi": "$135.00", "asset_value": "$365,000",
        "original_value": "$350,000", "growth": "3%",
    },
    {
        "name": "Honda CR-V", "type": "Auto", "plan": "Auto Loans", "servicer": "Honda Financial",
        "balance": "$24,500.00", "rate": "6.9%", "minimum": "$485.00", "term": "54",
        "asset_value": "$27,000", "growth": "-15%",
    },
    {
        "name": "Visa Rewards", "type": "Credit Card", "plan": "Credit Cards",
        "balance": "$3,200.00", "rate": "24.99%", "minimum": "$95.00",
    },
]


def loans_frame(loans: Sequence[Loan], plans: Sequence[Plan]) -> pd.DataFrame:
    plan_names = {plan.plan_id: plan.name for plan in plans}
    rows = []
    for loan in loans:
        rows.append(
            {
                EXPORT_HEADERS["name"]: loan.name,
                EXPORT_HEADERS["type"]: SPECS[loan.loan_type].label,
                EXPORT_HEADERS["plan"]: plan_names.get(loan.plan_id, ""),
                EXPORT_HEADERS["servicer"]: loan.servicer,
                EXPORT_HEADERS["balance"]: f"{loan.payoff_amount:.2f}",
                EXPORT_HEADERS["rate"]: f"{loan.annual_rate * 100:.3f}%",
                EXPORT_HEADERS["minimum"]: f"{loan.minimum_payment:.2f}" if loan.minimum_payment else "",
                EXPORT_HEADERS["term"]: loan.term_months or "",
                EXPORT_HEADERS["escrow"]: f"{loan.escrow_monthly:.2f}" if loan.escrow_monthly else "",
                EXPORT_HEADERS["pmi"]: f"{loan.pmi_monthly:.2f}" if loan.pmi_monthly else "",
                EXPORT_HEADERS["asset_value"]: f"{loan.asset_value:.2f}" if loan.asset_value else "",
                EXPORT_HEADERS["original_value"]: f"{loan.original_value:.2f}" if loan.original_value else "",
                EXPORT_HEADERS["growth"]: "" if loan.asset_growth is None else f"{loan.asset_growth * 100:.2f}%",
                EXPORT_HEADERS["method"]: loan.interest_method.value if loan.interest_method else "",
            }
        )
    return pd.DataFrame(rows, columns=list(EXPORT_HEADERS.values()))


def export_loans(path: Path, loans: Sequence[Loan], plans: Sequence[Plan]) -> int:
    loans_frame(loans, plans).to_csv(path, index=False)
    return len(loans)


def export_template(path: Path) -> None:
    frame = pd.DataFrame(
        [{EXPORT_HEADERS[k]: row.get(k, "") for k in EXPORT_HEADERS} for row in _TEMPLATE_ROWS],
        columns=list(EXPORT_HEADERS.values()),
    )
    frame.to_csv(path, index=False)


def export_schedule(path: Path, schedule: Schedule) -> int:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["Month", "Starting balance", "Interest charged", "Payment", "To interest",
             "To principal", "PMI", "Escrow", "Ending balance", "Loans paid off"]
        )
        for month in schedule.months:
            writer.writerow(
                [
                    month.period.isoformat(), f"{month.starting_balance:.2f}",
                    f"{month.interest_charged:.2f}", f"{month.total_paid:.2f}",
                    f"{month.interest_paid:.2f}", f"{month.principal_paid:.2f}",
                    f"{month.fees_paid:.2f}", f"{month.escrow_paid:.2f}",
                    f"{month.ending_balance:.2f}", "; ".join(month.loans_closed),
                ]
            )
    return len(schedule.months)


def export_household(path: Path, household: HouseholdSchedule) -> int:
    outcomes = list(household.outcomes.items())
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["Month", "Total balance", "Payment", "To interest", "To principal", "PMI",
             "Rolled over"]
            + [f"{o.plan.name} balance" for _, o in outcomes]
            + ["Plans paid off"]
        )
        for month in household.months:
            writer.writerow(
                [
                    month.period.isoformat(), f"{month.ending_balance:.2f}",
                    f"{month.total_paid:.2f}", f"{month.interest_paid:.2f}",
                    f"{month.principal_paid:.2f}", f"{month.fees_paid:.2f}",
                    f"{month.rolled:.2f}",
                ]
                + [f"{month.plan_balances.get(key, 0.0):.2f}" for key, _ in outcomes]
                + ["; ".join(month.plans_completed)]
            )
    return len(household.months)


def export_payments(path: Path, payments: Sequence[PaymentRecord], plans: Sequence[Plan]) -> int:
    plan_names = {plan.plan_id: plan.name for plan in plans}
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["Month", "Logged on", "Plan", "Loan", "Applied", "Minimum portion", "Extra portion",
             "To interest", "To principal", "Balance after", "Note"]
        )
        rows = 0
        for record in payments:
            for allocation in record.allocations:
                writer.writerow(
                    [
                        record.period.isoformat(), record.paid_on.isoformat(),
                        plan_names.get(record.plan_id, ""), allocation.loan_name,
                        f"{allocation.amount:.2f}", f"{allocation.minimum_portion:.2f}",
                        f"{allocation.extra_portion:.2f}", f"{allocation.interest_portion:.2f}",
                        f"{allocation.principal_portion:.2f}",
                        f"{allocation.remaining_balance:.2f}", record.note,
                    ]
                )
                rows += 1
    return rows
