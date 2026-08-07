"""
Trend Modülü Birim Testleri (Unit Tests for strategy/trend.py).
"""

from datetime import datetime, timedelta
import pytest

from strategy.trend import (
    detect_trend,
    compute_ema_series,
    TrendDirection,
    TrendState,
)


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


def test_trend_up_higher_highs_higher_lows():
    # 60 mumluk lineer sürünen arka plan verisi (yanlışlıkla düz mum swing'i oluşmasın)
    candles_data = [(100.0 + i * 0.01, 100.1 + i * 0.01, 99.9 + i * 0.01, 100.0 + i * 0.01) for i in range(60)]
    # Swing high 1 at 10 (110.0), swing low 1 at 20 (90.0)
    candles_data[10] = (100.0, 110.0, 102.0, 105.0)
    candles_data[20] = (100.0, 100.0, 90.0, 95.0)
    # Swing high 2 at 30 (120.0 > 110.0), swing low 2 at 40 (95.0 > 90.0) -> UP
    candles_data[30] = (105.0, 120.0, 105.0, 115.0)
    candles_data[40] = (100.0, 100.0, 95.0, 98.0)
    # Son mum kapanışı EMA 50 üstünde (close=120.0 > EMA ~ 101.0)
    candles_data[59] = (110.0, 125.0, 109.0, 120.0)

    candles = _make_dummy_candles(candles_data)
    trend_states = detect_trend(candles, lookback=5, ema_period=50)

    last_state = trend_states[-1]
    assert last_state.direction == TrendDirection.UP
    assert last_state.ema_aligned is True
    assert last_state.strong is True


def test_trend_down_lower_highs_lower_lows():
    candles_data = [(100.0 + i * 0.01, 100.1 + i * 0.01, 99.9 + i * 0.01, 100.0 + i * 0.01) for i in range(60)]
    # Swing high 1 at 10 (120.0), swing low 1 at 20 (95.0)
    candles_data[10] = (115.0, 120.0, 112.0, 118.0)
    candles_data[20] = (100.0, 100.0, 95.0, 98.0)
    # Swing high 2 at 30 (110.0 < 120.0), swing low 2 at 40 (90.0 < 95.0) -> DOWN
    candles_data[30] = (105.0, 110.0, 105.0, 108.0)
    candles_data[40] = (100.0, 100.0, 90.0, 92.0)
    # Son mum kapanışı EMA 50 altında (close=80.0 < EMA ~ 100.0)
    candles_data[59] = (82.0, 85.0, 78.0, 80.0)

    candles = _make_dummy_candles(candles_data)
    trend_states = detect_trend(candles, lookback=5, ema_period=50)

    last_state = trend_states[-1]
    assert last_state.direction == TrendDirection.DOWN
    assert last_state.ema_aligned is True
    assert last_state.strong is True


def test_trend_sideways_and_short_history():
    candles_data = [(100.0, 100.2, 99.8, 100.0)] * 20
    candles = _make_dummy_candles(candles_data)

    trend_states = detect_trend(candles, lookback=5, ema_period=50)
    assert len(trend_states) == 20
    assert trend_states[-1].direction == TrendDirection.SIDEWAYS
    assert trend_states[-1].strong is False
