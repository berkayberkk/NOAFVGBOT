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

EKLENTİ (2026-09-02): yukarıdaki üç filtre artık her OrderBlock için
BİLGİ AMAÇLI (informational) boolean alan olarak hesaplanıyor --
`engulfing`, `swept_liquidity`, `htf_discount_aligned`. detect_order_blocks
davranışı DEĞİŞMEDİ (hiçbir OB bu alanlara göre elenmiyor) -- sadece
scratch_ob_filters_study.py'nin ablation testi yapabilmesi için sinyal
üzerine etiket ekleniyor. Filtrelerden hangisinin gerçekten PF/beklenti
artırdığı ölçülmeden hiçbiri detect_order_blocks'un ELEME mantığına
dahil edilmeyecek (bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md "Order Block
filtre ablasyonu" bölümü). Tüm üç hesaplama da CAUSAL'dır -- sadece
OB mumu (ob_index) ve impuls mumu (i, zaten OB'nin kendisini
doğrulamak için kullanılan aynı bar) ile ONDAN ÖNCEKİ mumlara bakar,
gelecek veri kullanmaz.
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
    # 2026-09-02 eklendi -- bilgi amaçlı ICT filtre etiketleri (bkz. modül
    # docstring'i). Hiçbiri detect_order_blocks tarafından ELEME için
    # kullanılmıyor, sadece scratch_ob_filters_study.py'nin ablation
    # testi yapabilmesi için işaretleniyor.
    engulfing: bool = False           # impuls mumu, OB mumunun tum high-low araligini (fitil dahil) yutuyor mu
    swept_liquidity: bool = False     # OB mumu, kendinden onceki N barin en dip/tepe seviyesini gecti mi (likidite supurmesi)
    htf_discount_aligned: bool = False  # entry seviyesi, N barlik HTF-proxy araligin dogru yarisinda mi (bullish->discount, bearish->premium)
    # 2026-09-03 eklendi -- ayni disiplinle, win-rate arastirmasi alanlari
    # (bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md). Yine hicbiri ELEME icin
    # kullanilmiyor.
    in_killzone: bool = False          # impuls mumu ICT killzone saatinde mi olustu
    volume_confirmed: bool = False      # impuls mumunun hacmi son N mumun ortalamasinin X kati mi


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


def _average_volume_series(candles: list[dict], period: int) -> list[float | None]:
    """Her mum icin, kendisinden ONCEKI `period` mumun ortalama tick_volume'unu doner (causal)."""
    volumes = [c.get("tick_volume", 0) for c in candles]
    result: list[float | None] = [None] * len(candles)
    for i in range(len(candles)):
        if i < period:
            continue
        window = volumes[i - period:i]
        result[i] = sum(window) / period
    return result


from strategy.session import in_killzone as _in_killzone_fn

_KILLZONE_HOURS = frozenset(h for h in range(24) if _in_killzone_fn(h))


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
    avg_volumes = _average_volume_series(candles, config.volume_confirm_period)
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

        # Engulfing: impuls mumu, OB mumunun TUM high-low araligini (govde
        # degil, fitil dahil) yutuyor mu -- standart ICT engulfing sarti.
        engulfing = candle["high"] >= ob_candle["high"] and candle["low"] <= ob_candle["low"]

        # Likidite supurmesi: OB mumu, kendinden ONCEKI N barin (ob_index
        # haric) en dusuk dip/en yuksek tepe seviyesini gecti mi.
        sweep_start = max(0, ob_index - config.ob_liquidity_sweep_lookback)
        prior_window = candles[sweep_start:ob_index]
        if prior_window:
            if direction == OBDirection.BULLISH:
                prior_low = min(c["low"] for c in prior_window)
                swept_liquidity = ob_candle["low"] < prior_low
            else:
                prior_high = max(c["high"] for c in prior_window)
                swept_liquidity = ob_candle["high"] > prior_high
        else:
            swept_liquidity = False

        # HTF premium/discount (proxy): OB mumuna kadar olan N barlik
        # aralik gercek bir HTF mumu degil ama yerine gecen bir pencere --
        # bullish OB sadece araligin ALT yarisinda (discount), bearish
        # sadece UST yarisinda (premium) gecerli sayilir.
        pd_start = max(0, ob_index - config.ob_premium_discount_lookback + 1)
        pd_window = candles[pd_start:ob_index + 1]
        range_high = max(c["high"] for c in pd_window)
        range_low = min(c["low"] for c in pd_window)
        midpoint = (range_high + range_low) / 2.0
        entry_level = (top + bottom) / 2.0
        if direction == OBDirection.BULLISH:
            htf_discount_aligned = entry_level < midpoint
        else:
            htf_discount_aligned = entry_level > midpoint

        avg_vol = avg_volumes[i]
        vol_confirmed = bool(avg_vol and candle.get("tick_volume", 0) >= avg_vol * config.volume_confirm_ratio)
        in_kz = candle["time"].hour in _KILLZONE_HOURS if hasattr(candle["time"], "hour") else False

        blocks.append(OrderBlock(
            index=ob_index,
            impulse_index=i,
            top=top,
            bottom=bottom,
            direction=direction,
            engulfing=engulfing,
            swept_liquidity=swept_liquidity,
            htf_discount_aligned=htf_discount_aligned,
            in_killzone=in_kz,
            volume_confirmed=vol_confirmed,
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
