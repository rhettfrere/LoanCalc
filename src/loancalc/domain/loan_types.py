"""Loan type registry.

Each type carries the behaviour that differs between products: how interest
accrues, whether there is collateral, whether it amortises over a fixed term,
and which plan it lands in by default. Adding a new product is one entry here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class LoanType(StrEnum):
    STUDENT = "student"
    MORTGAGE = "mortgage"
    AUTO = "auto"
    PERSONAL = "personal"
    CREDIT_CARD = "credit_card"
    OTHER = "other"


class InterestMethod(StrEnum):
    #: principal x rate x days / 365 — federal student loans, most auto loans.
    SIMPLE_DAILY = "simple_daily"
    #: principal x rate / 12 — standard amortised mortgages and personal loans.
    MONTHLY = "monthly"
    #: balance compounds daily at rate / 365 — revolving credit.
    DAILY_COMPOUND = "daily_compound"


INTEREST_METHOD_LABELS = {
    InterestMethod.SIMPLE_DAILY: "Simple daily (rate × days ÷ 365)",
    InterestMethod.MONTHLY: "Monthly amortised (rate ÷ 12)",
    InterestMethod.DAILY_COMPOUND: "Daily compounding (credit card)",
}


@dataclass(frozen=True, slots=True)
class LoanTypeSpec:
    key: LoanType
    label: str
    plan_name: str
    interest_method: InterestMethod
    color: str
    secured: bool = False
    amortizing: bool = False
    has_escrow: bool = False
    asset_label: str = ""
    asset_growth: float = 0.0
    keywords: tuple[str, ...] = ()
    description: str = ""


SPECS: dict[LoanType, LoanTypeSpec] = {
    LoanType.STUDENT: LoanTypeSpec(
        key=LoanType.STUDENT,
        label="Student loan",
        plan_name="Student Loans",
        interest_method=InterestMethod.SIMPLE_DAILY,
        color="#367C2B",
        keywords=("student", "mohela", "nelnet", "navient", "sallie", "direct loan",
                  "parent plus", "plus loan", "subsidized", "unsubsidized", "aidvantage",
                  "edfinancial", "fedloan", "perkins"),
        description="Simple daily interest; no collateral.",
    ),
    LoanType.MORTGAGE: LoanTypeSpec(
        key=LoanType.MORTGAGE,
        label="Mortgage",
        plan_name="Mortgage",
        interest_method=InterestMethod.MONTHLY,
        color="#1F6FB2",
        secured=True,
        amortizing=True,
        has_escrow=True,
        asset_label="Home value",
        asset_growth=0.03,
        keywords=("mortgage", "home loan", "heloc", "house", "escrow", "refi"),
        description="Monthly amortised P&I, escrow and PMI tracked separately.",
    ),
    LoanType.AUTO: LoanTypeSpec(
        key=LoanType.AUTO,
        label="Auto loan",
        plan_name="Auto Loans",
        interest_method=InterestMethod.SIMPLE_DAILY,
        color="#B0450B",
        secured=True,
        amortizing=True,
        asset_label="Vehicle value",
        asset_growth=-0.15,
        keywords=("auto", "car", "vehicle", "truck", "motorcycle", "rv ", "boat"),
        description="Simple daily interest; vehicle depreciation tracked for equity.",
    ),
    LoanType.PERSONAL: LoanTypeSpec(
        key=LoanType.PERSONAL,
        label="Personal loan",
        plan_name="Personal Loans",
        interest_method=InterestMethod.MONTHLY,
        color="#7D5BA6",
        amortizing=True,
        keywords=("personal", "installment", "sofi", "lending club", "upstart", "medical"),
        description="Fixed-term installment loan.",
    ),
    LoanType.CREDIT_CARD: LoanTypeSpec(
        key=LoanType.CREDIT_CARD,
        label="Credit card",
        plan_name="Credit Cards",
        interest_method=InterestMethod.DAILY_COMPOUND,
        color="#A32020",
        keywords=("credit card", "card", "visa", "mastercard", "amex", "discover"),
        description="Revolving balance compounding daily.",
    ),
    LoanType.OTHER: LoanTypeSpec(
        key=LoanType.OTHER,
        label="Other debt",
        plan_name="Other Debt",
        interest_method=InterestMethod.MONTHLY,
        color="#4C6D8C",
        description="Anything else with a balance and a rate.",
    ),
}

_ALIASES = {
    "student": LoanType.STUDENT,
    "studentloan": LoanType.STUDENT,
    "education": LoanType.STUDENT,
    "mortgage": LoanType.MORTGAGE,
    "home": LoanType.MORTGAGE,
    "homeloan": LoanType.MORTGAGE,
    "house": LoanType.MORTGAGE,
    "heloc": LoanType.MORTGAGE,
    "auto": LoanType.AUTO,
    "autoloan": LoanType.AUTO,
    "car": LoanType.AUTO,
    "vehicle": LoanType.AUTO,
    "personal": LoanType.PERSONAL,
    "personalloan": LoanType.PERSONAL,
    "installment": LoanType.PERSONAL,
    "creditcard": LoanType.CREDIT_CARD,
    "card": LoanType.CREDIT_CARD,
    "cc": LoanType.CREDIT_CARD,
    "other": LoanType.OTHER,
}


def spec(loan_type: LoanType | str) -> LoanTypeSpec:
    return SPECS[LoanType(loan_type)]


def parse_type(value: str) -> LoanType | None:
    """Map free text like 'Auto Loan' or 'credit_card' to a LoanType."""
    key = re.sub(r"[^a-z]", "", value.lower())
    if not key:
        return None
    if key in _ALIASES:
        return _ALIASES[key]
    for loan_type in LoanType:
        if key == loan_type.value.replace("_", ""):
            return loan_type
    return None


def infer_type(name: str) -> LoanType:
    """Best guess from a loan's name when the file has no type column."""
    text = name.lower()
    for loan_type in (
        LoanType.MORTGAGE,
        LoanType.AUTO,
        LoanType.CREDIT_CARD,
        LoanType.STUDENT,
        LoanType.PERSONAL,
    ):
        for keyword in SPECS[loan_type].keywords:
            if re.search(rf"\b{re.escape(keyword.strip())}\b", text):
                return loan_type
    return LoanType.OTHER
