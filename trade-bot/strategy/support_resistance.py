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


from strategy.config import DEFAULT_CONFIG, StrategyConfig

# --- Kalibre edilecek parametreler ---
SWING_LOOKBACK = DEFAULT_CONFIG.swing_lookback
TOLERANCE_ATR_RATIO = DEFAULT_CONFIG.tolerance_atr_ratio


def find_swing_points(candles: list[dict], lookback: int = SWING_LOOKBACK, config: StrategyConfig | None = None) -> tuple[list[int], list[int]]:
    """
    Swing high ve swing low index'lerini bulur.
    """
    lb = config.swing_lookback if config is not None else lookback
    highs: list[int] = []
    lows: list[int] = []
    n = len(candles)

    for i in range(lb, n - lb):
        window = candles[i - lb: i + lb + 1]
        if candles[i]["high"] == max(c["high"] for c in window):
            highs.append(i)
        if candles[i]["low"] == min(c["low"] for c in window):
            lows.append(i)

    return highs, lows


from dataclasses import replace


def build_levels(candles: list[dict], config: StrategyConfig = DEFAULT_CONFIG,
                 tolerance_atr_ratio: float | None = None, lookback: int | None = None) -> list[Level]:
    """
    Swing noktalarını kümeleyerek destek/direnç seviyeleri oluşturur.
    """
    if tolerance_atr_ratio is not None or lookback is not None:
        t = tolerance_atr_ratio if tolerance_atr_ratio is not None else config.tolerance_atr_ratio
        lb = lookback if lookback is not None else config.swing_lookback
        config = replace(config, tolerance_atr_ratio=t, swing_lookback=lb)
    atr_series = compute_atr_series(candles, config.atr_period)
    swing_highs, swing_lows = find_swing_points(candles, config=config)
    levels: list[Level] = []

    def _cluster(indices: list[int], level_type: LevelType, price_key: str) -> None:
        for i in indices:
            price = candles[i][price_key]
            atr = atr_series[i] or 0
            tolerance = atr * config.tolerance_atr_ratio

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
