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

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
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

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
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

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    # idx 21: limit dolum
    candles_data[21] = (100.0, 100.5, 99.5, 100.0)
    # idx 22: high=112.0 (>= TP 110.0) AND low=96.0 (<= SL 98.0)
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
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(35)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    candles_data[22] = (100.0, 111.0, 99.5, 110.5)
    candles_data[28] = (100.0, 110.0, 99.0, 105.0)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    assert result.skipped_no_tp == 0
    assert result.trades[0].take_profit == 110.0
    assert result.trades[0].won is True


# --- Phase 3A: Execution Cost Tests ---

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
    # Exec entry = 100.0, Exec exit = 109.80, gross_pnl = 9.80, risk = 2.0 -> R = 4.90 < 5.0
    assert t.executed_entry == 100.0
    assert t.executed_exit == 109.80
    assert t.r_multiple == pytest.approx(4.90)


def test_sell_spread_worsens_result():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)
    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=102.0, reason="A+")
    candles_data[22] = (100.0, 100.5, 89.0, 89.5)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.40)  # half_spread = 0.20
    res = run_backtest(candles, [signal], config=cfg)
    t = res.trades[0]
    # Exec entry = 100.0, Exec exit = 90.20, gross_pnl = 9.80, risk = 2.0 -> R = 4.90 < 5.0
    assert t.executed_entry == 100.0
    assert t.executed_exit == 90.20
    assert t.r_multiple == pytest.approx(4.90)


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
    # Market-emri: exec entry = 100.0 + 0.10 = 100.10 (limit'ten kotu, EA'nin
    # gercek davranisiyla uyumlu), exec exit = 109.90, gross_pnl = 9.80,
    # risk = 2.0 -> R = 4.90 < 5.0
    assert t.executed_entry == pytest.approx(100.10)
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
    # Market-emri: exec entry = 100.0 - 0.10 = 99.90 (limit'ten kotu), exec
    # exit = 90.10, gross_pnl = 9.80, risk = 2.0 -> R = 4.90 < 5.0
    assert t.executed_entry == pytest.approx(99.90)
    assert t.executed_exit == 90.10
    assert t.r_multiple == pytest.approx(4.90)


def test_commission_reduces_net_r():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(commission=0.20)
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
    # Market-emri: exec entry = 100.0 + half_spread(0.10) + slippage(0.05) = 100.05
    # Exec exit = 110.0 - 0.10 - 0.05 = 109.85
    # Gross PnL = 9.80 -> Gross R = 4.90
    # Net PnL = 9.80 - 0.10 = 9.70 -> Net R = 4.85
    assert t.executed_entry == pytest.approx(100.05)
    assert t.executed_exit == pytest.approx(109.85)
    assert t.gross_r_multiple == pytest.approx(4.90)
    assert t.net_r_multiple == pytest.approx(4.85)


def test_same_bar_sl_tp_pessimistic_with_costs():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")
    candles_data[21] = (100.0, 100.5, 99.5, 100.0)  # Fill at idx 21
    candles_data[22] = (100.0, 112.0, 96.0, 105.0)  # Same-bar SL/TP at idx 22
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.20, slippage=0.05, commission=0.10)
    res = run_backtest(candles, [signal], config=cfg)
    t = res.trades[0]
    assert t.won is False
    # Executed SL exit = 98.0 - 0.10 - 0.05 = 97.85
    # Market-emri: executed entry = 100.0 + half_spread(0.10) + slippage(0.05) = 100.05
    # Gross PnL = 97.85 - 100.05 = -2.20
    # Net PnL = -2.20 - 0.10 = -2.30 -> Net R = -1.15
    assert t.net_r_multiple == pytest.approx(-1.15)


def test_long_tp_not_triggered_when_mid_touches_but_bid_does_not():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    candles_data[21] = (100.0, 100.5, 99.5, 100.0)  # Fill at idx 21
    candles_data[22] = (100.0, 110.1, 99.5, 105.0)  # MID high = 110.1, BID high = 109.9 < 110.0
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.40)
    res = run_backtest(candles, [signal], config=cfg)
    assert len(res.trades) == 0


