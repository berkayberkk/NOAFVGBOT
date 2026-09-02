"""
Sinyal Motoru Entegrasyon Testleri (Integration Tests for strategy/signal_engine.py).

2026-09-02 tamamen yeniden yazıldı -- eski A+/trend-filtreli tasarım
kaldırıldığı için (bkz. modül docstring'i), her testin amacı artık
"generate_signals doğru modülü tetikliyor mu VE bu oturumda kalibre
edilen resmi parametreleri (MODULE_R_MULTIPLE/MODULE_SL_BUFFER_RATIO/
BREAKEVEN_TRIGGER_PCT) doğru uyguluyor mu" sorusuna cevap veriyor --
tespit doğruluğunun kendisi zaten strategy/fvg.py, ifvg.py,
order_block.py, trendline.py'nin kendi birim testlerinde kanıtlanmış.
"""

from dataclasses import replace
from datetime import datetime, timedelta
import pytest

from strategy.signal_engine import generate_signals, SignalType, Confidence, SetupType
from strategy.config import DEFAULT_CONFIG


def _make_dummy_candles(ohlc_list: list[tuple[float, float, float, float]]) -> list[dict]:
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    candles = []
    for i, (o, h, l, c) in enumerate(ohlc_list):
        candles.append({
            "time": base_time + timedelta(minutes=30 * i),
            "open": o, "high": h, "low": l, "close": c,
            "tick_volume": 100, "spread": 10,
        })
    return candles


def test_fvg_signal_uses_official_r_multiple_and_sl_buffer():
    # test_fvg.py::test_bullish_fvg_detection ile ayni FVG (top=102.0, bottom=101.0).
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 14
    fvg = [
        (100.0, 101.0, 99.0, 100.5),
        (101.0, 103.0, 100.5, 102.8),
        (102.8, 104.0, 102.0, 103.5),
    ]
    candles = _make_dummy_candles(neutral + fvg)
    signals = generate_signals(candles)

    fvg_signals = [s for s in signals if s.setup_type == SetupType.FVG_ONLY]
    assert len(fvg_signals) == 1
    s = fvg_signals[0]
    assert s.index == 16
    assert s.type == SignalType.BUY
    assert s.confidence == Confidence.MEDIUM
    assert s.entry == 101.0
    assert s.stop_loss == 100.0        # bottom(101.0) - gap(1.0)*SL_BUFFER_RATIO["fvg"](1.0)
    assert s.take_profit == pytest.approx(102.5)  # entry + R(1.5)*risk(1.0)
    assert s.breakeven_trigger_pct == 0.5           # "fvg" BREAKEVEN_ENABLED_MODULES icinde


def test_ifvg_signal_uses_official_r_multiple_and_sl_buffer():
    # test_ifvg.py::test_confirmed_ifvg_on_break_and_rejection ile ayni senaryo.
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 14
    fvg = [
        (100.0, 101.0, 99.0, 100.5),
        (101.0, 103.0, 100.5, 102.8),
        (102.8, 104.0, 102.0, 103.5),
    ]
    broken = [(100.9, 100.9, 99.5, 100.0)]
    retest = [(100.0, 101.5, 99.8, 100.5)]
    candles = _make_dummy_candles(neutral + fvg + broken + retest)
    signals = generate_signals(candles)

    ifvg_signals = [s for s in signals if s.setup_type == SetupType.IFVG_ONLY]
    assert len(ifvg_signals) == 1
    s = ifvg_signals[0]
    assert s.index == 18
    assert s.type == SignalType.SELL   # bullish FVG asagi kirildi -> bearish reversal
    assert s.entry == 101.5             # consequent_encroachment
    assert s.stop_loss == 103.0          # top(102.0) + gap(1.0)*SL_BUFFER_RATIO["ifvg"](1.0)
    assert s.take_profit == pytest.approx(99.25)  # entry - R(1.5)*risk(1.5)
    assert s.breakeven_trigger_pct == 0.5


def test_ob_signal_uses_official_r_multiple_and_sl_buffer():
    # test_order_block.py::test_bullish_order_block_detection ile ayni senaryo.
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]
    impulse = [(99.5, 106.0, 99.4, 105.5)]
    candles = _make_dummy_candles(neutral + last_opposite + impulse)
    signals = generate_signals(candles)

    ob_signals = [s for s in signals if s.setup_type == SetupType.OB_ONLY]
    assert len(ob_signals) == 1
    s = ob_signals[0]
    assert s.index == 14                 # ob.impulse_index -- ob.index DEGIL (bu oturumun kalibrasyonuyla uyumlu)
    assert s.type == SignalType.BUY
    assert s.entry == 100.0               # (top+bottom)/2 = (100.5+99.5)/2
    assert s.stop_loss == 96.5             # bottom(99.5) - govde(1.0)*SL_BUFFER_RATIO["ob"](3.0)
    assert s.take_profit == pytest.approx(110.5)  # entry + R(3.0)*risk(3.5)
    assert s.breakeven_trigger_pct == 0.5


def test_trendline_bounce_signal_breakeven_disabled():
    # test_trendline.py::test_ascending_trendline_validated_on_third_touch
    # tabanini (slope=0.2/bar) genisletip known_index'ten SONRA cizgiye
    # geri donen bir "sicrama" (bounce) mumu ekliyor.
    config = replace(DEFAULT_CONFIG, trendline_swing_lookback=3)
    n = 35
    data = []
    for i in range(n):
        low = 100.0 + 0.5 * i
        high = low + 1.0
        data.append((low + 0.3, high, low, low + 0.5))
    data[10] = (100.2, 101.0, 100.0, 100.3)
    data[20] = (102.2, 103.0, 102.0, 102.3)
    data[30] = (104.2, 105.0, 104.0, 104.3)
    data.append((105.0, 105.5, 104.8, 105.2))  # idx35 -- cizgiye donus (dokunus)
    candles = _make_dummy_candles(data)

    signals = generate_signals(candles, config=config)
    tl_signals = [s for s in signals if s.setup_type == SetupType.TRENDLINE_ONLY]
    assert len(tl_signals) == 1
    s = tl_signals[0]
    assert s.index == 34                # tetikleme bari (35) - 1 -- ayni barda dolum icin
    assert s.type == SignalType.BUY
    assert s.entry == 104.8              # dokunus barinin (idx35) low'u
    assert s.breakeven_trigger_pct is None  # "trendline" BREAKEVEN_ENABLED_MODULES'ta yok


def test_no_a_plus_signals_ever_generated():
    # Confluence ablation (results/confluence_and_filters/) fayda bulamadi --
    # A+ artik hicbir kosulda uretilmemeli, FVG+OB cakissa bile.
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 13
    last_opposite = [(100.5, 100.8, 99.2, 99.5)]  # OB govdesi [99.5,100.5]
    impulse = [(99.5, 106.0, 99.4, 105.5)]         # ayni zamanda FVG'yi tetikleyen guclu hareket
    tail = [(105.5, 108.0, 104.0, 107.0), (107.0, 110.0, 106.5, 109.0)]
    candles = _make_dummy_candles(neutral + last_opposite + impulse + tail)
    signals = generate_signals(candles)

    assert all(s.setup_type != SetupType.A_PLUS for s in signals)
