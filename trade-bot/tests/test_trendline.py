"""
Trendline Modülü Birim Testleri (Unit Tests for strategy/trendline.py).
"""

from datetime import datetime, timedelta
from dataclasses import replace

from strategy.trendline import detect_trendlines, detect_trendline_reversals, TrendlineDirection
from strategy.config import DEFAULT_CONFIG

CONFIG = replace(DEFAULT_CONFIG, trendline_swing_lookback=3)


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


def _ascending_base(n: int = 35) -> list[tuple[float, float, float, float]]:
    # Arka plan mumlari, egimi (0.5/bar) test trendline'inin kendi
    # egiminden (0.2/bar) BILEREK dik tutuluyor -- boylece formul-bazli
    # mumlar hicbir zaman cizgiyi ihlal etmiyor, sadece 10/20/30 index'lerine
    # yerlestirilen ust-uste binen dip'ler cizgiye tam dokunuyor.
    data = []
    for i in range(n):
        low = 100.0 + 0.5 * i
        high = low + 1.0
        data.append((low + 0.3, high, low, low + 0.5))
    data[10] = (100.2, 101.0, 100.0, 100.3)   # 1. dokunus
    if n > 20:
        data[20] = (102.2, 103.0, 102.0, 102.3)  # 2. dokunus
    if n > 30:
        data[30] = (104.2, 105.0, 104.0, 104.3)  # 3. dokunus (dogrulama)
    return data


def _descending_base(n: int = 35) -> list[tuple[float, float, float, float]]:
    data = []
    for i in range(n):
        high = 200.0 - 0.5 * i
        low = high - 1.0
        data.append((high - 0.3, high, low, high - 0.5))
    data[10] = (199.8, 200.0, 199.0, 199.7)
    if n > 20:
        data[20] = (197.8, 198.0, 197.0, 197.7)
    if n > 30:
        data[30] = (195.8, 196.0, 195.0, 195.7)
    return data


def test_ascending_trendline_validated_on_third_touch():
    candles = _make_dummy_candles(_ascending_base())
    lines = detect_trendlines(candles, config=CONFIG)
    asc = [l for l in lines if l.direction == TrendlineDirection.ASCENDING]

    assert len(asc) == 1
    tl = asc[0]
    assert tl.anchor_indices == [10, 20, 30]
    assert tl.validated_index == 30
    assert tl.touch_count == 3
    assert abs(tl.slope - 0.2) < 1e-9
    assert abs(tl.intercept - 98.0) < 1e-9
    assert tl.broken is False


def test_known_index_lags_validated_index_by_swing_lookback():
    # KRITIK (causal): validated_index'in kendisi bir swing noktasi --
    # find_swing_points bunu ancak SONRASINDAKI lookback kadar mumu da
    # gorunce onaylayabiliyor. known_index bu gecikmeyi yansitmali,
    # yoksa dokunus/kirilma barinin KENDI fiyati SL olarak kullanildiginda
    # gelecek bilgisi sizdirir (bkz. git log -- Trendline TP/SL calismasi
    # kalibrasyonunda bulunan lookahead bug, 2026-09-01).
    candles = _make_dummy_candles(_ascending_base())
    lines = detect_trendlines(candles, config=CONFIG)
    tl = [l for l in lines if l.direction == TrendlineDirection.ASCENDING][0]
    assert tl.swing_lookback == 3
    assert tl.known_index == tl.validated_index + 3 == 33


def test_descending_trendline_validated_on_third_touch():
    candles = _make_dummy_candles(_descending_base())
    lines = detect_trendlines(candles, config=CONFIG)
    desc = [l for l in lines if l.direction == TrendlineDirection.DESCENDING]

    assert len(desc) == 1
    tl = desc[0]
    assert tl.anchor_indices == [10, 20, 30]
    assert tl.validated_index == 30
    assert abs(tl.slope - (-0.2)) < 1e-9
    assert tl.broken is False


def test_two_touches_not_validated():
    # 3. dokunus (idx 30) icin yeterli mum yok -- sadece 2 dokunus (10, 20)
    # gerceklesebiliyor, cizgi hic dogrulanmamali.
    candles = _make_dummy_candles(_ascending_base(n=26))
    lines = detect_trendlines(candles, config=CONFIG)
    asc = [l for l in lines if l.direction == TrendlineDirection.ASCENDING]
    assert asc == []


