"""Closed-form loan math shared by the engine, the loan editor and the charts."""
from __future__ import annotations

import math

#: PMI cancels automatically at 78% of the original value (Homeowners Protection Act).
PMI_AUTO_CANCEL_LTV = 0.78
#: Borrowers may request PMI removal once the balance reaches 80%.
PMI_REQUEST_LTV = 0.80


def scheduled_payment(principal: float, annual_rate: float, months: int) -> float:
    """Level principal-and-interest payment that retires `principal` in `months`."""
    if principal <= 0:
        return 0.0
    if months <= 0:
        return round(principal, 2)
    monthly = annual_rate / 12.0
    if monthly == 0:
        return round(principal / months, 2)
    return round(principal * monthly / (1 - (1 + monthly) ** -months), 2)


def remaining_term(principal: float, annual_rate: float, payment: float) -> int | None:
    """Months left at `payment`, or None if the payment never covers interest."""
    if principal <= 0:
        return 0
    if payment <= 0:
        return None
    monthly = annual_rate / 12.0
    if monthly == 0:
        return math.ceil(principal / payment)
    if payment <= principal * monthly:
        return None
    months = -math.log(1 - monthly * principal / payment) / math.log(1 + monthly)
    # Payments are rounded to cents, which can leave a sub-cent final month.
    return math.ceil(months - 0.01)


def asset_value_at(value: float, annual_growth: float, months: int) -> float:
    """Collateral value after `months` of compound appreciation/depreciation."""
    if value <= 0:
        return 0.0
    return value * (1 + annual_growth) ** (months / 12.0)


def loan_to_value(balance: float, value: float) -> float | None:
    if value <= 0:
        return None
    return balance / value


def pmi_applies(balance: float, original_value: float) -> bool:
    if original_value <= 0:
        return False
    return balance / original_value > PMI_AUTO_CANCEL_LTV


def pmi_balance_target(original_value: float, ltv: float = PMI_AUTO_CANCEL_LTV) -> float:
    """Principal you need to reach for PMI to fall away."""
    return round(original_value * ltv, 2)
