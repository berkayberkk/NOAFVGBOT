"""
Backtest Motoru Regresyon Testleri (Regression Tests for backtest/engine.py).
"""

from datetime import datetime, timedelta
import pytest

from backtest.engine import (
    run_backtest,
    _find_take_profit,
    Trade,
    BacktestResult,
)
from strategy.signal_engine import Signal, SignalType, Confidence, SetupType
from strategy.support_resistance import Level, LevelType


def _make_dummy_candles(ohlc_list: list[tuple[float, float, float, float]]) -> list[dict]:
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    candles = []
    for i, (o, h, l, c) in enumerate(ohlc_list):
        candles.append({
            "time": base_time + timedelta(minutes=30 * i),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "tick_volume": 100,
            "spread": 10,
        })
    return candles


def test_take_profit_hit():
    # 25 mumluk veri. S/R direnç seviyesi at price 110.0 (formed at idx 5 and 15)
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)   # resistance touch 1
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)  # resistance touch 2 -> Level created at last_index=15

    # BUY Signal at idx 20: entry=100.0, stop_loss=98.0
    signal = Signal(
        index=20,
        type=SignalType.BUY,
        confidence=Confidence.HIGH,
        setup_type=SetupType.A_PLUS,
        entry=100.0,
        stop_loss=98.0,
        reason="A+ test",
    )

    # idx 22: price hits TP (high = 111.0 >= 110.0)
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.won is True
    assert trade.exit_price == 110.0
    assert trade.r_multiple == (110.0 - 100.0) / (100.0 - 98.0)  # 10.0 / 2.0 = 5.0 R


def test_stop_loss_hit():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    signal = Signal(
        index=20,
        type=SignalType.BUY,
        confidence=Confidence.HIGH,
        setup_type=SetupType.A_PLUS,
        entry=100.0,
        stop_loss=98.0,
        reason="A+ test",
    )

    # idx 22: price hits SL (low = 97.0 <= 98.0)
    candles_data[22] = (100.0, 100.5, 97.0, 97.5)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.won is False
    assert trade.exit_price == 98.0
    assert trade.r_multiple == -1.0


def test_pessimistic_sl_first_priority_when_both_touched():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    signal = Signal(
        index=20,
        type=SignalType.BUY,
        confidence=Confidence.HIGH,
        setup_type=SetupType.A_PLUS,
        entry=100.0,
        stop_loss=98.0,
        reason="A+ test",
    )

    # idx 22: high=112.0 (>= TP 110.0) AND low=96.0 (<= SL 98.0) in the EXACT same bar!
    candles_data[22] = (100.0, 112.0, 96.0, 105.0)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.won is False
    assert trade.r_multiple == -1.0


def test_non_lookahead_sr_target_exit_selection():
    levels = [
        Level(price=110.0, type=LevelType.RESISTANCE, touch_count=2, first_index=5, last_index=25)
    ]

    tp = _find_take_profit(entry=100.0, direction=SignalType.BUY, levels=levels, signal_index=20)
    assert tp is None

    tp_valid = _find_take_profit(entry=100.0, direction=SignalType.BUY, levels=levels, signal_index=25)
    assert tp_valid == 110.0