def test_trendline_breaks_on_close_beyond_line():
    data = _ascending_base(n=35)
    data[34] = (104.0, 104.2, 102.0, 103.0)  # kapanis (103.0) < line_price(34)=104.8
    candles = _make_dummy_candles(data)
    lines = detect_trendlines(candles, config=CONFIG)
    asc = [l for l in lines if l.direction == TrendlineDirection.ASCENDING]

    assert len(asc) == 1
    assert asc[0].broken is True
    assert asc[0].broken_index == 34


def test_wick_below_line_does_not_break():
    data = _ascending_base(n=35)
    # fitil (low=102.0) cizginin altina iner ama kapanis (104.9) line_price(34)=104.8'in USTUNDE kalir
    data[34] = (104.9, 105.0, 102.0, 104.9)
    candles = _make_dummy_candles(data)
    lines = detect_trendlines(candles, config=CONFIG)
    asc = [l for l in lines if l.direction == TrendlineDirection.ASCENDING]

    assert len(asc) == 1
    assert asc[0].broken is False
    assert asc[0].broken_index is None


def test_bearish_reversal_after_ascending_line_breaks_down():
    # ascending (destek) cizgi asagi kirilir (idx 34), sonra fiyat cizgiye
    # GERI DONUP (idx 35) YUKARIDAN dokunur ve reddedip (kapanis cizginin
    # altinda kalir) asagi devam eder -- SHORT reversal sinyali beklenir.
    data = _ascending_base(n=36)
    data[34] = (104.0, 104.2, 102.0, 103.0)   # kirilma: kapanis(103.0) < line_price(34)=104.8
    data[35] = (103.0, 105.0, 102.5, 103.5)   # retest: high(105.0) >= line_price(35)=105.0, kapanis(103.5) < 105.0 -- reddiye
    candles = _make_dummy_candles(data)
    lines = detect_trendlines(candles, config=CONFIG)
    asc = [l for l in lines if l.direction == TrendlineDirection.ASCENDING]
    assert asc[0].broken is True

    reversals = detect_trendline_reversals(candles, lines, config=CONFIG)
    assert len(reversals) == 1
    rev = reversals[0]
    assert rev.is_bullish is False
    assert rev.retest_index == 35
    assert abs(rev.entry_price - 105.0) < 1e-9


def test_bullish_reversal_after_descending_line_breaks_up():
    data = _descending_base(n=36)
    data[34] = (196.0, 196.5, 195.5, 196.0)   # kirilma: kapanis(196.0) > line_price(34)=195.2
    data[35] = (195.5, 196.0, 194.8, 195.8)   # retest: low(194.8) <= line_price(35)=195.0, kapanis(195.8) > 195.0 -- reddiye
    candles = _make_dummy_candles(data)
    lines = detect_trendlines(candles, config=CONFIG)
    desc = [l for l in lines if l.direction == TrendlineDirection.DESCENDING]
    assert desc[0].broken is True

    reversals = detect_trendline_reversals(candles, lines, config=CONFIG)
    assert len(reversals) == 1
    rev = reversals[0]
    assert rev.is_bullish is True
    assert rev.retest_index == 35
    assert abs(rev.entry_price - 195.0) < 1e-9


def test_reclaim_on_first_retest_touch_produces_no_reversal():
    # kirildiktan sonra ilk temas REDDETMEZ (kapanis eski bolgeye geri
    # doner/reclaim eder) -- iFVG'deki "ilk temas reddetmezse sinyal
    # olusmaz" kuraliyla ayni, reversal sinyali UretilMEMELI.
    data = _ascending_base(n=36)
    data[34] = (104.0, 104.2, 102.0, 103.0)   # kirilma
    data[35] = (103.0, 105.0, 102.5, 105.5)   # retest ama kapanis (105.5) line_price(35)=105.0'in USTUNE geri donuyor (reclaim)
    candles = _make_dummy_candles(data)
    lines = detect_trendlines(candles, config=CONFIG)

    reversals = detect_trendline_reversals(candles, lines, config=CONFIG)
    assert reversals == []
