"""
Order Block (OB) tespit modülü.

Kurallar (kullanıcının kendi tanımına göre, PDF kaynağı yok):
- Order block, güçlü hareketi BAŞLATAN mumun kendisidir (klasik ICT
  tanımındaki "son zıt mum" değil — burada mumun kendisi OB sayılıyor).
- "Güçlü hareket", mumun boyu (high-low aralığı) son N mumun ortalama
  boyundan belirgin şekilde büyükse anlaşılıyor.
- Order block'un bölgesi, o mumun tüm high-low aralığıdır.
- Yön: mum yükselişte kapandıysa (close > open) bullish OB, düşüşte
  kapandıysa (close < open) bearish OB.
- Geçersizlik: fiyat bölgeyi tamamen geçip kapanış verirse (bullish OB
  için bir mumun close'u OB'nin altına, bearish OB için üstüne
  geçerse) order block geçersiz sayılır.
"""

from dataclasses import dataclass
from enum import Enum


class OBDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class OrderBlock:
    index: int                     # order block mumunun index'i
    top: float
    bottom: float
    direction: OBDirection
    mitigated: bool = False         # fiyat bu bölgeyi tamamen geçip geçersiz kıldı mı
    mitigated_index: int | None = None


from strategy.config import DEFAULT_CONFIG, StrategyConfig

# --- Kalibre edilecek parametreler ---
AVG_RANGE_PERIOD = DEFAULT_CONFIG.avg_range_period
STRONG_MOVE_RATIO = DEFAULT_CONFIG.strong_move_ratio


def _average_range_series(candles: list[dict], period: int) -> list[float | None]:
    """Her mum için, kendisinden önceki `period` mumun ortalama high-low aralığını döner."""
    ranges = [c["high"] - c["low"] for c in candles]
    result: list[float | None] = [None] * len(candles)

    for i in range(len(candles)):
        if i < period:
            continue
        window = ranges[i - period:i]  # kendisi dahil değil, öncesindeki mumlar
        result[i] = sum(window) / period

    return result


from dataclasses import replace


def detect_order_blocks(candles: list[dict], config: StrategyConfig = DEFAULT_CONFIG,
                        period: int | None = None, strong_move_ratio: float | None = None) -> list[OrderBlock]:
    """
    Verilen mum listesinden order block'ları tespit eder.
    """
    if period is not None or strong_move_ratio is not None:
        p = period if period is not None else config.avg_range_period
        sm = strong_move_ratio if strong_move_ratio is not None else config.strong_move_ratio
        config = replace(config, avg_range_period=p, strong_move_ratio=sm)
    avg_ranges = _average_range_series(candles, config.avg_range_period)
    blocks: list[OrderBlock] = []

    for i, candle in enumerate(candles):
        avg_range = avg_ranges[i]
        if avg_range is None or avg_range == 0:
            continue

        candle_range = candle["high"] - candle["low"]
        if candle_range < avg_range * config.strong_move_ratio:
            continue  # yeterince güçlü değil

        direction = OBDirection.BULLISH if candle["close"] > candle["open"] else OBDirection.BEARISH

        blocks.append(OrderBlock(
            index=i,
            top=candle["high"],
            bottom=candle["low"],
            direction=direction,
        ))

    return blocks


def mark_mitigated_blocks(blocks: list[OrderBlock], candles: list[dict]) -> list[OrderBlock]:
    """
    Her order block için, sonraki mumlardan biri bölgeyi tamamen geçip
    ters yönde kapanış verdiyse mitigated=True işaretler (kuralın adı
    "mitigated" ama burada tam karşılığı "geçersiz" = tamamen kırıldı).
    """
    for block in blocks:
        for j in range(block.index + 1, len(candles)):
            candle = candles[j]
            if block.direction == OBDirection.BULLISH and candle["close"] < block.bottom:
                block.mitigated = True
                block.mitigated_index = j
                break
            if block.direction == OBDirection.BEARISH and candle["close"] > block.top:
                block.mitigated = True
                block.mitigated_index = j
                break

    return blocks
