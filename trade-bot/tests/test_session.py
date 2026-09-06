"""
Seans/Killzone Modülü Birim Testleri (Unit Tests for strategy/session.py).
"""

from strategy.session import in_killzone


def test_london_killzone_hours_true():
    assert in_killzone(7) is True
    assert in_killzone(9) is True


def test_ny_am_killzone_hours_true():
    assert in_killzone(12) is True
    assert in_killzone(14) is True


def test_ny_pm_killzone_hours_true():
    assert in_killzone(18) is True
    assert in_killzone(19) is True


def test_outside_killzone_hours_false():
    assert in_killzone(0) is False
    assert in_killzone(5) is False
    assert in_killzone(11) is False
    assert in_killzone(16) is False
    assert in_killzone(22) is False


def test_killzone_boundary_hours_exclusive():
    # range(7,10) -> 10 killzone DISINDA (ust sinir haric)
    assert in_killzone(10) is False
    assert in_killzone(15) is False
    assert in_killzone(20) is False
