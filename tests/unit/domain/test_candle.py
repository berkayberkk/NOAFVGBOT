"""Unit tests for forex_daytrade.domain.candle."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from forex_daytrade.domain.candle import Candle
from forex_daytrade.exceptions.data import InvalidCandleError

_TS = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


def _make_candle(**overrides: object) -> Candle:
    defaults: dict[str, object] = {
        "timestamp": _TS,
        "open": 1.1000,
        "high": 1.1050,
        "low": 1.0950,
        "close": 1.1020,
        "volume": 100.0,
        "timezone": "UTC",
    }
    defaults.update(overrides)
    return Candle(**defaults)  # type: ignore[arg-type]


def test_construction_with_valid_values() -> None:
    candle = _make_candle()
    assert candle.open == 1.1000
    assert candle.spread is None


def test_equality() -> None:
    assert _make_candle() == _make_candle()


def test_inequality() -> None:
    assert _make_candle() != _make_candle(close=1.1049)


def test_is_frozen() -> None:
    candle = _make_candle()
    with pytest.raises(AttributeError):
        candle.close = 1.2  # type: ignore[misc]


def test_is_bullish() -> None:
    candle = _make_candle(open=1.1000, close=1.1020)
    assert candle.is_bullish
    assert not candle.is_bearish


def test_is_bearish() -> None:
    candle = _make_candle(open=1.1020, high=1.1050, low=1.0950, close=1.1000)
    assert candle.is_bearish
    assert not candle.is_bullish


def test_range() -> None:
    assert _make_candle(high=1.1050, low=1.0950).range == pytest.approx(0.01)


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(InvalidCandleError, match="timezone-aware"):
        _make_candle(timestamp=datetime(2026, 1, 5, 10, 0))


def test_timezone_mismatch_rejected() -> None:
    aware = datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Europe/London"))
    with pytest.raises(InvalidCandleError, match="does not match"):
        _make_candle(timestamp=aware, timezone="UTC")


def test_empty_timezone_rejected() -> None:
    with pytest.raises(InvalidCandleError, match="must not be empty"):
        _make_candle(timezone="")


def test_low_above_high_rejected() -> None:
    with pytest.raises(InvalidCandleError, match="low"):
        _make_candle(low=1.2, high=1.1)


def test_open_outside_range_rejected() -> None:
    with pytest.raises(InvalidCandleError, match="open"):
        _make_candle(open=1.2, high=1.1050, low=1.0950)


def test_close_outside_range_rejected() -> None:
    with pytest.raises(InvalidCandleError, match="close"):
        _make_candle(close=0.9, high=1.1050, low=1.0950)


def test_non_positive_price_rejected() -> None:
    with pytest.raises(InvalidCandleError, match="positive"):
        _make_candle(open=0, high=1.1050, low=1.0950, close=1.1000)


def test_negative_volume_rejected() -> None:
    with pytest.raises(InvalidCandleError, match="volume"):
        _make_candle(volume=-1)


def test_negative_spread_rejected() -> None:
    with pytest.raises(InvalidCandleError, match="spread"):
        _make_candle(spread=-1)


def test_valid_spread_accepted() -> None:
    assert _make_candle(spread=1.5).spread == 1.5
