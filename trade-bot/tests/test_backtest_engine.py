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

    candles_data[22] = (100.0, 111.0, 99.5, 110.5)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.won is True
    assert trade.exit_price == 110.0
    assert trade.r_multiple == (110.0 - 100.0) / (100.0 - 98.0)


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


def test_future_touch_does_not_contaminate_past_trade_tp():
    # Gelecek mumlardaki (idx 28) S/R dokunuşu idx 20'deki işlemin TP seçimini etkilememelidir.
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(35)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)  # S/R level at 110.0 created by idx 5 & 15

    signal = Signal(
        index=20,
        type=SignalType.BUY,
        confidence=Confidence.HIGH,
        setup_type=SetupType.A_PLUS,
        entry=100.0,
        stop_loss=98.0,
        reason="A+ test",
    )

    # idx 22: price hits TP 110.0
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)

    # idx 28: Gelecekteki 3. dokunuş (last_index=28 olurdu eğer tüm veriyle S/R hesaplansaydı)
    candles_data[28] = (100.0, 110.0, 99.0, 105.0)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    # Gelecekteki dokunuş yüzünden işlem atlanmamalı (skipped_no_tp = 0 olmalı)
    assert len(result.trades) == 1
    assert result.skipped_no_tp == 0
    assert result.trades[0].take_profit == 110.0
    assert result.trades[0].won is True
