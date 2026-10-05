from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loancalc.domain.loan_types import LoanType  # noqa: E402
from loancalc.domain.models import Loan  # noqa: E402

START = date(2026, 10, 1)


@pytest.fixture
def student_loans() -> list[Loan]:
    return [
        Loan("High", 10_000, 0.065, 120),
        Loan("Mid", 8_000, 0.05, 95),
        Loan("Low", 5_000, 0.03, 60),
    ]


@pytest.fixture
def mortgage() -> Loan:
    return Loan(
        "Home", 280_000, 0.065, 0, loan_type=LoanType.MORTGAGE, term_months=348,
        escrow_monthly=450, pmi_monthly=140, asset_value=360_000, original_value=350_000,
    )


@pytest.fixture
def auto_loan() -> Loan:
    return Loan("Car", 24_000, 0.069, 0, loan_type=LoanType.AUTO, term_months=60, asset_value=26_000)