def test_short_tp_not_triggered_when_mid_touches_but_ask_does_not():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)
    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=102.0, reason="A+")

    candles_data[21] = (100.0, 100.5, 99.5, 100.0)  # Fill at idx 21
    candles_data[22] = (100.0, 100.5, 89.9, 95.0)  # MID low = 89.9, ASK low = 90.1 > 90.0
    candles = _make_dummy_candles(candles_data)

    cfg = StrategyConfig(spread=0.40)
    res = run_backtest(candles, [signal], config=cfg)
    assert len(res.trades) == 0


# --- Phase 3B: Order Fill Realism Tests ---

def test_signal_candle_does_not_retroactively_fill_order():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    # Sinyal mumu (idx 20) limit entry seviyesine (99.0) değiyor!
    candles_data[20] = (100.0, 100.5, 98.5, 100.0)

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=99.0, stop_loss=97.0, reason="A+")

    # Sonraki mumlar (idx 21+) 99.0 seviyesine hiç değmiyor (low = 99.5)
    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    # Sinyal mumu retroaktif olarak emri doldurmamalıdır!
    assert len(result.trades) == 0
    assert result.unfilled_orders == 1


def test_next_candle_touches_long_limit_fills_correctly():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=99.0, stop_loss=97.0, reason="A+")

    # idx 21: low = 98.5 (<= limit 99.0) -> Limit dolumu idx 21'de gerçekleşmeli!
    candles_data[21] = (100.0, 100.5, 98.5, 100.0)
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)  # TP 110.0 hit at idx 22

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.filled is True
    assert t.entry_fill_index == 21
    assert t.executed_entry == 99.0
    assert t.won is True


def test_next_candle_never_reaches_long_limit_remains_unfilled():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=99.0, stop_loss=97.0, reason="A+")

    # Tüm sonraki mumlarda fiyat en düşük 99.5 (limit 99.0'a hiç ulaşamıyor)
    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 0
    assert result.unfilled_orders == 1


def test_short_limit_fills_correctly():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)

    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=101.0, stop_loss=103.0, reason="A+")

    # idx 21: high = 101.5 (>= limit 101.0) -> Short limit dolumu gerçekleşir
    candles_data[21] = (100.0, 101.5, 99.5, 100.0)
    candles_data[22] = (100.0, 100.5, 89.0, 89.5)  # TP 90.0 hit at idx 22

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.filled is True
    assert t.entry_fill_index == 21
    assert t.executed_entry == 101.0
    assert t.won is True


def test_short_never_reaches_limit_unfilled():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)

    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=101.0, stop_loss=103.0, reason="A+")

    # Tüm mumlarda high en fazla 100.5 (< limit 101.0)
    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 0
    assert result.unfilled_orders == 1


def test_gap_through_long_fill():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=99.0, stop_loss=96.0, reason="A+")

    # idx 21: Open = 97.0 (gap down through limit 99.0). Fill occurs at open 97.0 (better price fill)!
    candles_data[21] = (97.0, 98.0, 96.5, 97.5)
    candles_data[22] = (97.5, 111.0, 97.0, 110.5)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.executed_entry == 97.0  # Limit 99.0'dan daha iyi (97.0) fiyatla doldu!


def test_gap_through_short_fill():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)

    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=101.0, stop_loss=104.0, reason="A+")

    # idx 21: Open = 103.0 (gap up through limit 101.0). Fill occurs at open 103.0 (better price fill for short)!
    candles_data[21] = (103.0, 103.5, 102.0, 102.5)
    candles_data[22] = (102.5, 103.0, 89.0, 89.5)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.executed_entry == 103.0  # Limit 101.0'dan daha iyi (103.0) fiyatla doldu!


