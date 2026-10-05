"""Display formatting helpers shared by every view."""
from __future__ import annotations

from datetime import date

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def money_compact(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def signed_money(value: float) -> str:
    return ("+" if value > 0 else "") + money(value)


def percent(value: float, places: int = 2) -> str:
    return f"{value * 100:.{places}f}%"


def month_label(period: date) -> str:
    return f"{_MONTHS[period.month - 1]} {period.year}"


def long_date(value: date | None) -> str:
    return value.strftime("%d %b %Y") if value else "—"


def duration(months: int) -> str:
    if months <= 0:
        return "—"
    years, remainder = divmod(months, 12)
    if years and remainder:
        return f"{years} yr {remainder} mo"
    if years:
        return f"{years} yr"
    return f"{remainder} mo"
