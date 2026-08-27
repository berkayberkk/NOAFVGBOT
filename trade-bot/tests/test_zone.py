"""
Alan (Zone) / Katman (Layer) Modülü Birim Testleri (Unit Tests for strategy/zone.py).
"""

from dataclasses import replace
from datetime import datetime, timedelta

from strategy.config import DEFAULT_CONFIG
from strategy.zone import (
    detect_zones,
    classify_katman,
    current_katman,
    mark_zone_reactions,
    Zone,
    ZoneDirection,
    ZoneType,
    Katman,
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


# lookback=1 -> pivot testleri için 3-mumluk pencere yeterli (FVG'nin 3 mumluk
# formasyon presedanıyla aynı ölçekte, çok uzun candle serileri gerektirmez).
_LB1_CONFIG = replace(DEFAULT_CONFIG, zone_swing_lookback=1)


def _base_leg_candles(tail: tuple[float, float, float, float]) -> list[dict]:
    """
    Ortak leg iskeleti: idx0 padding, idx1 LOW pivot (90.0), idx2 mid,
    idx3 HIGH pivot (118.0), idx4 = verilen tail (extend/flip davranışını
    izole etmek için testten teste değişir).
    """
    base = [
        (100.0, 100.5, 99.5, 100.0),   # idx0 padding
        (100.0, 100.2, 90.0, 95.0),    # idx1 LOW pivot
        (95.0, 100.3, 94.0, 96.0),     # idx2 mid
        (96.0, 118.0, 95.5, 117.0),    # idx3 HIGH pivot
    ]
    return _make_dummy_candles(base + [tail])


def test_bootstrap_zone_from_first_two_pivots():
    candles = _base_leg_candles((117.0, 110.0, 106.0, 108.0))  # high<118 no extend, low>104 no flip
    zones = detect_zones(candles, config=_LB1_CONFIG)

    assert len(zones) == 1
    zone = zones[0]
    assert zone.zone_type == ZoneType.N
    assert zone.direction == ZoneDirection.BULLISH
    assert zone.start_index == 1
    assert zone.start_price == 90.0
    assert zone.extreme_index == 3
    assert zone.extreme_price == 118.0
    assert zone.flip_reason is None


def test_active_zone_extreme_extends_with_new_highs():
    base = [
        (100.0, 100.5, 99.5, 100.0),
        (100.0, 100.2, 90.0, 95.0),
        (95.0, 100.3, 94.0, 96.0),
        (96.0, 118.0, 95.5, 117.0),
        (117.0, 110.0, 106.0, 108.0),   # no extend, no flip
        (108.0, 125.0, 115.0, 124.0),   # yeni tepe -- extreme 125'e genişlemeli
    ]
    candles = _make_dummy_candles(base)
    zones = detect_zones(candles, config=_LB1_CONFIG)

    assert len(zones) == 1
    zone = zones[0]
    assert zone.extreme_index == 5
    assert zone.extreme_price == 125.0


def test_kural1_flip_on_wick_touch_no_close_required():
    # level_50 = 90 + 0.5*(118-90) = 104. Fitil 100'e kadar iniyor (<=104)
    # ama kapanış 110 -- kapanış şartı olmadan yine de flip olmalı.
    candles = _base_leg_candles((117.0, 105.0, 100.0, 110.0))
    zones = detect_zones(candles, config=_LB1_CONFIG)

    assert len(zones) == 2
    assert zones[0].zone_type == ZoneType.O
    assert zones[0].flip_reason == "kural1"
    assert zones[0].extreme_price == 118.0  # tail bar extend etmedi (105 < 118)


def test_kural1_no_flip_when_050_not_reached():
    # level_50 = 104. Fitil 104.1'de kalıyor -- 0.50 kırılmıyor.
    candles = _base_leg_candles((102.0, 108.0, 104.1, 107.0))
    zones = detect_zones(candles, config=_LB1_CONFIG)

    assert len(zones) == 1
    assert zones[0].zone_type == ZoneType.N


def test_new_zone_starts_at_old_zone_extreme():
    candles = _base_leg_candles((117.0, 105.0, 100.0, 110.0))
    zones = detect_zones(candles, config=_LB1_CONFIG)

    assert len(zones) == 2
    old, new = zones[0], zones[1]
    assert new.start_index == old.extreme_index
    assert new.start_price == old.extreme_price
    assert new.direction == ZoneDirection.BEARISH  # eski BULLISH'in tersi
    assert new.extreme_price == 100.0  # flip barının low'undan tohumlandı


def test_narrow_zone_marked_invalid():
    config = replace(_LB1_CONFIG, atr_period=1, zone_min_size_atr_ratio=3.0)
    candles = _base_leg_candles((117.0, 110.0, 106.0, 108.0))
    zones = detect_zones(candles, config=config)

    assert len(zones) == 1
    assert zones[0].valid is False
    assert "dar alan" in zones[0].invalid_reason


def test_wide_zone_marked_valid():
    config = replace(_LB1_CONFIG, atr_period=1, zone_min_size_atr_ratio=3.0)
    base = [
        (100.0, 100.5, 99.5, 100.0),
        (100.0, 100.2, 90.0, 95.0),
        (95.0, 100.3, 94.0, 96.0),
        (96.0, 200.0, 95.5, 117.0),      # HIGH pivot çok daha uzakta (200)
        (190.0, 195.0, 150.0, 192.0),    # extend yok (195<200), flip yok (150 > level_50=145)
    ]
    candles = _make_dummy_candles(base)
    zones = detect_zones(candles, config=config)

    assert len(zones) == 1
    assert zones[0].valid is True


def test_classify_katman_boundaries():
    zone = Zone(start_index=0, start_price=100.0, extreme_index=10, extreme_price=200.0,
                direction=ZoneDirection.BULLISH, zone_type=ZoneType.O)

    assert classify_katman(zone, 100.0) == Katman.K1   # fraction 0.00
    assert classify_katman(zone, 124.0) == Katman.K1   # fraction 0.24
    assert classify_katman(zone, 125.0) == Katman.K2   # fraction 0.25
    assert classify_katman(zone, 149.0) == Katman.K2   # fraction 0.49
    assert classify_katman(zone, 150.0) == Katman.K3   # fraction 0.50
    assert classify_katman(zone, 174.0) == Katman.K3   # fraction 0.74
    assert classify_katman(zone, 175.0) == Katman.K4   # fraction 0.75
    assert classify_katman(zone, 200.0) == Katman.K4   # fraction 1.00
    assert classify_katman(zone, 99.0) is None          # aralık dışı (altında)
    assert classify_katman(zone, 201.0) is None         # aralık dışı (üstünde)


def test_classify_katman_bearish_direction():
    # start=200 (origin/tepe), extreme=100 (dip) -- 0=200'e yakın, 1=100'e yakın.
    zone = Zone(start_index=0, start_price=200.0, extreme_index=10, extreme_price=100.0,
                direction=ZoneDirection.BEARISH, zone_type=ZoneType.O)

    assert classify_katman(zone, 200.0) == Katman.K1   # fraction 0.00
    assert classify_katman(zone, 175.0) == Katman.K2   # fraction 0.25
    assert classify_katman(zone, 150.0) == Katman.K3   # fraction 0.50
    assert classify_katman(zone, 125.0) == Katman.K4   # fraction 0.75
    assert classify_katman(zone, 100.0) == Katman.K4   # fraction 1.00


def test_current_katman_finds_most_recent_frozen_zone():
    zone_old = Zone(start_index=0, start_price=100.0, extreme_index=5, extreme_price=200.0,
                     direction=ZoneDirection.BULLISH, zone_type=ZoneType.O)
    zone_new = Zone(start_index=5, start_price=200.0, extreme_index=10, extreme_price=150.0,
                     direction=ZoneDirection.BEARISH, zone_type=ZoneType.O)
    zone_active = Zone(start_index=10, start_price=150.0, extreme_index=12, extreme_price=155.0,
                        direction=ZoneDirection.BULLISH, zone_type=ZoneType.N)
    zones = [zone_old, zone_new, zone_active]

    candles = _make_dummy_candles([(100.0, 101.0, 99.0, 100.0)] * 12 + [(190.0, 196.0, 189.0, 195.0)])

    result = current_katman(12, candles, zones)

    assert result is not None
    zone, katman = result
    assert zone is zone_new
    assert katman == Katman.K1  # fraction (195-200)/(150-200) = 0.1


def test_current_katman_none_before_any_frozen_zone():
    zone_active = Zone(start_index=0, start_price=100.0, extreme_index=5, extreme_price=150.0,
                        direction=ZoneDirection.BULLISH, zone_type=ZoneType.N)
    candles = _make_dummy_candles([(100.0, 101.0, 99.0, 100.0)] * 6)

    assert current_katman(5, candles, [zone_active]) is None
    assert current_katman(5, candles, []) is None


def test_mark_zone_reactions_classifies_next_zone_extreme():
    zone1 = Zone(start_index=0, start_price=100.0, extreme_index=5, extreme_price=200.0,
                 direction=ZoneDirection.BULLISH, zone_type=ZoneType.O)
    zone2 = Zone(start_index=5, start_price=200.0, extreme_index=10, extreme_price=150.0,
                 direction=ZoneDirection.BEARISH, zone_type=ZoneType.O)

    mark_zone_reactions([zone1, zone2])

    assert zone1.first_reaction_katman == Katman.K3  # fraction (150-100)/100 = 0.50
    assert zone1.first_reaction_index == 10
    assert zone1.first_reaction_price == 150.0


def test_mark_zone_reactions_pending_when_next_zone_still_active():
    zone1 = Zone(start_index=0, start_price=100.0, extreme_index=5, extreme_price=200.0,
                 direction=ZoneDirection.BULLISH, zone_type=ZoneType.O)
    zone2 = Zone(start_index=5, start_price=200.0, extreme_index=10, extreme_price=150.0,
                 direction=ZoneDirection.BEARISH, zone_type=ZoneType.N)

    mark_zone_reactions([zone1, zone2])

    assert zone1.first_reaction_katman is None
    assert zone1.first_reaction_index is None


def test_too_few_pivots_returns_empty_list():
    # idx1 (tek kontrol edilen index, lb=1) ne swing high ne swing low --
    # window'un ne max'ı ne min'i onun değeri (tam ortada) -- 0 pivot bulunur.
    candles = _make_dummy_candles([
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 100.5, 99.5, 100.0),
        (100.0, 101.0, 99.0, 100.0),
    ])
    assert detect_zones(candles, config=_LB1_CONFIG) == []


