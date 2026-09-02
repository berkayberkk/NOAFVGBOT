"""
Trendline (diyagonal trend çizgisi) tespit modülü.

Derin araştırmadan (TrendSpider, Tradeciety, LuxAlgo "Trendline
Liquidity" -- bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md "Trendline" bölümü,
2026-08-31):

- Yükselen trendline: art arda YÜKSELEN swing low'ları birleştiren
  diyagonal (destek çizgisi, bullish). Düşen trendline: art arda DÜŞEN
  swing high'ları birleştiren diyagonal (direnç çizgisi, bearish).
- Geçerlilik: "iki nokta çizer, üç nokta doğrular" -- 2 swing noktası
  geometrik olarak bir aday çizgi tanımlar, ama 3. bir swing noktasının
  (causal olarak, o ana kadar) çizgiye saygı göstermesi (fitille dokunup
  ters yöne dönmesi) gerekir; ancak o zaman "doğrulanmış" sayılır.
- Dokunuş: FİTİL ile ölçülür (swing high/low'un kendisi zaten fitil
  ucudur). Kırılma (invalidation): sadece KAPANIŞ ile -- FVG/OB'de
  kullanılan aynı desen.

ALGORİTMA (tek geçişli, causal): Her yön (yükselen/düşen) için, ardışık
swing noktaları arasında ADAY bir 2-nokta çizgi kurulur. Sonraki her
mumda KAPANIŞ çizgiyi ihlal ederse aday/doğrulanmış çizgi biter (yeni
adaya sıfırlanır -- doğrulanmış olan `broken=True` ile sonuçlara
eklenir). Yeni bir swing noktası çizgiye (toleransla) dokunursa bu bir
"doğrulama dokunuşu" sayılır; 3. dokunuşta çizgi "doğrulanmış" olur. Yeni
bir swing noktası çizgiyi kırmadan ama ondan daha dik/uzak geçerse
(henüz doğrulanmamışsa), aday çizgi bu yeni, daha dik noktayla güncellenir
-- bu, `zone.py`'nin "daha ekstrem pivotu tut" deseniyle aynı ruhta,
kodda kasıtlı bir basitleştirme olarak işaretlenmiştir.

MVP KAPSAM KARARI: Bu modül SADECE temel yapı taşını kapsıyor --
`detect_trendlines` (aday + 3. dokunuşla causal doğrulama) ve
`mark_broken_trendlines`in `detect_trendlines` içine gömülü hali (kırılan
çizgiler zaten `broken=True` ile dönüyor). Süpürme/gerçek-kırılma ayrımı,
break+retest sinyali ve bounce sinyali kasıtlı olarak kapsam dışı --
kaynakların kendisi de "hangi kırılmanın süpürme olduğu önceden kesin
ayrılamaz" diyor (FVG/OB'nin aksine). Bunlar, FVG'den iFVG'ye geçişteki
gibi, gerçek veriyle görsel doğrulama sonrası ikinci aşamada eklenecek.
"""

from dataclasses import dataclass
from enum import Enum

from strategy.fvg import compute_atr_series
from strategy.support_resistance import find_swing_points


class TrendlineDirection(Enum):
    ASCENDING = "ascending"    # yukselen swing low'lari birlestirir -- destek, bullish
    DESCENDING = "descending"  # dusen swing high'lari birlestirir -- direnc, bearish


@dataclass
class Trendline:
    direction: TrendlineDirection
    anchor_indices: list[int]          # cizgiyi tanimlayan/dogrulayan swing index'leri (kronolojik)
    slope: float                        # bar basina fiyat degisimi
    intercept: float                    # index 0'daki (teorik) fiyat -- price_at(0) ile ayni
    validated_index: int                # 3. dokunusun (dogrulamanin) gerceklestigi bar -- cizgi bu bardan itibaren "var"
    swing_lookback: int                 # find_swing_points'e verilen lookback -- known_index hesabinda kullanilir
    touch_count: int = 3                # dogrulama anindaki dokunus sayisi, sonradan artabilir
    broken: bool = False
    broken_index: int | None = None

    def price_at(self, index: int) -> float:
        return self.slope * index + self.intercept

    @property
    def known_index(self) -> int:
        """
        KRITIK (causal): validated_index bir swing noktasi (find_swing_points'in
        3. anchor'i) -- ve find_swing_points bir mumun swing oldugunu ancak
        SONRASINDAKI `swing_lookback` mumu da gorunce onaylayabiliyor (bkz.
        support_resistance.py:find_swing_points, simetrik pencere). Yani bu
        cizginin VARLIGI bile validated_index'te degil, ancak
        validated_index+swing_lookback'te "biliniyor" sayilabilir -- ondan
        ONCEKI hicbir dokunus/kirilma/retest CAUSAL olarak islenemez (gelecek
        veri sizdirir). Trade simulasyonu bu index'ten ONCEKI hicbir olayi
        kullanmamali.
        """
        return self.validated_index + self.swing_lookback


