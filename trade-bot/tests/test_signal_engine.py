"""
Sinyal Motoru Entegrasyon Testleri (Integration Tests for strategy/signal_engine.py).
"""

from datetime import datetime, timedelta
import pytest

from strategy.signal_engine import (
    generate_signals,
    SignalType,
    Confidence,
    SetupType,
    Signal,
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


def test_aplus_confluence_signal_generation():
    candles_data = [(100.0 + i * 0.01, 100.25 + i * 0.01, 99.75 + i * 0.01, 100.0 + i * 0.01) for i in range(60)]
    candles_data[10] = (100.0, 110.0, 102.0, 105.0)
    candles_data[20] = (100.0, 100.0, 90.0, 95.0)
    candles_data[30] = (105.0, 120.0, 105.0, 115.0)
    candles_data[40] = (100.0, 100.0, 95.0, 98.0)

    candles_data[50] = (100.0, 101.0, 99.5, 100.5)   # c1 high = 101.0
    candles_data[51] = (101.0, 103.0, 100.5, 102.8)  # c2 (OB range=2.5)
    candles_data[52] = (102.8, 104.0, 102.0, 103.5)  # c3 low = 102.0 -> FVG zone [101.0, 102.0]
    for i in range(53, 60):
        candles_data[i] = (103.0 + i * 0.1, 104.0 + i * 0.1, 102.5, 103.5)

    candles = _make_dummy_candles(candles_data)
    signals = generate_signals(candles)

    aplus_signals = [s for s in signals if s.setup_type == SetupType.A_PLUS]
    assert len(aplus_signals) >= 1

    sig = aplus_signals[0]
    assert sig.type == SignalType.BUY
    assert sig.confidence == Confidence.HIGH
    assert sig.entry == 101.0
    assert sig.stop_loss == 100.5


def test_standalone_signals_confidence_cap():
    candles_data = [(100.0 + i * 0.01, 100.25 + i * 0.01, 99.75 + i * 0.01, 100.0 + i * 0.01) for i in range(60)]
    candles_data[10] = (100.0, 110.0, 102.0, 105.0)
    candles_data[20] = (100.0, 100.0, 90.0, 95.0)
    candles_data[30] = (105.0, 120.0, 105.0, 115.0)
    candles_data[40] = (100.0, 100.0, 95.0, 98.0)

    # Sadece Bullish FVG (c2 range = 0.8 < OB threshold, c3 idx 53 low=101.2 prevents 2nd FVG)
    candles_data[50] = (100.0, 101.0, 99.5, 100.5)   # c1 high = 101.0
    candles_data[51] = (101.0, 101.3, 100.5, 101.2)  # c2 range = 0.8 (NOT an OB)
    candles_data[52] = (101.2, 103.5, 102.0, 103.0)  # c3 low = 102.0 -> Bullish FVG [101.0, 102.0]
    candles_data[53] = (103.0, 104.0, 101.2, 103.5)
    for i in range(54, 60):
        candles_data[i] = (103.0 + i * 0.1, 104.0 + i * 0.1, 102.5, 103.5)

    candles = _make_dummy_candles(candles_data)
    signals = generate_signals(candles)

    # idx10/20/30/40'taki dolgu mumları da (causal olarak, kendi oluştukları
    # barda henüz dolmamış) ayrı, ilgisiz bir bearish FVG_ONLY sinyali
    # üretiyor (idx32) -- testin asıl konusu olan bullish FVG'yi (idx52)
    # yön filtresiyle izole ediyoruz.
    fvg_signals = [s for s in signals if s.setup_type == SetupType.FVG_ONLY and s.type == SignalType.BUY]
    assert len(fvg_signals) >= 1
    assert fvg_signals[0].confidence == Confidence.MEDIUM


def test_opposite_trend_signal_filtering():
    candles_data = [(100.0 + i * 0.01, 100.1 + i * 0.01, 99.9 + i * 0.01, 100.0 + i * 0.01) for i in range(60)]
    candles_data[10] = (115.0, 120.0, 112.0, 118.0)
    candles_data[20] = (100.0, 100.0, 95.0, 98.0)
    candles_data[30] = (105.0, 110.0, 105.0, 108.0)
    candles_data[40] = (100.0, 100.0, 90.0, 92.0)
    for i in range(41, 60):
        candles_data[i] = (85.0, 86.0 - (i - 40) * 0.05, 75.0, 80.0)

    candles_data[50] = (100.0, 101.0, 99.0, 100.5)
    candles_data[51] = (101.0, 103.0, 100.5, 102.5)
    candles_data[52] = (102.5, 104.0, 102.0, 103.5)

    candles = _make_dummy_candles(candles_data)
    signals = generate_signals(candles)

    # idx30'daki dolgu mumu, düşüş trendi henüz kurulmadan (idx41+) önce
    # kendi barında geçerli bir bullish OB oluşturuyor -- bu, testin konusu
    # olan "kurulmuş düşüş trendine ters sinyal" durumu değil (o mum
    # oluştuğunda trend henüz ters değil). Asıl kontrol, trend kurulduktan
    # SONRAKİ barlarda BUY sinyali üretilmediği.
    buy_signals = [s for s in signals if s.type == SignalType.BUY and s.index >= 41]
    assert len(buy_signals) == 0
