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


# --- Kalibre edilecek parametreler ---
AVG_RANGE_PERIOD = 14

# Bir mumun "güçlü hareket" sayılması için, boyunun son AVG_RANGE_PERIOD
# mumun ortalama boyundan kaç kat büyük olması gerektiği. VARSAYIM —
# gerçek veride örnekleri gözden geçirip birlikte kalibre edeceğiz.
STRONG_MOVE_RATIO = 2.0


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


def detect_order_blocks(candles: list[dict], period: int = AVG_RANGE_PERIOD,
                         strong_move_ratio: float = STRONG_MOVE_RATIO) -> list[OrderBlock]:
    """
    Verilen mum listesinden order block'ları tespit eder.

    Parametreler
    ----------
    candles : {"open","high","low","close",...} anahtarlı mum listesi.
    period : ortalama mum boyu hesaplanırken kaç mumluk pencereye bakılacağı.
    strong_move_ratio : bir mumun "güçlü" sayılması için ortalamanın kaç katı
                        olması gerektiği.

    Dönüş
    -----
    list[OrderBlock] : tespit edilen tüm order block'lar (mitigasyon durumu
                        henüz kontrol edilmemiş halde — bkz. mark_mitigated_blocks).
    """
    avg_ranges = _average_range_series(candles, period)
    blocks: list[OrderBlock] = []

    for i, candle in enumerate(candles):
        avg_range = avg_ranges[i]
        if avg_range is None or avg_range == 0:
            continue

        candle_range = candle["high"] - candle["low"]
        if candle_range < avg_range * strong_move_ratio:
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
