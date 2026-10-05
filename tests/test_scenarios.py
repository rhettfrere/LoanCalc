from __future__ import annotations

from datetime import date

from loancalc.domain.models import Pin, PinMode, PinRepeat, Scenario


def _scenario(*pins: Pin) -> Scenario:
    return Scenario("Test", 3_000, pins=list(pins))


def test_unpinned_month_uses_base():
    assert _scenario().payment_for(date(2027, 1, 1)) == 3_000


def test_add_pin_stacks_on_base():
    s = _scenario(Pin(date(2027, 4, 1), 3_000, PinMode.ADD, "Refund"))
    assert s.payment_for(date(2027, 4, 1)) == 6_000


def test_set_pin_replaces_then_add_stacks():
    s = _scenario(
        Pin(date(2027, 4, 1), 1_500, PinMode.SET),
        Pin(date(2027, 4, 1), 500, PinMode.ADD),
    )
    assert s.payment_for(date(2027, 4, 1)) == 2_000


def test_minimum_pin_uses_supplied_minimum():
    s = _scenario(Pin(date(2026, 12, 1), mode=PinMode.MINIMUM))
    assert s.payment_for(date(2026, 12, 1), minimum=767.07) == 767.07


def test_yearly_pin_repeats_until():
    pin = Pin(date(2027, 4, 1), 3_000, PinMode.ADD, repeat=PinRepeat.YEARLY, until=date(2029, 4, 1))
    s = _scenario(pin)
    assert s.payment_for(date(2028, 4, 1)) == 6_000
    assert s.payment_for(date(2029, 4, 1)) == 6_000
    assert s.payment_for(date(2030, 4, 1)) == 3_000
    assert s.payment_for(date(2026, 4, 1)) == 3_000
    assert s.payment_for(date(2028, 5, 1)) == 3_000


def test_copy_is_independent():
    original = _scenario(Pin(date(2027, 4, 1), 100))
    clone = original.copy("Clone")
    clone.pins[0].amount = 999
    assert original.pins[0].amount == 100
    assert clone.pins[0].pin_id is None