from strategy.config import DEFAULT_CONFIG, StrategyConfig

# --- Kalibre edilecek parametreler ---
SWING_LOOKBACK = DEFAULT_CONFIG.trendline_swing_lookback
MIN_TOUCHES = DEFAULT_CONFIG.trendline_min_touches
TOUCH_TOLERANCE_ATR_RATIO = DEFAULT_CONFIG.trendline_touch_tolerance_atr_ratio


def _fit_line(i: int, price_i: float, j: int, price_j: float) -> tuple[float, float]:
    """(i, price_i) ve (j, price_j) noktalarindan gecen dogrunun slope/intercept'i."""
    slope = (price_j - price_i) / (j - i)
    intercept = price_i - slope * i
    return slope, intercept


def _detect_one_direction(candles: list[dict], atr_series: list[float | None], pivots: list[int],
                          price_key: str, direction: TrendlineDirection, rising: bool,
                          config: StrategyConfig) -> list[Trendline]:
    """
    TEK GECISLI (O(n)): candles uzerinde bir kez ilerler, HER YON icin
    aynı anda sadece TEK BIR aktif aday/dogrulanmis cizgi izlenir (zone.py'nin
    "tek aktif zone" modeliyle ayni ruhta -- basitlik/performans icin
    kasitli bir MVP sinirlamasi: ic ice/es zamanli birden fazla trendline
    yakalanmiyor). Cizgi kirildiginda sifirlanir, sonraki iki pivot yeni
    adayi baslatir.
    """
    n = len(candles)
    lines: list[Trendline] = []
    pivot_set = set(pivots)

    def better(price: float, ref: float) -> bool:
        return price > ref if rising else price < ref

    i: int | None = None       # 1. anchor pivot index'i
    j: int | None = None       # 2. anchor pivot index'i (aday cizgiyi tanimlar)
    slope = intercept = 0.0
    touches: list[int] = []
    cur_line: Trendline | None = None

    def reset():
        nonlocal i, j, touches, cur_line
        i = j = None
        touches = []
        cur_line = None

    for k in range(n):
        if j is not None:
            close = candles[k]["close"]
            line_price = slope * k + intercept
            broke = (close < line_price) if rising else (close > line_price)
            if broke and k > j:
                if cur_line is not None:
                    cur_line.broken = True
                    cur_line.broken_index = k
                    lines.append(cur_line)
                reset()

        if k in pivot_set:
            price_k = candles[k][price_key]
            if i is None:
                i = k
            elif j is None:
                if (price_k > candles[i][price_key]) == rising:
                    j = k
                    slope, intercept = _fit_line(i, candles[i][price_key], j, price_k)
                    touches = [i, j]
                else:
                    i = k  # yon uyumsuz -- yeni anchor olarak bu pivottan devam
            else:
                line_price = slope * k + intercept
                tol = (atr_series[k] or 0) * config.trendline_touch_tolerance_atr_ratio
                if abs(price_k - line_price) <= tol:
                    touches.append(k)
                    if cur_line is not None:
                        cur_line.touch_count += 1
                        cur_line.anchor_indices.append(k)
                    elif len(touches) >= config.trendline_min_touches:
                        cur_line = Trendline(
                            direction=direction, anchor_indices=list(touches),
                            slope=slope, intercept=intercept,
                            validated_index=k, swing_lookback=config.trendline_swing_lookback,
                            touch_count=len(touches),
                        )
                elif cur_line is None and better(price_k, line_price):
                    # henuz dogrulanmadi -- daha dik/ekstrem pivotla adayi guncelle
                    j = k
                    slope, intercept = _fit_line(i, candles[i][price_key], j, price_k)
                    touches = [i, j]

    if cur_line is not None:
        lines.append(cur_line)  # seri sonunda hala acik (kirilmamis)

    return lines


