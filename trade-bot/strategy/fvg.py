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
    filled: bool = False             # fiyat bu gap'i (verilen candle dizisinin SONUNA kadar) hiç doldurdu mu
    filled_at_index: int | None = None  # ilk dolum barının index'i (hiç dolmadıysa None) -- causal sorgular için
    valid: bool = True               # tüm geçerlilik kurallarını geçti mi
    invalid_reason: str | None = None  # geçersizse hangi kural yüzünden

    @property
    def entry_price(self) -> float:
        """Kurala göre giriş fiyatı: bullish'te gap'in altı, bearish'te üstü."""
        return self.bottom if self.direction == FVGDirection.BULLISH else self.top

    def is_unfilled_as_of(self, index: int) -> bool:
        """
        FVG'nin, verilen bar'a kadar (bar dahil, sonrası hariç) henüz
        dolmamış olup olmadığını CAUSAL olarak kontrol eder -- yani sadece
        `index`'ten önce/onda gerçekleşmiş bir dolum sayılır, `filled`
        alanının aksine (o, candles dizisinin TAMAMINA -- geleceğe de --
        bakarak hesaplanmıştı). Bir sinyal, kendi oluştuğu bar'da bu
        kontrolü kullanmalı; `filled_at_index` (varsa) her zaman
        `end_index`'ten SONRAKİ bir bar olduğundan, bu kontrol formasyonun
        kendi oluşum barında her zaman True döner -- doğru davranış,
        çünkü henüz hiçbir gelecek bar test edilmemiştir.
        """
        return self.filled_at_index is None or self.filled_at_index > index


from strategy.config import DEFAULT_CONFIG, StrategyConfig

# --- Kalibre edilecek parametreler ---
ATR_PERIOD = DEFAULT_CONFIG.atr_period
MIN_GAP_TO_ATR_RATIO = DEFAULT_CONFIG.min_gap_to_atr_ratio
MAX_GAP_TO_ATR_RATIO = DEFAULT_CONFIG.max_gap_to_atr_ratio
MAX_MIDDLE_CANDLE_RATIO = DEFAULT_CONFIG.max_middle_candle_ratio


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


from dataclasses import replace


def detect_fvgs(candles: list[dict], config: StrategyConfig = DEFAULT_CONFIG, atr_period: int | None = None) -> list[FVG]:
    """
    Verilen mum listesinden FVG'leri tespit eder ve geçerlilik kurallarını uygular.
    """
    if atr_period is not None:
        config = replace(config, atr_period=atr_period)
    fvgs: list[FVG] = []
    atr_series = compute_atr_series(candles, config.atr_period)

    for i in range(len(candles) - 2):
        c1, c2, c3 = candles[i], candles[i + 1], candles[i + 2]
        atr = atr_series[i]
        if atr is None:
            continue  # henüz yeterli veri yok, ATR hesaplanamıyor

        # Bullish FVG: 3. mumun alt fitili, 1. mumun üst fitilinin üstünde
        if c3["low"] > c1["high"]:
            fvgs.append(_build_fvg(i, i + 2, c1["high"], c3["low"],
                                    FVGDirection.BULLISH, c2, atr, config))

        # Bearish FVG: 3. mumun üst fitili, 1. mumun alt fitilinin altında
        if c3["high"] < c1["low"]:
            fvgs.append(_build_fvg(i, i + 2, c3["high"], c1["low"],
                                    FVGDirection.BEARISH, c2, atr, config))

    _apply_multi_fvg_rule(fvgs)
    return fvgs


def _build_fvg(start_index: int, end_index: int, bottom: float, top: float,
               direction: FVGDirection, middle_candle: dict, atr: float, config: StrategyConfig = DEFAULT_CONFIG) -> FVG:
    gap_size = top - bottom
    gap_to_atr = gap_size / atr if atr else 0

    valid = True
    reason = None

    if not (config.min_gap_to_atr_ratio <= gap_to_atr <= config.max_gap_to_atr_ratio):
        valid = False
        reason = (f"mesafe kuralı dışında (gap/ATR={gap_to_atr:.2f}, "
                  f"izin verilen aralık {config.min_gap_to_atr_ratio}-{config.max_gap_to_atr_ratio})")

    if valid:
        middle_range = middle_candle["high"] - middle_candle["low"]
        if gap_size > 0 and middle_range > gap_size * config.max_middle_candle_ratio:
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
    to_invalidate = set()
    n = len(fvgs)
    for i in range(n):
        if not fvgs[i].valid:
            continue
        for j in range(i + 1, n):
            if not fvgs[j].valid or fvgs[i].direction != fvgs[j].direction:
                continue

            close_by = abs(fvgs[i].start_index - fvgs[j].start_index) <= 3
            overlap = min(fvgs[i].top, fvgs[j].top) - max(fvgs[i].bottom, fvgs[j].bottom)

            if close_by and overlap > 0:
                to_invalidate.add(i)
                to_invalidate.add(j)

    for idx in to_invalidate:
        fvgs[idx].valid = False
        fvgs[idx].invalid_reason = "multi FVG (yakında çakışan başka FVG var)"


def mark_filled_fvgs(fvgs: list[FVG], candles: list[dict]) -> list[FVG]:
    """
    Her FVG için, oluştuktan sonraki mumlardan biri KAPANIŞLA gap'in
    tamamının (uzak kenarının) dışına çıktıysa filled=True işaretler ve
    o barın index'ini filled_at_index'e kaydeder.

    ÖNEMLİ (kullanıcı düzeltmesi): fitilin gap'e değmesi ya da gap'in
    içine (hatta en dibine/tepesine kadar) girmesi FVG'yi GEÇERSİZ
    kılmaz -- bu normal bir retest/reaksiyon. Ancak bir mumun KAPANIŞI
    gap'in tamamını geçip uzak kenarın dışına çıkarsa FVG artık
    kullanılamaz sayılır. Bu, "FVG doldu" ile "FVG invert oldu" (bkz.
    iFVG -- scratch_multi_timeframe_fvg_scan.py:detect_ifvgs) olayının
    AYNI tetikleyiciye sahip olduğu anlamına gelir -- sadece bakış
    açısı farklı (kendi yönünde geçersiz mi, yoksa ters yönde yeni bir
    bölge mi).

    NOT: `filled`/`filled_at_index` burada candles dizisinin TAMAMINA
    (geleceğe de) bakılarak hesaplanır -- bu, "FVG şu ana kadar dolmuş
    mu" gibi tarihsel/analiz amaçlı sorular için doğrudan kullanılabilir,
    ama SİNYAL ÜRETİMİNDE (bir bar'da bu FVG hâlâ geçerli mi?) doğrudan
    `not fvg.filled` olarak kullanmak causal değildir -- `fvg.is_unfilled_as_of(bar_index)`
    kullanılmalı (bkz. o metodun docstring'i, ve bunun neden önemli
    olduğuna dair not: NOA_KONSEPTI_KAYNAK_ANALIZI.md).
    """
    for fvg in fvgs:
        for i in range(fvg.end_index + 1, len(candles)):
            candle = candles[i]
            if fvg.direction == FVGDirection.BULLISH:
                if candle["close"] < fvg.bottom:
                    fvg.filled = True
                    fvg.filled_at_index = i
                    break
            else:
                if candle["close"] > fvg.top:
                    fvg.filled = True
                    fvg.filled_at_index = i
                    break
    return fvgs
