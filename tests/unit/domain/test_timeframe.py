"""Unit tests for forex_daytrade.domain.timeframe."""

from datetime import timedelta

import pytest

from forex_daytrade.domain.timeframe import Timeframe


@pytest.mark.parametrize(
    ("timeframe", "expected"),
    [
        (Timeframe.M1, timedelta(minutes=1)),
        (Timeframe.M5, timedelta(minutes=5)),
        (Timeframe.M15, timedelta(minutes=15)),
        (Timeframe.M30, timedelta(minutes=30)),
        (Timeframe.H1, timedelta(hours=1)),
        (Timeframe.H4, timedelta(hours=4)),
        (Timeframe.D1, timedelta(days=1)),
    ],
)
def test_timeframe_timedelta(timeframe: Timeframe, expected: timedelta) -> None:
    assert timeframe.timedelta == expected


def test_timeframe_minutes() -> None:
    assert Timeframe.M1.minutes == 1
    assert Timeframe.H1.minutes == 60
    assert Timeframe.H4.minutes == 240
    assert Timeframe.D1.minutes == 1440


def test_timeframe_values() -> None:
    assert Timeframe.M1.value == "M1"
    assert Timeframe.D1.value == "D1"


def test_timeframe_is_str_enum() -> None:
    assert Timeframe.M5 == "M5"
    assert isinstance(Timeframe.M5, str)


def test_timeframe_members_are_complete() -> None:
    assert {member.value for member in Timeframe} == {
        "M1",
        "M5",
        "M15",
        "M30",
        "H1",
        "H4",
        "D1",
    }


def test_timeframe_construction_from_string() -> None:
    assert Timeframe("H1") is Timeframe.H1


def test_timeframe_invalid_value_raises() -> None:
    with pytest.raises(ValueError, match="M2"):
        Timeframe("M2")
