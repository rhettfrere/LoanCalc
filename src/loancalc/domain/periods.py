"""Calendar-month arithmetic. Every period is the first day of its month."""
from __future__ import annotations

import calendar
from datetime import date


def period_of(day: date) -> date:
    return day.replace(day=1)


def add_months(period: date, count: int) -> date:
    total = (period.year * 12 + period.month - 1) + count
    return date(total // 12, total % 12 + 1, 1)


def months_between(start: date, end: date) -> int:
    return (end.year * 12 + end.month) - (start.year * 12 + start.month)


def days_in_period(period: date) -> int:
    return calendar.monthrange(period.year, period.month)[1]


def month_end(period: date) -> date:
    return date(period.year, period.month, days_in_period(period))