def detect_trendlines(candles: list[dict], config: StrategyConfig = DEFAULT_CONFIG) -> list[Trendline]:
    """
    Swing low ciftlerinden yukselen, swing high ciftlerinden dusen aday
    trendline'lar kurar; her adayin CAUSAL olarak (o ana kadarki veriyle)
    3. bir dokunusla dogrulanip dogrulanmadigini kontrol eder (bkz. modul
    docstring'i -- tek gecisli algoritma).
    """
    swing_highs, swing_lows = find_swing_points(candles, lookback=config.trendline_swing_lookback)
    atr_series = compute_atr_series(candles, config.atr_period)

    lines = []
    lines += _detect_one_direction(candles, atr_series, swing_lows, "low", TrendlineDirection.ASCENDING, True, config)
    lines += _detect_one_direction(candles, atr_series, swing_highs, "high", TrendlineDirection.DESCENDING, False, config)
    lines.sort(key=lambda tl: tl.validated_index)
    return lines


@dataclass
class TrendlineReversal:
    """
    Kırılım + retest + reddiye (iFVG'nin "kırılma+retest+reddiye"
    örüntüsüyle yapısal olarak birebir aynı, bkz. modül docstring'i).
    Düşen (direnç) çizgi yukarı kırılırsa BULLISH reversal (long), yükselen
    (destek) çizgi aşağı kırılırsa BEARISH reversal (short) -- çizgi artık
    rol değiştirip yeni destek/direnç olur.
    """
    source_trendline: Trendline
    is_bullish: bool               # True: long (dusen cizgi yukari kirildi), False: short
    retest_index: int              # reddiye barinin index'i -- giris burada
    entry_price: float             # retest anindaki cizgi fiyati


def detect_trendline_reversals(candles: list[dict], lines: list[Trendline],
                               config: StrategyConfig = DEFAULT_CONFIG) -> list[TrendlineReversal]:
    """
    Her KIRILMIŞ trendline için, kırılmadan SONRA (süre sınırı YOK --
    iFVG'de doğrulanan "süre önemli değil" bulgusuyla aynı), fiyatın geri
    dönüp kırılan çizgiye (artık rol değiştirmiş -- eski destek/direnç
    yeni direnç/destek) fitille dokunup AYNI BARDA reddetmesi (kapanışın
    eski bölgeye geri DÖNMEMESİ) aranır. İLK TEMASTA KARAR VERİLİR: ilk
    temas reddetmezse (kapanış eski tarafa geri dönerse) o kırılma için
    reversal sinyali OLUŞMAZ (iFVG'nin "ilk temas reddetmezse iFVG
    oluşmaz" kuralıyla aynı).

    CAUSAL NOT: tarama, `tl.known_index`'ten ÖNCE başlamaz -- çizginin
    kendisi (slope/intercept/validated_index) causal olarak ancak o
    bardan itibaren "bilinebilir" (bkz. Trendline.known_index). Kırılma
    known_index'ten önce gerçekleşmiş olsa bile (fiyat çizgiyi biz daha
    "görmeden" kırmış olabilir), retest araması known_index'ten başlar.
    """
    atr_series = compute_atr_series(candles, config.atr_period)
    n = len(candles)
    reversals: list[TrendlineReversal] = []

    for tl in lines:
        if not tl.broken or tl.broken_index is None:
            continue
        is_bullish = tl.direction == TrendlineDirection.DESCENDING  # dusen direnc yukari kirildi -> bullish

        scan_start = max(tl.broken_index, tl.known_index) + 1
        for k in range(scan_start, n):
            line_price = tl.price_at(k)
            tol = (atr_series[k] or 0) * config.trendline_touch_tolerance_atr_ratio
            c = candles[k]
            if is_bullish:
                touched = c["low"] <= line_price + tol
                rejected = c["close"] > line_price
            else:
                touched = c["high"] >= line_price - tol
                rejected = c["close"] < line_price

            if not touched:
                continue
            if rejected:
                reversals.append(TrendlineReversal(
                    source_trendline=tl, is_bullish=is_bullish,
                    retest_index=k, entry_price=line_price,
                ))
            break  # ilk temasta karar verildi (reddetti ya da etmedi) -- ya sinyal uret ya da vazgec

    reversals.sort(key=lambda r: r.retest_index)
    return reversals
