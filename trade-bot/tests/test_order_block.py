"""
Order Block Modülü Birim Testleri (Unit Tests for strategy/order_block.py).
"""

from datetime import datetime, timedelta
import pytest

from strategy.order_block import (
    detect_order_blocks,
    mark_mitigated_blocks,
    OBDirection,
    OrderBlock,
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


def test_bullish_order_block_detection():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    impulse_candle = [(100.0, 106.0, 99.5, 105.5)]
    candles = _make_dummy_candles(neutral_candles + impulse_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 1

    ob = blocks[0]
    assert ob.index == 14
    assert ob.direction == OBDirection.BULLISH
    assert ob.top == 106.0
    assert ob.bottom == 99.5
    assert ob.mitigated is False


def test_bearish_order_block_detection():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    impulse_candle = [(105.0, 105.5, 99.0, 99.5)]
    candles = _make_dummy_candles(neutral_candles + impulse_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 1

    ob = blocks[0]
    assert ob.index == 14
    assert ob.direction == OBDirection.BEARISH
    assert ob.top == 105.5
    assert ob.bottom == 99.0
    assert ob.mitigated is False


def test_weak_candle_not_order_block():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    weak_candle = [(100.0, 101.5, 99.0, 101.0)]
    candles = _make_dummy_candles(neutral_candles + weak_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 0


def test_order_block_mitigation():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    impulse_bullish = [(100.0, 106.0, 99.5, 105.5)]  # idx 14: Bullish OB [99.5, 106.0]
    subsequent_candles = [
        (105.5, 107.0, 104.0, 106.0),  # idx 15: inside zone, close = 106.0 > 99.5
        (100.0, 100.5, 98.5, 99.0),    # idx 16: range = 2.0 < 4.0, close = 99.0 < 99.5 (mitigates OB)
    ]
    candles = _make_dummy_candles(neutral_candles + impulse_bullish + subsequent_candles)

    blocks = detect_order_blocks(candles)
    mark_mitigated_blocks(blocks, candles)

    assert len(blocks) == 1
    assert blocks[0].mitigated is True
    assert blocks[0].mitigated_index == 16
