"""
FVG Modülü Birim Testleri (Unit Tests for strategy/fvg.py).
"""

from datetime import datetime, timedelta
import pytest

from strategy.fvg import (
    detect_fvgs,
    mark_filled_fvgs,
    compute_atr_series,
    FVGDirection,
    FVG,
)


def _make_dummy_candles(ohlc_list: list[tuple[float, float, float, float]]) -> list[dict]:
    """Yardımcı fonksiyon: (open, high, low, close) tuple listesinden mum dict'leri üretir."""
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


def test_bullish_fvg_detection():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    fvg_candles = [
        (100.0, 101.0, 99.0, 100.5),   # c1 (idx 14)
        (101.0, 103.0, 100.5, 102.8),  # c2 (idx 15)
        (102.8, 104.0, 102.0, 103.5),  # c3 (idx 16)
    ]
    candles = _make_dummy_candles(neutral_candles + fvg_candles)

    fvgs = detect_fvgs(candles)
    assert len(fvgs) >= 1

    bullish_fvgs = [f for f in fvgs if f.direction == FVGDirection.BULLISH]
    assert len(bullish_fvgs) == 1

    fvg = bullish_fvgs[0]
    assert fvg.start_index == 14
    assert fvg.end_index == 16
    assert fvg.bottom == 101.0
    assert fvg.top == 102.0
    assert fvg.entry_price == 101.0
    assert fvg.valid is True
    assert fvg.filled is False


def test_bearish_fvg_detection():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    fvg_candles = [
        (100.0, 101.0, 99.0, 99.5),   # c1 (idx 14)
        (99.0, 99.5, 97.0, 97.2),     # c2 (idx 15)
        (97.2, 98.0, 96.0, 96.5),     # c3 (idx 16)
    ]
    candles = _make_dummy_candles(neutral_candles + fvg_candles)

    fvgs = detect_fvgs(candles)
    bearish_fvgs = [f for f in fvgs if f.direction == FVGDirection.BEARISH]
    assert len(bearish_fvgs) == 1

    fvg = bearish_fvgs[0]
    assert fvg.start_index == 14
    assert fvg.end_index == 16
    assert fvg.bottom == 98.0
    assert fvg.top == 99.0
    assert fvg.entry_price == 99.0
    assert fvg.valid is True


def test_fvg_atr_threshold_filtering():
    neutral_candles = [(100.0, 105.0, 95.0, 100.0)] * 14  # ATR ~ 10.0
    small_gap_candles = [
        (100.0, 101.0, 99.0, 100.5),   # c1 high = 101.0
        (101.0, 102.0, 100.5, 101.5),  # c2
        (101.5, 103.0, 101.1, 102.5),  # c3 low = 101.1 -> gap = 0.1, gap/ATR = 0.01 < 0.15
    ]
    candles = _make_dummy_candles(neutral_candles + small_gap_candles)
    fvgs = detect_fvgs(candles)
    assert len(fvgs) == 1
    assert fvgs[0].valid is False
    assert "mesafe kuralı dışında" in fvgs[0].invalid_reason


def test_fvg_disproportionate_middle_candle():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14 # ATR ~ 2.0
    unbalanced_candles = [
        (100.0, 101.0, 99.0, 100.0),   # c1 high = 101.0
        (100.0, 110.0, 95.0, 109.0),   # c2 range = 15.0 (huge middle candle)
        (109.0, 112.0, 102.0, 111.0),  # c3 low = 102.0 -> gap = 1.0, middle_range(15) > gap(1)*3
    ]
    candles = _make_dummy_candles(neutral_candles + unbalanced_candles)
    fvgs = detect_fvgs(candles)
    assert len(fvgs) == 1
    assert fvgs[0].valid is False
    assert "dengesiz FVG" in fvgs[0].invalid_reason


def test_multi_fvg_proximity_cancellation():
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    multi_fvg_candles = [
        (100.0, 101.0, 99.0, 100.0),   # idx 14 (c1 for FVG 1)
        (100.5, 101.5, 100.2, 101.2),  # idx 15 (c2 for FVG 1, c1 for FVG 2)
        (101.5, 103.0, 102.0, 102.8),  # idx 16 (c3 for FVG 1: low=102.0; c2 for FVG 2)
        (102.8, 104.0, 102.5, 103.8),  # idx 17 (c3 for FVG 2: low=102.5)
    ]
    candles = _make_dummy_candles(neutral_candles + multi_fvg_candles)
    fvgs = detect_fvgs(candles)
    assert len(fvgs) == 2
    # Her iki çakışan FVG de geçersiz kılınmalı (döngü sırasından bağımsız)
    assert fvgs[0].valid is False
    assert fvgs[1].valid is False
    assert "multi FVG" in fvgs[0].invalid_reason
    assert "multi FVG" in fvgs[1].invalid_reason


def test_mark_filled_fvgs():
    # Bullish FVG gap = [101.0, 102.0] (bottom=101.0, top=102.0). "Doldu" artık
    # KAPANIŞ bazlı: bir mumun kapanışı bottom'un tamamen ALTINA çıkmadıkça
    # (sadece fitille değmek/içine girmek dahil) FVG geçersiz sayılmaz.
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    fvg_candles = [
        (100.0, 101.0, 99.0, 100.5),   # c1 (14)
        (101.0, 103.0, 100.5, 102.8),  # c2 (15)
        (102.8, 104.0, 102.0, 103.5),  # c3 (16) -> Bullish FVG gap [101.0, 102.0]
        (103.5, 104.0, 103.0, 103.8),  # 17 -> gap'e hic degmiyor
        (103.8, 104.0, 100.0, 100.5),  # 18 -> kapanis 100.5 < 101.0 (bottom) -> doldu
    ]
    candles = _make_dummy_candles(neutral_candles + fvg_candles)
    fvgs = detect_fvgs(candles)
    mark_filled_fvgs(fvgs, candles)

    bullish_fvg = [f for f in fvgs if f.direction == FVGDirection.BULLISH][0]
    assert bullish_fvg.filled is True
    assert bullish_fvg.filled_at_index == 18


def test_wick_touch_into_fvg_does_not_invalidate_it():
    # Fitil gap'in en dibine kadar girip (hatta bottom'a esit low ile) geri
    # donerse -- kapanis bottom'un USTUNDE kaldigi surece -- FVG hala
    # kullanilabilir sayilmali (kullanici duzeltmesi: "degmesi veya biraz
    # icine girmesi sikinti cikarmaz, yeterki disina cikmasin").
    neutral_candles = [(100.0, 101.0, 99.0, 100.0)] * 14
    fvg_candles = [
        (100.0, 101.0, 99.0, 100.5),   # c1 (14)
        (101.0, 103.0, 100.5, 102.8),  # c2 (15)
        (102.8, 104.0, 102.0, 103.5),  # c3 (16) -> Bullish FVG gap [101.0, 102.0]
        (103.5, 104.0, 101.0, 103.0),  # 17 -> fitil tam bottom'a (101.0) iniyor, kapanis 103.0 (gap ustunde)
    ]
    candles = _make_dummy_candles(neutral_candles + fvg_candles)
    fvgs = detect_fvgs(candles)
    mark_filled_fvgs(fvgs, candles)

    bullish_fvg = [f for f in fvgs if f.direction == FVGDirection.BULLISH][0]
    assert bullish_fvg.filled is False
