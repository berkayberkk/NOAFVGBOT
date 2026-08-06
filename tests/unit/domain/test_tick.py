"""Unit tests for forex_daytrade.domain.tick."""

from datetime import UTC, datetime

import pytest

from forex_daytrade.domain.tick import Tick
from forex_daytrade.exceptions.data import InvalidTickError

_TS = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


def _make_tick(**overrides: object) -> Tick:
    defaults: dict[str, object] = {"bid": 1.1000, "ask": 1.1002, "timestamp": _TS}
    defaults.update(overrides)
    return Tick(**defaults)  # type: ignore[arg-type]


def test_construction_with_valid_values() -> None:
    tick = _make_tick()
    assert tick.bid == 1.1000
    assert tick.ask == 1.1002


def test_spread_property() -> None:
    tick = _make_tick(bid=1.1000, ask=1.1002)
    assert tick.spread == pytest.approx(0.0002)


def test_mid_property() -> None:
    tick = _make_tick(bid=1.1000, ask=1.1002)
    assert tick.mid == pytest.approx(1.1001)


def test_equality() -> None:
    assert _make_tick() == _make_tick()


def test_inequality() -> None:
    assert _make_tick() != _make_tick(bid=1.0999)


def test_is_frozen() -> None:
    tick = _make_tick()
    with pytest.raises(AttributeError):
        tick.bid = 1.0  # type: ignore[misc]


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(InvalidTickError, match="timezone-aware"):
        _make_tick(timestamp=datetime(2026, 1, 5, 10, 0))


def test_non_positive_bid_rejected() -> None:
    with pytest.raises(InvalidTickError, match="bid"):
        _make_tick(bid=0)


def test_non_positive_ask_rejected() -> None:
    with pytest.raises(InvalidTickError, match="ask"):
        _make_tick(ask=0)


def test_ask_below_bid_rejected() -> None:
    with pytest.raises(InvalidTickError, match="ask"):
        _make_tick(bid=1.1002, ask=1.1000)