def test_same_bar_entry_and_tp_ambiguity_no_optimistic_tp():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    # idx 21: low = 99.5 (<= entry 100.0) AND high = 111.0 (>= TP 110.0)
    # Aynı mumda dolum + TP: Yol sırası belirsiz olduğundan iyimser TP verilmemeli!
    candles_data[21] = (100.0, 111.0, 99.5, 105.0)
    # idx 22: Sonraki mumda TP tekrar vuruluyor
    candles_data[22] = (105.0, 111.0, 104.0, 110.0)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.entry_fill_index == 21
    assert t.exit_index == 22  # TP 21. mumda değil 22. mumda kapandı!


def test_same_bar_entry_and_sl_pessimistic_fill():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    # idx 21: low = 97.0 (<= entry 100.0 VE <= SL 98.0!)
    # Aynı mumda dolum + SL: Kötümser olarak 21. mumda SL ile kapanmalı!
    candles_data[21] = (100.0, 100.5, 97.0, 97.5)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.entry_fill_index == 21
    assert t.exit_index == 21
    assert t.won is False
    assert t.r_multiple == -1.0


def test_same_bar_entry_sl_tp_all_reachable_pessimistic_sl_first():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)

    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    # idx 21: high = 112.0 (>= TP 110.0) AND low = 96.0 (<= entry 100.0 VE <= SL 98.0)
    # Giriş, SL ve TP hepsi aynı mumda! Kötümser kural gereği SL kazanır!
    candles_data[21] = (100.0, 112.0, 96.0, 105.0)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.entry_fill_index == 21
    assert t.exit_index == 21
    assert t.won is False
    assert t.r_multiple == -1.0


def test_buy_gap_through_with_large_slippage_applies_beyond_limit():
    # 2026-09-07: market-emri modelinde slippage KOSULSUZ uygulanir -- entry
    # mumu limit'ten daha IYI (99.90) acilsa bile, dolum yine de
    # signal.entry'den kotu olabilir (canli EA market emriyle acar, limit
    # emri gibi "asla kotu olamaz" garantisi yok).
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    candles_data[21] = (99.90, 100.5, 99.0, 100.0)
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)

    candles = _make_dummy_candles(candles_data)
    cfg = StrategyConfig(slippage=0.30)
    res = run_backtest(candles, [signal], config=cfg)

    assert len(res.trades) == 1
    # market_price = min(entry=100.0, open=99.90) = 99.90; +slippage(0.30) = 100.20
    assert res.trades[0].executed_entry == pytest.approx(100.20)


def test_sell_gap_through_with_large_slippage_applies_beyond_limit():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)
    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=102.0, reason="A+")

    candles_data[21] = (100.10, 100.5, 99.0, 99.5)
    candles_data[22] = (99.5, 100.0, 89.0, 89.5)

    candles = _make_dummy_candles(candles_data)
    cfg = StrategyConfig(slippage=0.30)
    res = run_backtest(candles, [signal], config=cfg)

    assert len(res.trades) == 1
    # market_price = max(entry=100.0, open=100.10) = 100.10; -slippage(0.30) = 99.80
    assert res.trades[0].executed_entry == pytest.approx(99.80)


def test_buy_intrabar_touch_with_slippage_applies_beyond_limit():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    candles_data[21] = (101.0, 101.5, 99.8, 100.5)
    candles_data[22] = (100.5, 111.0, 100.0, 110.5)

    candles = _make_dummy_candles(candles_data)
    cfg = StrategyConfig(slippage=0.20)
    res = run_backtest(candles, [signal], config=cfg)

    assert len(res.trades) == 1
    # market_price = min(entry=100.0, open=101.0) = 100.0; +slippage(0.20) = 100.20
    assert res.trades[0].executed_entry == pytest.approx(100.20)


