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
    # Standart tanim: displacement (guclu YUKSELIS) mumundan HEMEN ONCEKI
    # son ZIT (bearish) mum OB olur -- displacement mumunun kendisi degil.
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]      # idx 13: bearish mum -- bu OB olacak
    impulse_candle = [(99.5, 106.0, 99.4, 105.5)]      # idx 14: guclu yukselis (displacement)
    candles = _make_dummy_candles(neutral_candles + last_opposite + impulse_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 1

    ob = blocks[0]
    assert ob.index == 13                # OB mumu -- son zit mum
    assert ob.impulse_index == 14         # displacement mumu ayri alanda
    assert ob.direction == OBDirection.BULLISH
    assert ob.top == 100.5                # govde ust siniri (max(open,close))
    assert ob.bottom == 99.5              # govde alt siniri (min(open,close))
    assert ob.mitigated is False


def test_bearish_order_block_detection():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(99.5, 100.8, 99.3, 100.5)]       # idx 13: bullish mum -- bu OB olacak
    impulse_candle = [(100.5, 100.6, 94.0, 94.5)]       # idx 14: guclu dusus (displacement)
    candles = _make_dummy_candles(neutral_candles + last_opposite + impulse_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 1

    ob = blocks[0]
    assert ob.index == 13
    assert ob.impulse_index == 14
    assert ob.direction == OBDirection.BEARISH
    assert ob.top == 100.5
    assert ob.bottom == 99.5
    assert ob.mitigated is False


def test_weak_candle_not_order_block():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    weak_candle = [(100.0, 101.5, 99.0, 101.0)]
    candles = _make_dummy_candles(neutral_candles + weak_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 0


def test_same_direction_candle_before_impulse_is_skipped():
    # impuls mumundan hemen once AYNI yonde (bullish) kucuk bir mum varsa,
    # dedektor onu atlayip bir ONCEKI GERCEK zit (bearish) mumu OB secmeli.
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 12
    last_opposite = [(100.5, 100.8, 99.0, 99.2)]        # idx 12: bearish -- GERCEK OB bu olmali
    same_dir_filler = [(99.2, 99.8, 99.1, 99.6)]         # idx 13: kucuk bullish mum -- atlanmali
    impulse_candle = [(99.6, 107.0, 99.5, 106.5)]        # idx 14: guclu yukselis
    candles = _make_dummy_candles(neutral_candles + last_opposite + same_dir_filler + impulse_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 1
    assert blocks[0].index == 12
    assert blocks[0].top == 100.5
    assert blocks[0].bottom == 99.2


def test_order_block_mitigation():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]        # idx 13: Bullish OB govdesi [99.5, 100.5]
    impulse_candle = [(99.5, 106.0, 99.4, 105.5)]        # idx 14: displacement
    subsequent_candles = [
        (105.5, 107.0, 104.0, 106.0),  # idx 15: bolgenin disinda, close = 106.0 > 100.5
        (100.0, 100.5, 98.5, 99.0),    # idx 16: close = 99.0 < 99.5 (OB govdesini gecersiz kilar)
    ]
    candles = _make_dummy_candles(neutral_candles + last_opposite + impulse_candle + subsequent_candles)

    blocks = detect_order_blocks(candles)
    mark_mitigated_blocks(blocks, candles)

    assert len(blocks) == 1
    assert blocks[0].mitigated is True
    assert blocks[0].mitigated_index == 16
