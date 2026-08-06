"""Unit tests for forex_daytrade.domain.symbol."""

import pytest

from forex_daytrade.domain.symbol import Symbol, TradeMode
from forex_daytrade.exceptions.data import InvalidSymbolError


def _make_symbol(**overrides: object) -> Symbol:
    defaults: dict[str, object] = {
        "name": "EURUSD",
        "digits": 5,
        "point_size": 0.00001,
        "contract_size": 100000.0,
        "tick_value": 1.0,
        "min_volume": 0.01,
        "max_volume": 100.0,
        "volume_step": 0.01,
    }
    defaults.update(overrides)
    return Symbol(**defaults)  # type: ignore[arg-type]


def test_construction_with_valid_values() -> None:
    symbol = _make_symbol()
    assert symbol.name == "EURUSD"
    assert symbol.trade_mode is TradeMode.UNKNOWN


def test_trade_mode_can_be_set_explicitly() -> None:
    symbol = _make_symbol(trade_mode=TradeMode.FULL)
    assert symbol.trade_mode is TradeMode.FULL


def test_equality_for_identical_symbols() -> None:
    assert _make_symbol() == _make_symbol()


def test_inequality_for_different_symbols() -> None:
    assert _make_symbol() != _make_symbol(name="GBPUSD")


def test_is_frozen() -> None:
    symbol = _make_symbol()
    with pytest.raises(AttributeError):
        symbol.name = "GBPUSD"  # type: ignore[misc]


def test_is_hashable() -> None:
    assert hash(_make_symbol()) == hash(_make_symbol())


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"digits": -1},
        {"point_size": 0},
        {"point_size": -0.1},
        {"contract_size": 0},
        {"tick_value": 0},
        {"min_volume": 0},
        {"max_volume": 0.005},
        {"volume_step": 0},
    ],
)
def test_invalid_values_raise(overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidSymbolError):
        _make_symbol(**overrides)


def test_trade_mode_enum_values() -> None:
    assert TradeMode.FULL.value == "full"
    assert TradeMode.DISABLED.value == "disabled"
    assert TradeMode.LONG_ONLY.value == "long_only"
    assert TradeMode.SHORT_ONLY.value == "short_only"
    assert TradeMode.CLOSE_ONLY.value == "close_only"
    assert TradeMode.UNKNOWN.value == "unknown"