def test_alternating_pivot_collapse_keeps_more_extreme():
    # idx1 ve idx3 ARDIŞIK iki HIGH pivotu (aralarında LOW yok) -- collapse
    # bunları en yükseği (idx3=115) tutarak birleştirmeli. idx5 tek LOW pivotu.
    # Collapse OLMASAYDI bootstrap yanlışlıkla (idx1=110,HIGH) + (idx3=115,HIGH)
    # çiftini kullanır, tutarsız bir BULLISH zone (start=110,extreme=115) üretirdi.
    base = [
        (95.0, 101.0, 90.0, 100.0),    # idx0 padding
        (100.0, 110.0, 89.0, 105.0),   # idx1 HIGH A
        (100.0, 103.0, 88.0, 101.0),   # idx2 mid
        (100.0, 115.0, 87.0, 110.0),   # idx3 HIGH B (daha yüksek)
        (95.0, 104.0, 86.0, 100.0),    # idx4 mid
        (90.0, 92.0, 70.0, 85.0),      # idx5 LOW
        (85.0, 90.0, 80.0, 88.0),      # idx6 padding
    ]
    candles = _make_dummy_candles(base)
    zones = detect_zones(candles, config=_LB1_CONFIG)

    assert len(zones) == 1
    zone = zones[0]
    assert zone.start_index == 3
    assert zone.start_price == 115.0
    assert zone.direction == ZoneDirection.BEARISH
    assert zone.extreme_index == 5
    assert zone.extreme_price == 70.0
