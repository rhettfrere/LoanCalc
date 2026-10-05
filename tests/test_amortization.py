from __future__ import annotations

import pytest

from loancalc.domain import amortization as am


def test_textbook_mortgage_payment():
    assert am.scheduled_payment(300_000, 0.065, 360) == pytest.approx(1896.20, abs=0.01)


def test_zero_rate_payment_is_straight_line():
    assert am.scheduled_payment(12_000, 0.0, 12) == 1000.0


@pytest.mark.parametrize("principal, rate, months", [(300_000, 0.065, 360), (24_000, 0.069, 60), (5_000, 0.0, 10)])
def test_remaining_term_inverts_payment(principal, rate, months):
    payment = am.scheduled_payment(principal, rate, months)
    assert am.remaining_term(principal, rate, payment) == months


def test_payment_below_interest_never_amortises():
    assert am.remaining_term(100_000, 0.12, 900) is None


def test_pmi_threshold():
    assert am.pmi_applies(280_000, 350_000)  # 80%
    assert not am.pmi_applies(272_000, 350_000)  # under 78%
    assert am.pmi_balance_target(350_000) == 273_000.0


def test_asset_growth_compounds():
    assert am.asset_value_at(100_000, 0.03, 12) == pytest.approx(103_000)
    assert am.asset_value_at(20_000, -0.15, 24) == pytest.approx(20_000 * 0.85**2)
