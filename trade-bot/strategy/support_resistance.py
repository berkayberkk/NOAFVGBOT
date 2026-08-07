"""
Destek / Direnç seviyesi tespit modülü.

Kurallar (kullanıcının kendi tanımı): swing high/low noktaları bulunur,
birbirine yakın (ATR toleransı içinde) olan swing noktaları tek bir
seviyede kümelenir. Bir seviyeye ne kadar çok dokunulmuşsa (touch_count)
o kadar güçlü kabul edilir.
"""

from dataclasses import dataclass
from enum import Enum

from strategy.fvg import compute_atr_series


class LevelType(Enum):
    SUPPORT = "support"
    RESISTANCE = "resistance"


@dataclass
class Level:
    price: float
    type: LevelType
    touch_count: int = 1
    first_index: int = 0
    last_index: int = 0


# --- Kalibre edilecek parametreler ---
SWING_LOOKBACK = 5           # swing noktası için her iki yanda kaç muma bakılacak
TOLERANCE_ATR_RATIO = 0.5    # iki nokta aynı seviye sayılsın diye ATR'nin kaç katı yakın olmalı (VARSAYIM)


def find_swing_points(candles: list[dict], lookback: int = SWING_LOOKBACK) -> tuple[list[int], list[int]]:
    """
    Swing high ve swing low index'lerini bulur.
    Bir mum, kendisinden önceki ve sonraki `lookback` mum içinde en yüksek
    (veya en düşük) ise swing noktası sayılır.

    Dönüş: (swing_high_indices, swing_low_indices)
    """
    highs: list[int] = []
    lows: list[int] = []
    n = len(candles)

    for i in range(lookback, n - lookback):
        window = candles[i - lookback: i + lookback + 1]
        if candles[i]["high"] == max(c["high"] for c in window):
            highs.append(i)
        if candles[i]["low"] == min(c["low"] for c in window):
            lows.append(i)

    return highs, lows


def build_levels(candles: list[dict], tolerance_atr_ratio: float = TOLERANCE_ATR_RATIO,
                  lookback: int = SWING_LOOKBACK) -> list[Level]:
    """
    Swing noktalarını kümeleyerek destek/direnç seviyeleri oluşturur.
    Her yeni swing noktası, mevcut seviyelerden birine (ATR toleransı
    içindeyse) eklenir; değilse yeni bir seviye açılır.
    """
    atr_series = compute_atr_series(candles)
    swing_highs, swing_lows = find_swing_points(candles, lookback)
    levels: list[Level] = []

    def _cluster(indices: list[int], level_type: LevelType, price_key: str) -> None:
        for i in indices:
            price = candles[i][price_key]
            atr = atr_series[i] or 0
            tolerance = atr * tolerance_atr_ratio

            matched = None
            for lvl in levels:
                if lvl.type == level_type and abs(lvl.price - price) <= tolerance:
                    matched = lvl
                    break

            if matched:
                # seviyeyi yeni dokunuşun ortalamasıyla güncelle
                matched.price = (matched.price * matched.touch_count + price) / (matched.touch_count + 1)
                matched.touch_count += 1
                matched.last_index = i
            else:
                levels.append(Level(price=price, type=level_type, touch_count=1,
                                     first_index=i, last_index=i))

    _cluster(swing_highs, LevelType.RESISTANCE, "high")
    _cluster(swing_lows, LevelType.SUPPORT, "low")

    return levels