def test_sell_intrabar_touch_with_slippage_applies_beyond_limit():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 101.0, 90.0, 95.0)
    candles_data[15] = (100.0, 101.0, 90.0, 95.0)
    signal = Signal(index=20, type=SignalType.SELL, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=102.0, reason="A+")

    candles_data[21] = (99.0, 100.2, 98.5, 99.5)
    candles_data[22] = (99.5, 100.0, 89.0, 89.5)

    candles = _make_dummy_candles(candles_data)
    cfg = StrategyConfig(slippage=0.20)
    res = run_backtest(candles, [signal], config=cfg)

    assert len(res.trades) == 1
    # market_price = max(entry=100.0, open=99.0) = 100.0; -slippage(0.20) = 99.80
    assert res.trades[0].executed_entry == pytest.approx(99.80)


def test_small_slippage_consumes_some_gap_improvement():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    candles_data[5] = (100.0, 110.0, 99.0, 105.0)
    candles_data[15] = (100.0, 110.0, 99.0, 105.0)
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS, entry=100.0, stop_loss=98.0, reason="A+")

    candles_data[21] = (99.50, 100.5, 99.0, 100.0)
    candles_data[22] = (100.0, 111.0, 99.5, 110.5)

    candles = _make_dummy_candles(candles_data)
    cfg = StrategyConfig(slippage=0.20)
    res = run_backtest(candles, [signal], config=cfg)

    assert len(res.trades) == 1
    assert res.trades[0].executed_entry == pytest.approx(99.70)


# --- 2026-09-02: acik (explicit) take_profit + breakeven-stop testleri ---
# (bkz. strategy/signal_engine.py -- artik FVG/iFVG/OB/Trendline kendi
# resmi TP/breakeven parametrelerini Signal uzerinden bildiriyor)

def test_explicit_take_profit_bypasses_support_resistance():
    # S/R seviyesi kurulumu YOK (candles_data[5]/[15] atlaniyor) -- sinyal
    # kendi take_profit'ini bildirdigi icin _find_take_profit hic cagrilmiyor.
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.FVG_ONLY,
                    entry=100.0, stop_loss=98.0, take_profit=105.0, reason="explicit-tp")
    candles_data[22] = (100.0, 106.0, 99.5, 105.5)

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.won is True
    assert trade.exit_price == 105.0
    assert trade.r_multiple == pytest.approx((105.0 - 100.0) / (100.0 - 98.0))


def test_breakeven_arm_converts_reversal_to_zero_r():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.FVG_ONLY,
                    entry=100.0, stop_loss=98.0, take_profit=106.0, breakeven_trigger_pct=0.5, reason="be")
    # idx21: dolum (arka plan, low=99.5<=100.0)
    candles_data[22] = (100.0, 103.5, 99.8, 103.0)   # arm_level=103.0 asiliyor -- SL/TP vurulmuyor
    candles_data[23] = (103.0, 103.2, 99.0, 99.5)     # geri donup ORIJINAL SL(98.0) yerine effective_sl(entry=100.0)'e takiliyor

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.won is False
    assert trade.is_breakeven is True
    assert trade.exit_price == 100.0          # entry'ye cekilmis effective_sl
    assert trade.r_multiple == pytest.approx(0.0)


def test_breakeven_not_armed_when_arm_level_never_reached():
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.FVG_ONLY,
                    entry=100.0, stop_loss=98.0, take_profit=106.0, breakeven_trigger_pct=0.5, reason="be")
    candles_data[22] = (100.0, 101.0, 99.7, 100.5)    # arm_level(103.0)'e ulasmiyor
    candles_data[23] = (100.5, 100.6, 97.5, 98.0)      # dogrudan ORIJINAL SL(98.0)'e takiliyor

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.won is False
    assert trade.is_breakeven is False
    assert trade.exit_price == 98.0
    assert trade.r_multiple == pytest.approx(-1.0)


