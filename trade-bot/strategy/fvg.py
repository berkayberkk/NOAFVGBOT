"""
FVG (Fair Value Gap) tespit modülü.

Kurallar (kullanıcının kaynağına göre):
- 3 mumluk yapı, fitiller arası boşluk baz alınır.
- Bullish: 1. mumun üst fitili ile 3. mumun alt fitili arasındaki boşluk.
  Giriş 3. mumun alt fitilinden.
- Bearish: 1. mumun alt fitili ile 3. mumun üst fitili arasındaki boşluk.
  Giriş 3. mumun üst fitilinden.
- Mesafe kuralı: sabit point yerine ATR bazlı ölçüt kullanılıyor —
  boşluk büyüklüğü, o bölgedeki ortalama volatiliteye (ATR) göre çok
  küçük ya da çok büyükse geçersiz sayılır. Böylece kural, piyasa
  sakinken de hareketliyken de kendini otomatik ayarlar.
- Dengesiz FVG: ortadaki mum boşluğa göre çok büyükse geçersiz.
- Multi FVG: yakın/çakışan birden fazla FVG varsa hiçbiri güvenilir sayılmaz.

NOT: "Yüksek Katman FVG" ve "Alanın dibindeki FVG" kuralları, FVG'nin
daha geniş bir hareketin (alan/leg) neresinde oluştuğuna bakıyor —
bu, henüz kodlamadığımız swing/zone yapısına bağlı. O yüzden bu modül
şimdilik sadece geometrik + mesafe + dengesizlik + multi-FVG kurallarını
uyguluyor; katman/alan kuralı ayrı bir modülde (muhtemelen
support_resistance.py ile birlikte) ele alınacak.
"""

from dataclasses import dataclass
from enum import Enum


class FVGDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class FVG:
    start_index: int              # gap'i oluşturan ilk mumun (1. mum) index'i
    end_index: int                 # gap'i oluşturan üçüncü mumun index'i
    top: float                      # gap'in üst sınırı
    bottom: float                   # gap'in alt sınırı
    direction: FVGDirection
    filled: bool = False             # fiyat bu gap'i sonradan doldurdu mu
    valid: bool = True               # tüm geçerlilik kurallarını geçti mi
    invalid_reason: str | None = None  # geçersizse hangi kural yüzünden

    @property
    def entry_price(self) -> float:
        """Kurala göre giriş fiyatı: bullish'te gap'in altı, bearish'te üstü."""
        return self.bottom if self.direction == FVGDirection.BULLISH else self.top


# --- Kalibre edilecek parametreler ---
# ATR periyodu: mesafe kuralı için "o bölgedeki ortalama volatilite"yi
# hesaplarken kaç mumluk pencereye bakılacağı.
ATR_PERIOD = 14

# Mesafe kuralı artık ATR'nin katları cinsinden: gap_size / ATR bu aralıkta
# olmalı. Sayılar VARSAYIM — gerçek veride tespitleri gözden geçirip
# birlikte kalibre edeceğiz.
MIN_GAP_TO_ATR_RATIO = 0.15   # ATR'nin çok altındaki gap'ler "gürültü" sayılır
MAX_GAP_TO_ATR_RATIO = 2.5    # ATR'nin çok üstündeki gap'ler "uçurum" sayılır (3. büyük mum tarzına yakın)

# "Dengesiz FVG" kuralı sayısal olarak PDF'de verilmemiş; ortadaki mumun
# boşluktan kaç kat büyük olması durumunda dengesiz sayılacağı burada bir
# VARSAYIM olarak MAX_MIDDLE_CANDLE_RATIO ile ayarlanabilir bırakıldı.
# Gerçek veride tespitleri gözden geçirip bu sayıyı birlikte kalibre edeceğiz.
MAX_MIDDLE_CANDLE_RATIO = 3.0


def _true_range(candle: dict, prev_close: float) -> float:
    return max(
        candle["high"] - candle["low"],
        abs(candle["high"] - prev_close),
        abs(candle["low"] - prev_close),
    )


def compute_atr_series(candles: list[dict], period: int = ATR_PERIOD) -> list[float | None]:
    """
    Her mum için o ana kadarki basit ortalama True Range'i (ATR) döner.
    İlk `period` mum için yeterli veri olmadığından None döner.
    """
    atrs: list[float | None] = [None] * len(candles)
    true_ranges: list[float] = []

    for i, candle in enumerate(candles):
        if i == 0:
            true_ranges.append(candle["high"] - candle["low"])
        else:
            true_ranges.append(_true_range(candle, candles[i - 1]["close"]))

        if i >= period - 1:
            window = true_ranges[i - period + 1: i + 1]
            atrs[i] = sum(window) / period

    return atrs


