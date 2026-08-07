"""
Trend modülü.

Kurallar: hem HH/HL (higher high / higher low, ya da tam tersi) yapısı
hem hareketli ortalama (EMA) pozisyonu birlikte kullanılıyor.
- HH/HL yapısı: art arda gelen swing high/low'lar yükseliyorsa UP,
  düşüyorsa DOWN, karışıksa SIDEWAYS.
- EMA: kapanış fiyatı EMA'nın üstündeyse bullish taraf, altındaysa
  bearish taraf; bu, HH/HL sinyalini teyit etmek için kullanılır.
"""

from dataclasses import dataclass
from enum import Enum

from strategy.support_resistance import find_swing_points


class TrendDirection(Enum):
    UP = "up"
    DOWN = "down"
    SIDEWAYS = "sideways"


@dataclass
class TrendState:
    index: int
    direction: TrendDirection        # HH/HL yapısına göre yön
    ema_aligned: bool                 # fiyat EMA'nın yapıyla aynı tarafında mı
    strong: bool                       # yön + EMA teyidi ikisi de aynı yöndeyse True

from strategy.config import DEFAULT_CONFIG, StrategyConfig

EMA_PERIOD = DEFAULT_CONFIG.ema_period


def compute_ema_series(candles: list[dict], period: int = EMA_PERIOD) -> list[float | None]:
    """Basit EMA hesabı. İlk `period` mum için None döner (henüz veri yetersiz)."""
    ema: list[float | None] = [None] * len(candles)
    multiplier = 2 / (period + 1)

    for i, c in enumerate(candles):
        if i < period - 1:
            continue
        if i == period - 1:
            window = candles[0:period]
            ema[i] = sum(x["close"] for x in window) / period
        else:
            ema[i] = (c["close"] - ema[i - 1]) * multiplier + ema[i - 1]

    return ema


def detect_trend(candles: list[dict], lookback: int = 5, ema_period: int = EMA_PERIOD) -> list[TrendState]:
    """
    Her mum için o ana kadarki trend durumunu hesaplar.

    Mantık: her mumda, o ana kadar oluşmuş son 2 swing high ve son 2
    swing low karşılaştırılır:
      - son high > önceki high VE son low > önceki low  -> UP
      - son high < önceki high VE son low < önceki low  -> DOWN
      - aksi halde                                        -> SIDEWAYS
    Sonra kapanış fiyatının EMA'ya göre pozisyonu bu yönle karşılaştırılıp
    `ema_aligned` ve `strong` alanları belirlenir.
    """
    swing_highs, swing_lows = find_swing_points(candles, lookback)
    ema_series = compute_ema_series(candles, ema_period)

    states: list[TrendState] = []

    for i, candle in enumerate(candles):
        recent_highs = [candles[idx]["high"] for idx in swing_highs if idx <= i][-2:]
        recent_lows = [candles[idx]["low"] for idx in swing_lows if idx <= i][-2:]

        direction = TrendDirection.SIDEWAYS
        if len(recent_highs) == 2 and len(recent_lows) == 2:
            if recent_highs[1] > recent_highs[0] and recent_lows[1] > recent_lows[0]:
                direction = TrendDirection.UP
            elif recent_highs[1] < recent_highs[0] and recent_lows[1] < recent_lows[0]:
                direction = TrendDirection.DOWN

        ema = ema_series[i]
        ema_aligned = False
        if ema is not None:
            if direction == TrendDirection.UP and candle["close"] > ema:
                ema_aligned = True
            elif direction == TrendDirection.DOWN and candle["close"] < ema:
                ema_aligned = True

        strong = direction != TrendDirection.SIDEWAYS and ema_aligned

        states.append(TrendState(index=i, direction=direction, ema_aligned=ema_aligned, strong=strong))

    return states