def test_no_breakeven_when_trigger_pct_is_none():
    # breakeven_trigger_pct verilmediyse (varsayilan None) -- arm hic olmaz,
    # arm seviyesini asan bir hareket sonrasi bile orijinal SL'e takilir.
    candles_data = [(100.0, 100.5, 99.5, 100.0) for _ in range(25)]
    signal = Signal(index=20, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.FVG_ONLY,
                    entry=100.0, stop_loss=98.0, take_profit=106.0, reason="no-be")
    candles_data[22] = (100.0, 103.5, 99.8, 103.0)     # breakeven acik olsaydi arm olurdu -- ama kapali
    candles_data[23] = (103.0, 103.2, 99.0, 99.5)       # orijinal SL(98.0)'e HENUZ ulasmiyor (low=99.0)
    candles_data[24] = (99.5, 99.6, 97.5, 98.0)          # simdi orijinal SL(98.0)'e takiliyor

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.is_breakeven is False
    assert trade.exit_price == 98.0
    assert trade.r_multiple == pytest.approx(-1.0)


# --- 2026-09-04 regresyon testleri (bkz. backtest/engine.py MAX_GAP_FILL_RISK_MULTIPLE
# yorumu) -- CHFJPY 2015-01-15 SNB CHF depeg soku gibi, sinyalin kendi (kucuk)
# riskine gore anlamsiz derecede uzak bir "dolum" gecerli sayilmamali. Bu
# koruma eklenmeden once, boyle bir sicrama +413R gibi sahte R degerleri
# ureterek gercekte kayip olan islemleri bile "kazanc" gibi gosterebiliyordu
# (bkz. audit denetiminde bulunan Bulgu #7 -- bu senaryo icin regresyon
# testi eksikti).

def test_extreme_gap_fill_rejected_and_signal_remains_unfilled():
    # risk = |100-98| = 2.0, MAX_GAP_FILL_RISK_MULTIPLE=3.0 -> kabul siniri
    # entry'den +/-6 birim. index 1'deki sicrama (entry'den 50 birim uzakta)
    # naif mantikla "dolum" sayilirdi (ask_low <= entry) -- ama GECERSIZ
    # sayilip taramaya devam edilmeli. Sonraki mumlar entry'nin (100) HEP
    # USTUNDE kalip bir daha hic dokunmuyor -- sinyal sonuna kadar
    # doldurulamamis kalmali.
    candles_data = [(100.0, 100.2, 99.8, 100.0)]
    candles_data.append((50.0, 55.0, 45.0, 52.0))          # asiri sicrama -- reddedilir
    candles_data += [(110.0, 112.0, 108.0, 110.0)] * 4      # entry'nin (100) ustunde kaliyor, bir daha dokunmuyor
    signal = Signal(index=0, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS,
                    entry=100.0, stop_loss=98.0, take_profit=104.0, reason="A+")

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 0
    assert result.unfilled_orders == 1


def test_extreme_gap_rejected_then_genuine_later_fill_still_counted():
    # Asiri sicrama reddedildikten SONRA fiyat gercekten (kucuk/normal bir
    # hareketle, gap sinirinin ICINDE) entry seviyesine donerse, taramaya
    # devam edilip GECERLI bir islem olusturulmali -- gap reddi taramayi
    # kalici olarak durdurmamali.
    candles_data = [(100.0, 100.2, 99.8, 100.0)]
    candles_data.append((50.0, 55.0, 45.0, 52.0))          # asiri sicrama -- reddedilir
    candles_data.append((110.0, 112.0, 108.0, 110.0))       # entry'nin (100) ustunde, henuz dokunmuyor
    candles_data.append((101.0, 102.0, 99.5, 100.5))        # simdi GERCEKTEN entry'ye (100) dokunuyor -- normal dolum
    candles_data.append((100.0, 104.5, 99.5, 104.0))        # TP (104) vuruluyor
    signal = Signal(index=0, type=SignalType.BUY, confidence=Confidence.HIGH, setup_type=SetupType.A_PLUS,
                    entry=100.0, stop_loss=98.0, take_profit=104.0, reason="A+")

    candles = _make_dummy_candles(candles_data)
    result = run_backtest(candles, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_fill_index == 3
    assert trade.executed_entry == pytest.approx(100.0)
    assert trade.won is True
    assert trade.r_multiple == pytest.approx(2.0)  # (104-100)/(100-98)
