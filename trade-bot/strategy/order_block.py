"""
Order Block (OB) tespit modülü.

DÜZELTME (2026-08-31): Bu modül önceden "kullanıcının kendi tanımı" adı
altında, güçlü hareketi BAŞLATAN mumun kendisini OB sayıyordu -- bu,
FVG/iFVG'de izlenen yöntemle (derin araştırma + gerçek trade örneğiyle
doğrulama) kontrol edildiğinde standart tanımdan saptığı görüldü.
Kaynak: LuxAlgo, ICTKillzone, InnerCircleTrader, TradingWyckoff, ATAS
(bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md "Order Block" bölümü) -- hepsi
aynı tanımda hemfikir:

- Order Block, güçlü hareketten (displacement) HEMEN ÖNCEKİ SON ZIT
  YÖNLÜ mumdur -- hareketi başlatan mumun KENDİSİ DEĞİL.
- Bullish OB: güçlü YÜKSELİŞ hareketinden önceki son DÜŞÜŞ mumu.
  Bearish OB: güçlü DÜŞÜŞ hareketinden önceki son YÜKSELİŞ mumu.
- Bölge, o mumun SADECE GÖVDESİYLE sınırlıdır (open-close arası) --
  fitil dahil tüm high-low aralığı değil.
- "Güçlü hareket" (displacement), impuls mumun boyu (high-low aralığı)
  son N mumun ortalama boyundan belirgin şekilde büyükse anlaşılıyor
  (bu kısım değişmedi).
- Geçersizlik (mitigation): fiyat bölgeyi tamamen geçip KAPANIŞ
  verirse (fitille değmek yetmez) order block geçersiz sayılır (bu
  kural zaten koddaki gibiydi, değişmedi).

Bilinçli olarak kapsam dışı bırakılanlar (FVG/iFVG'deki gibi, önce
temel tanımı test edip sonra ampirik olarak filtre eklemek için):
likidite süpürmesi şartı, engulfing şartı, HTF premium/discount uyumu,
Breaker/Mitigation Block ayrımı. Bunlar ayrı bir çalışmada eklenecek.
"""

from dataclasses import dataclass
from enum import Enum


class OBDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class OrderBlock:
    index: int                     # OB mumunun (son zıt mumun) index'i -- impuls mumunun değil
    impulse_index: int              # OB'yi doğrulayan displacement mumunun index'i
    top: float                      # mumun GÖVDESİNİN üst sınırı (max(open,close))
    bottom: float                   # mumun GÖVDESİNİN alt sınırı (min(open,close))
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


def _candle_direction(candle: dict) -> OBDirection | None:
    """Mumun kendi rengi -- dogu (close==open) ise None (ne bullish ne bearish)."""
    if candle["close"] > candle["open"]:
        return OBDirection.BULLISH
    if candle["close"] < candle["open"]:
        return OBDirection.BEARISH
    return None


def detect_order_blocks(candles: list[dict], config: StrategyConfig = DEFAULT_CONFIG,
                        period: int | None = None, strong_move_ratio: float | None = None) -> list[OrderBlock]:
    """
    Verilen mum listesinden order block'ları tespit eder: her displacement
    (impuls) mumu için, ONDAN HEMEN ÖNCEKİ SON ZIT YÖNLÜ mum OB sayılır --
    impuls mumunun kendisi değil (bkz. modül docstring'i).
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
            continue  # yeterince güçlü değil (displacement yok)

        impulse_dir = _candle_direction(candle)
        if impulse_dir is None:
            continue  # doji impuls mumu -- yön belirsiz

        # Ondan hemen once, impuls ile AYNI yonde olmayan (zit veya doji
        # olmayan) ilk mumu bul -- standart "son zit mum" tanimi.
        ob_index = None
        for j in range(i - 1, -1, -1):
            d = _candle_direction(candles[j])
            if d is not None and d != impulse_dir:
                ob_index = j
                break
            if d == impulse_dir:
                continue  # ayni yonde kucuk bir mum -- atla, geriye bakmaya devam et
        if ob_index is None:
            continue  # veri basinda zit mum bulunamadi

        ob_candle = candles[ob_index]
        top = max(ob_candle["open"], ob_candle["close"])
        bottom = min(ob_candle["open"], ob_candle["close"])
        direction = OBDirection.BULLISH if impulse_dir == OBDirection.BULLISH else OBDirection.BEARISH

        blocks.append(OrderBlock(
            index=ob_index,
            impulse_index=i,
            top=top,
            bottom=bottom,
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
