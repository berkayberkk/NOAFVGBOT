"""
Destek / Direnç Modülü Birim Testleri (Unit Tests for strategy/support_resistance.py).
"""

from datetime import datetime, timedelta
import pytest

from strategy.support_resistance import (
    find_swing_points,
    build_levels,
    LevelType,
    Level,
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


def test_find_swing_points():
    candles_data = [(100.0, 100.0 + (i % 3) * 0.1, 99.0, 100.0) for i in range(30)]
    candles_data[6] = (100.0, 110.0, 99.0, 105.0)   # peak high
    candles_data[18] = (100.0, 101.0, 85.0, 95.0)   # trough low

    candles = _make_dummy_candles(candles_data)
    highs, lows = find_swing_points(candles, lookback=5)

    assert 6 in highs
    assert 18 in lows


def test_build_levels_clustering_and_touch_count():
    # Arka plan mumlarına dalgalanma verilerek tekil swing high'lar oluşturuluyor
    candles_data = [(100.0, 100.0 + (i % 3) * 0.1, 99.0, 100.0) for i in range(30)]
    candles_data[6] = (100.0, 110.0, 99.0, 105.0)   # swing high 1
    candles_data[18] = (100.0, 110.2, 99.0, 105.0)  # swing high 2

    candles = _make_dummy_candles(candles_data)
    levels = build_levels(candles, tolerance_atr_ratio=0.5, lookback=5)

    resistance_levels = [l for l in levels if l.type == LevelType.RESISTANCE and l.price > 105.0]
    assert len(resistance_levels) == 1

    lvl = resistance_levels[0]
    assert lvl.touch_count == 2
    assert lvl.first_index == 6
    assert lvl.last_index == 18
    assert abs(lvl.price - 110.1) < 0.05


def test_levels_outside_tolerance_not_clustered():
    candles_data = [(100.0, 100.0 + (i % 3) * 0.1, 99.0, 100.0) for i in range(30)]
    candles_data[6] = (100.0, 110.0, 99.0, 105.0)   # resistance at 110.0
    candles_data[18] = (100.0, 130.0, 99.0, 125.0)  # resistance at 130.0 (far away)

    candles = _make_dummy_candles(candles_data)
    levels = build_levels(candles, tolerance_atr_ratio=0.5, lookback=5)

    resistance_levels = [l for l in levels if l.type == LevelType.RESISTANCE and l.price > 105.0]
    assert len(resistance_levels) == 2
    assert resistance_levels[0].touch_count == 1
    assert resistance_levels[1].touch_count == 1
