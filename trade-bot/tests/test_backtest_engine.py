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
from strategy.config import StrategyConfig, DEFAULT_CONFIG
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


def test_zero_cost_backward_compatibility():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)
    candles = _make_dummy_candles(candles_data)

    res_default = run_backtest(candles, [signal])
    res_zero = run_backtest(candles, [signal], config=StrategyConfig(spread=0.0, slippage=0.0, commission=0.0))

    assert res_default.total_r == res_zero.total_r == 5.0
    assert res_default.trades[0].r_multiple == res_zero.trades[0].r_multiple == 5.0


def test_buy_spread_worsens_result():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.40)  # half_spread = 0.20
    res = run_backtest(candles, [signal], config=cfg)
    t = res.trades[0]
    # Exec entry = 100.20, Exec exit = 109.80, gross_pnl = 9.60, risk = 2.0 -> R = 4.80 < 5.0
    assert t.executed_entry == 100.20
    assert t.executed_exit == 109.80
    assert t.r_multiple == pytest.approx(4.80)


def test_sell_spread_worsens_result():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)  # Support at 90.0
    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=102.0, reason="A+")
    candles_data[22] = (100.0, 100.5, 89.0, 89.5)  # Hits TP 90.0
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.40)  # half_spread = 0.20
    res = run_backtest(candles, [signal], config=cfg)
    t = res.trades[0]
    # Exec entry = 99.80, Exec exit = 90.20, gross_pnl = 9.60, risk = 2.0 -> R = 4.80 < 5.0
    assert t.executed_entry == 99.80
    assert t.executed_exit == 90.20
    assert t.r_multiple == pytest.approx(4.80)


def test_buy_adverse_slippage():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(slippage=0.10)
    res = run_backtest(candles, [signal], config=cfg)
    t = res.trades[0]
    # Exec entry = 100.10, Exec exit = 109.90, gross_pnl = 9.80, risk = 2.0 -> R = 4.90 < 5.0
    assert t.executed_entry == 100.10
    assert t.executed_exit == 109.90
    assert t.r_multiple == pytest.approx(4.90)


def test_sell_adverse_slippage():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)
    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=102.0, reason="A+")
    candles_data[22] = (100.0, 100.5, 89.0, 89.5)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(slippage=0.10)
    res = run_backtest(candles, [signal], config=cfg)
    t = res.trades[0]
    # Exec entry = 99.90, Exec exit = 90.10, gross_pnl = 9.80, risk = 2.0 -> R = 4.90 < 5.0
    assert t.executed_entry == 99.90
    assert t.executed_exit == 90.10
    assert t.r_multiple == pytest.approx(4.90)


def test_commission_reduces_net_r():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(commission=0.20)  # $0.20 price units -> 0.10 R on risk=2.0
    res = run_backtest(candles, [signal], config=cfg)
    t = res.trades[0]
    assert t.gross_r_multiple == pytest.approx(5.0)
    assert t.net_r_multiple == pytest.approx(4.9)


def test_combined_execution_costs():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.20, slippage=0.05, commission=0.10)
    res = run_backtest(candles, [signal], config=cfg)
    t = res.trades[0]
    # Entry = 100.0 + 0.10 + 0.05 = 100.15
    # Exit = 110.0 - 0.10 - 0.05 = 109.85
    # Gross PnL = 9.70 -> Gross R = 4.85
    # Net PnL = 9.70 - 0.10 = 9.60 -> Net R = 4.80
    assert t.executed_entry == pytest.approx(100.15)
    assert t.executed_exit == pytest.approx(109.85)
    assert t.gross_r_multiple == pytest.approx(4.85)
    assert t.net_r_multiple == pytest.approx(4.80)


def test_same_bar_sl_tp_pessimistic_with_costs():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
    candles_data[22] = (100.0, 112.0, 96.0, 105.0)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.20, slippage=0.05, commission=0.10)
    res = run_backtest(candles, [signal], config=cfg)
    t = res.trades[0]
    assert t.won is False
    # Executed SL exit = 98.0 - 0.10 - 0.05 = 97.85
    # Executed entry = 100.15
    # Gross PnL = 97.85 - 100.15 = -2.30
    assert t.net_r_multiple == pytest.approx(-1.20)


def test_long_tp_not_triggered_when_mid_touches_but_bid_does_not():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)  # TP = 110.0
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    # MID high = 110.1 (>= 110.0), ama spread = 0.40 (half_spread = 0.20)
    # BID high = 110.1 - 0.20 = 109.9 (< 110.0 TP). TP tetiklenmemelidir!
    candles_data[22] = (100.0, 110.1, 99.5, 105.0)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.40)
    res = run_backtest(candles, [signal], config=cfg)
    assert len(res.trades) == 0  # Islem hic kapanmadi (TP tetiklenmedi)


def test_short_tp_not_triggered_when_mid_touches_but_ask_does_not():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)  # TP = 90.0
    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=102.0, reason="A+")

    # MID low = 89.9 (<= 90.0), ama spread = 0.40 (half_spread = 0.20)
    # ASK low = 89.9 + 0.20 = 90.1 (> 90.0 TP). TP tetiklenmemelidir!
    candles_data[22] = (100.0, 100.5, 89.9, 95.0)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.40)
    res = run_backtest(candles, [signal], config=cfg)
    assert len(res.trades) == 0  # Islem hic kapanmadi (TP tetiklenmedi)