def detect_fvgs(candles: list[dict], atr_period: int = ATR_PERIOD) -> list[FVG]:
    """
    Verilen mum listesinden FVG'leri tespit eder ve geçerlilik kurallarını uygular.

    Parametreler
    ----------
    candles : {"open","high","low","close",...} anahtarlı mum sözlüklerinin
              listesi (eskiden yeniye sıralı).
    atr_period : mesafe kuralı için ATR hesabında kullanılacak periyot.

    Dönüş
    -----
    list[FVG] : tespit edilen tüm FVG'ler (geçerli olsun olmasın).
                 fvg.valid == False olanlar mesafe/dengesizlik/multi
                 kurallarından birine takılmış demektir; invalid_reason'da
                 sebebi yazar. İlk `atr_period` mum içinde oluşan FVG'ler
                 ATR henüz hesaplanamadığı için atlanır.
    """
    fvgs: list[FVG] = []
    atr_series = compute_atr_series(candles, atr_period)

    for i in range(len(candles) - 2):
        c1, c2, c3 = candles[i], candles[i + 1], candles[i + 2]
        atr = atr_series[i]
        if atr is None:
            continue  # henüz yeterli veri yok, ATR hesaplanamıyor

        # Bullish FVG: 3. mumun alt fitili, 1. mumun üst fitilinin üstünde
        if c3["low"] > c1["high"]:
            fvgs.append(_build_fvg(i, i + 2, c1["high"], c3["low"],
                                    FVGDirection.BULLISH, c2, atr))

        # Bearish FVG: 3. mumun üst fitili, 1. mumun alt fitilinin altında
        if c3["high"] < c1["low"]:
            fvgs.append(_build_fvg(i, i + 2, c3["high"], c1["low"],
                                    FVGDirection.BEARISH, c2, atr))

    _apply_multi_fvg_rule(fvgs)
    return fvgs


def _build_fvg(start_index: int, end_index: int, bottom: float, top: float,
               direction: FVGDirection, middle_candle: dict, atr: float) -> FVG:
    gap_size = top - bottom
    gap_to_atr = gap_size / atr if atr else 0

    valid = True
    reason = None

    if not (MIN_GAP_TO_ATR_RATIO <= gap_to_atr <= MAX_GAP_TO_ATR_RATIO):
        valid = False
        reason = (f"mesafe kuralı dışında (gap/ATR={gap_to_atr:.2f}, "
                  f"izin verilen aralık {MIN_GAP_TO_ATR_RATIO}-{MAX_GAP_TO_ATR_RATIO})")

    if valid:
        middle_range = middle_candle["high"] - middle_candle["low"]
        if gap_size > 0 and middle_range > gap_size * MAX_MIDDLE_CANDLE_RATIO:
            valid = False
            reason = "dengesiz FVG (ortadaki mum boşluğa göre orantısız büyük)"

    return FVG(start_index=start_index, end_index=end_index, top=top, bottom=bottom,
               direction=direction, valid=valid, invalid_reason=reason)


def _apply_multi_fvg_rule(fvgs: list[FVG]) -> None:
    """
    Birbirine yakın index'te ve fiyat olarak çakışan FVG'leri (multi FVG
    modeli) geçersiz işaretler — PDF'e göre bu kümedeki hiçbir FVG
    güvenilir sayılmıyor.
    """
    for i, fvg in enumerate(fvgs):
        if not fvg.valid:
            continue
        for j, other in enumerate(fvgs):
            if i == j or not other.valid or fvg.direction != other.direction:
                continue

            close_by = abs(fvg.start_index - other.start_index) <= 3
            overlap = min(fvg.top, other.top) - max(fvg.bottom, other.bottom)

            if close_by and overlap > 0:
                fvg.valid = False
                fvg.invalid_reason = "multi FVG (yakında çakışan başka FVG var)"
                break


def mark_filled_fvgs(fvgs: list[FVG], candles: list[dict]) -> list[FVG]:
    """
    Her FVG için, oluştuktan sonraki mumlardan biri gap'in tamamını
    (top-bottom aralığını) geçtiyse filled=True işaretler.
    """
    for fvg in fvgs:
        for candle in candles[fvg.end_index + 1:]:
            if fvg.direction == FVGDirection.BULLISH:
                if candle["low"] <= fvg.bottom:
                    fvg.filled = True
                    break
            else:
                if candle["high"] >= fvg.top:
                    fvg.filled = True
                    break
    return fvgs
