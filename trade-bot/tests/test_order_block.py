"""
Order Block Modülü Birim Testleri (Unit Tests for strategy/order_block.py).
"""

from dataclasses import replace
from datetime import datetime, timedelta
import pytest

from strategy.config import DEFAULT_CONFIG
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


def test_engulfing_true_when_impulse_covers_ob_full_wick_range():
    # Impuls mumu, OB mumunun fitil dahil TUM high-low araligini kapsiyor
    # (impulse.high >= ob.high VE impulse.low <= ob.low).
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]        # idx 13: high=100.8, low=99.2
    impulse_candle = [(99.5, 106.0, 99.0, 105.5)]        # idx 14: high=106.0>=100.8, low=99.0<=99.2
    candles = _make_dummy_candles(neutral_candles + last_opposite + impulse_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 1
    assert blocks[0].engulfing is True


def test_engulfing_false_when_impulse_does_not_cover_ob_low():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]        # idx 13: low=99.2
    impulse_candle = [(99.5, 106.0, 99.4, 105.5)]        # idx 14: low=99.4 > 99.2 -- kapsamiyor
    candles = _make_dummy_candles(neutral_candles + last_opposite + impulse_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 1
    assert blocks[0].engulfing is False


def test_swept_liquidity_true_when_ob_candle_breaks_prior_window_low():
    # Onceki 10 barin (varsayilan ob_liquidity_sweep_lookback) en dusuk
    # dip'i 99.0 -- OB mumunun kendi dip'i (98.0) bunun altina geciyor.
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(100.5, 100.8, 98.0, 99.5)]        # idx 13: low=98.0 < 99.0
    impulse_candle = [(99.5, 106.0, 99.4, 105.5)]        # idx 14
    candles = _make_dummy_candles(neutral_candles + last_opposite + impulse_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 1
    assert blocks[0].swept_liquidity is True


def test_swept_liquidity_false_when_ob_candle_stays_within_prior_window():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]        # idx 13: low=99.2 > 99.0 -- supurme yok
    impulse_candle = [(99.5, 106.0, 99.4, 105.5)]        # idx 14
    candles = _make_dummy_candles(neutral_candles + last_opposite + impulse_candle)

    blocks = detect_order_blocks(candles)
    assert len(blocks) == 1
    assert blocks[0].swept_liquidity is False


def test_htf_discount_aligned_true_for_bullish_ob_in_lower_half():
    # ob_premium_discount_lookback=5 kucultulerek test kompakt tutuluyor.
    # Pencere (idx 9-13) high=101.0/low=99.0 -> midpoint=100.0. OB
    # mumunun govde orta noktasi (99.25) bunun ALTINDA -- discount.
    cfg = replace(DEFAULT_CONFIG, ob_premium_discount_lookback=5)
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(99.5, 99.5, 99.0, 99.0)]           # idx 13: bearish, top=99.5, bottom=99.0
    impulse_candle = [(99.0, 106.0, 98.9, 105.5)]        # idx 14
    candles = _make_dummy_candles(neutral_candles + last_opposite + impulse_candle)

    blocks = detect_order_blocks(candles, config=cfg)
    assert len(blocks) == 1
    assert blocks[0].htf_discount_aligned is True


def test_htf_discount_aligned_false_for_bullish_ob_in_upper_half():
    # Ayni pencere/midpoint (100.0), ama OB mumunun govde orta noktasi
    # (100.75) midpoint'in UZERINDE -- premium, bullish icin uyumsuz.
    cfg = replace(DEFAULT_CONFIG, ob_premium_discount_lookback=5)
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(101.0, 101.0, 100.5, 100.5)]       # idx 13: bearish, top=101.0, bottom=100.5
    impulse_candle = [(100.5, 107.0, 100.4, 106.5)]      # idx 14
    candles = _make_dummy_candles(neutral_candles + last_opposite + impulse_candle)

    blocks = detect_order_blocks(candles, config=cfg)
    assert len(blocks) == 1
    assert blocks[0].htf_discount_aligned is False


# --- 2026-09-03: win-rate arastirmasi alanlari (in_killzone, volume_confirmed) ---

def _make_dummy_candles_custom(ohlc_list, base_time=None, volumes=None):
    base_time = base_time or datetime(2026, 1, 1, 0, 0, 0)
    candles = []
    for i, (o, h, l, c) in enumerate(ohlc_list):
        candles.append({
            "time": base_time + timedelta(minutes=30 * i),
            "open": o, "high": h, "low": l, "close": c,
            "tick_volume": volumes[i] if volumes else 100,
            "spread": 10,
        })
    return candles


def test_ob_in_killzone_true_when_impulse_in_london_window():
    # base_time=22:00 -> idx21 (impuls) = 22:00 + 10sa30dk = 08:30 (ertesi gun) -> Londra killzone icinde
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 20
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]
    impulse = [(99.5, 106.0, 99.4, 105.5)]
    candles = _make_dummy_candles_custom(neutral + last_opposite + impulse, base_time=datetime(2026, 1, 1, 22, 0, 0))
    blocks = detect_order_blocks(candles)
    assert candles[21]["time"].hour == 8
    assert blocks[0].in_killzone is True


def test_ob_in_killzone_false_when_impulse_outside_windows():
    # base_time=00:00 -> idx21 = 00:00 + 10sa30dk = 10:30 -> hicbir killzone'da degil
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 20
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]
    impulse = [(99.5, 106.0, 99.4, 105.5)]
    candles = _make_dummy_candles_custom(neutral + last_opposite + impulse)
    blocks = detect_order_blocks(candles)
    assert candles[21]["time"].hour == 10
    assert blocks[0].in_killzone is False


def test_ob_volume_confirmed_true_when_impulse_volume_spikes():
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 20
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]
    impulse = [(99.5, 106.0, 99.4, 105.5)]
    volumes = [100] * 20 + [100, 500]  # impuls (idx21) hacmi 500 -- ortalamanin (100) 5 kati
    candles = _make_dummy_candles_custom(neutral + last_opposite + impulse, volumes=volumes)
    blocks = detect_order_blocks(candles)
    assert blocks[0].volume_confirmed is True


def test_ob_volume_confirmed_false_when_impulse_volume_normal():
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 20
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]
    impulse = [(99.5, 106.0, 99.4, 105.5)]
    volumes = [100] * 22  # impuls hacmi ortalamayla ayni
    candles = _make_dummy_candles_custom(neutral + last_opposite + impulse, volumes=volumes)
    blocks = detect_order_blocks(candles)
    assert blocks[0].volume_confirmed is False
