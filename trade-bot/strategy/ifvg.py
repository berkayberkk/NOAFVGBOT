"""
iFVG (Inverse Fair Value Gap) tespit modülü.

Kurallar (bu oturumda netleştirildi, bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md
"iFVG" bölümü -- önceki, "her invalidation = iFVG" şeklindeki gevşek
tanımın yerine geçti):

1. KIRILMA: bir FVG'nin kapanışla TAMAMEN geçilmesi (mevcut, test edilmiş
   `mark_filled_fvgs` mantığıyla aynı tetikleyici -- fitille değme değil,
   kapanış).
2. RETEST: kırılmadan SONRA (süre sınırı YOK), fiyatın geri dönüp
   bölgenin YAKIN kenarına (kırılan tarafa) fitille dokunması VE o mumun
   kapanışının dışarıda kalması (reddiye, "wick rejection"). İLK
   TEMASTA KARAR VERİLİR -- ilk temas reddetmezse (bölgeye kapanırsa) o
   FVG başarısız sayılır, iFVG oluşmaz.
3. CHOP-CLUSTER filtresi: bu bölge, GEÇMİŞTE (nedensel, geleceğe
   bakmadan) son `chop_cluster_bars` bar içinde ZIT yönlü başka bir
   kırılma/retest ile ÇAKIŞIYORSA şüpheli sayılır ve elenir -- aynı
   bölgenin kısa sürede iki kez zıt yönde "kırılması" bir chop/kararsızlık
   işareti, temiz bir yön değişimi değil.

Diğer strateji modülleriyle aynı desen: `strategy/fvg.py`'nin geçerli
FVG'leri (`detect_fvgs`) girdi olarak yeniden kullanılıyor, FVG'nin
kendi causal garantileri (ATR bazlı geçerlilik, 3-mumluk geometri)
buraya miras kalıyor.
"""

from dataclasses import dataclass

from strategy.fvg import detect_fvgs, FVGDirection


@dataclass
class IFVGEvent:
    top: float                      # kaynak FVG'nin üst sınırı
    bottom: float                    # kaynak FVG'nin alt sınırı
    new_dir: FVGDirection             # kırılma sonrası YENİ yön (reversal'ın yönü)
    broken_index: int                 # FVG'nin kapanışla kırıldığı bar
    retest_index: int                  # reddiye barının index'i -- giriş burada
    consequent_encroachment: float      # bölgenin %50 orta noktası (entry seviyesi)
    chop_cluster: bool = False           # yakın zamanlı zıt-yönlü çakışma nedeniyle şüpheli mi


from strategy.config import DEFAULT_CONFIG, StrategyConfig

# --- Kalibre edilecek parametreler ---
CHOP_CLUSTER_BARS = 15


def detect_confirmed_ifvgs(candles: list[dict], config: StrategyConfig = DEFAULT_CONFIG,
                           chop_cluster_bars: int = CHOP_CLUSTER_BARS) -> list[IFVGEvent]:
    """Kırılma + retest/reddiye + causal chop-cluster filtresiyle onaylanmış iFVG listesi döner."""
    fvgs = [f for f in detect_fvgs(candles, config=config) if f.valid]
    n = len(candles)
    events: list[IFVGEvent] = []

    for f in fvgs:
        broken_index = None
        new_dir = None
        for i in range(f.end_index + 1, n):
            c = candles[i]
            if f.direction == FVGDirection.BULLISH and c["close"] < f.bottom:
                broken_index, new_dir = i, FVGDirection.BEARISH
                break
            if f.direction == FVGDirection.BEARISH and c["close"] > f.top:
                broken_index, new_dir = i, FVGDirection.BULLISH
                break
        if broken_index is None:
            continue

        retest_index = None
        for j in range(broken_index + 1, n):
            cj = candles[j]
            if new_dir == FVGDirection.BEARISH:
                touched = cj["high"] >= f.bottom
                rejected = cj["close"] < f.bottom
            else:
                touched = cj["low"] <= f.top
                rejected = cj["close"] > f.top
            if touched:
                if rejected:
                    retest_index = j
                break
        if retest_index is None:
            continue

        events.append(IFVGEvent(
            top=f.top, bottom=f.bottom, new_dir=new_dir,
            broken_index=broken_index, retest_index=retest_index,
            consequent_encroachment=(f.top + f.bottom) / 2,
        ))

    _mark_chop_clusters(events, chop_cluster_bars)
    return [e for e in events if not e.chop_cluster]


def _mark_chop_clusters(events: list[IFVGEvent], chop_cluster_bars: int = CHOP_CLUSTER_BARS) -> None:
    """
    Her event için, ondan ÖNCE (causal -- sadece geçmişe bakarak) kırılmış,
    `chop_cluster_bars` içinde ve bölgesi çakışan, ZIT yönlü başka bir event
    varsa `chop_cluster=True` işaretler. Yerinde (in-place) mutasyon yapar.
    """
    for e in events:
        for e2 in events:
            if e2.broken_index >= e.broken_index:
                continue
            if e.broken_index - e2.broken_index > chop_cluster_bars:
                continue
            overlap = min(e.top, e2.top) - max(e.bottom, e2.bottom)
            if overlap > 0 and e.new_dir != e2.new_dir:
                e.chop_cluster = True
