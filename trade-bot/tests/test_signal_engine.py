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


def _make_dummy_candles(ohlc_list: list[tuple[float, float, float, float]], volumes=None) -> list[dict]:
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    candles = []
    for i, (o, h, l, c) in enumerate(ohlc_list):
        candles.append({
            "time": base_time + timedelta(minutes=30 * i),
            "open": o, "high": h, "low": l, "close": c,
            "tick_volume": volumes[i] if volumes else 100, "spread": 10,
        })
    return candles


def test_fvg_signal_uses_official_r_multiple_and_sl_buffer():
    # test_fvg.py::test_bullish_fvg_detection ile ayni FVG (top=102.0, bottom=101.0).
    # 20 notr mum (volume_confirm_period=20 icin yeterli gecmis) + orta mumda
    # (idx21) hacim patlamasi -- signal_engine artik FVG'de volume_confirmed
    # sarti uyguluyor (2026-09-03), aksi halde sinyal 0'a elenir.
    neutral = [(100.0, 101.0, 99.0, 100.0)] * 20
    fvg = [
        (100.0, 101.0, 99.0, 100.5),
        (101.0, 103.0, 100.5, 102.8),
        (102.8, 104.0, 102.0, 103.5),
    ]
    volumes = [100] * 20 + [100, 500, 100]
    candles = _make_dummy_candles(neutral + fvg, volumes=volumes)
    signals = generate_signals(candles)

    fvg_signals = [s for s in signals if s.setup_type == SetupType.FVG_ONLY]
    assert len(fvg_signals) == 1
    s = fvg_signals[0]
    assert s.index == 22
    assert s.type == SignalType.BUY
    assert s.confidence == Confidence.MEDIUM
    assert s.entry == 102.0            # sig/yakin kenar (top) -- 2026-09-03 giris derinligi bulgusu
    assert s.stop_loss == 86.0         # bottom(101.0) - gap(1.0)*SL_BUFFER_RATIO["fvg"](15.0, 2026-09-03 Aday 6 holdout ile benimsendi) -- SL hala uzak kenara gore
    assert s.take_profit == pytest.approx(126.0)  # entry(102.0) + R(1.5)*risk(16.0)
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
    assert s.stop_loss == 117.0          # top(102.0) + gap(1.0)*SL_BUFFER_RATIO["ifvg"](15.0, 2026-09-03 Aday 7 holdout ile benimsendi)
    assert s.take_profit == pytest.approx(78.25)  # entry(101.5) - R(1.5)*risk(15.5)
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
    assert s.entry == 100.5                # sig/yakin kenar (top) -- 2026-09-03 giris derinligi bulgusu
    assert s.stop_loss == 69.5             # bottom(99.5) - govde(1.0)*SL_BUFFER_RATIO["ob"](30.0, 2026-09-03 Aday 6 holdout ile benimsendi)
    assert s.take_profit == pytest.approx(193.5)  # entry(100.5) + R(3.0)*risk(31.0)
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
