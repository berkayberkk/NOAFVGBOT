"""
Merkezi Strateji Yapılandırması (Centralized Strategy Configuration).

Tüm strateji parametreleri burada tek bir dataclass altında toplanmıştır.
Tüm varsayılan değerler orijinal strateji kodundaki sabitlerle 100% aynıdır.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyConfig:
    # --- FVG Parametreleri ---
    atr_period: int = 14
    min_gap_to_atr_ratio: float = 0.15
    max_gap_to_atr_ratio: float = 2.5
    max_middle_candle_ratio: float = 3.0

    # --- Order Block Parametreleri ---
    avg_range_period: int = 14
    strong_move_ratio: float = 2.0
    # 2026-09-02 eklendi -- eksik ICT filtreleri (bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md
    # "Order Block" bölümü, kod ile uyum tablosu): likidite süpürmesi ve
    # HTF premium/discount için lookback pencereleri. Ampirik olarak
    # kalibre edilmedi -- makul varsayılanlar, scratch_ob_filters_study.py
    # ile ablation testinden geçirilecek.
    ob_liquidity_sweep_lookback: int = 10
    ob_premium_discount_lookback: int = 48  # M30'da ~1 gun -- HTF gunluk araligin yerini tutan pencere

    # --- Hacim Teyidi Parametreleri (2026-09-03 eklendi, FVG + OB icin ortak) ---
    # bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md "Win rate iyilestirme arastirmasi" --
    # birden fazla ICT kaynagi "displacement mumunun hacmi son N mumun
    # ortalamasinin X kati olmali" filtresini "tek en iyi teyit" diye
    # isaretledi. Ampirik olarak kalibre EDILMEDI, kaynak materyaldeki
    # tipik degerler (1.5x, 20 bar) kullanildi.
    volume_confirm_period: int = 20
    volume_confirm_ratio: float = 1.5

    # --- Backtest İşlem Maliyetleri (0.0 varsayılan = geriye dönük uyumlu) ---
    spread: float = 0.0            # Fiyat mesafesi cinsinden spread (örn. 0.20)
    slippage: float = 0.0          # Taraf başına olumsuz kayma mesafesi (örn. 0.05)
    commission: float = 0.0        # İşlem başı tur maliyeti (fiyat mesafesi cinsinden, örn. 0.10)

    # --- Destek / Direnç Parametreleri ---
    swing_lookback: int = 5
    tolerance_atr_ratio: float = 0.5
    min_level_touch_count: int = 2

    # --- Trend Parametreleri ---
    ema_period: int = 50

    # --- Alan / Katman Parametreleri ---
    # SR'nin swing_lookback'inden (5) BİLEREK farklı/geniş tutuldu -- Alan'lar
    # SR seviyelerinden daha büyük ölçekli trend leg'lerini temsil ediyor.
    zone_swing_lookback: int = 10
    # Donmuş (Eski Alan/O) bir alanın "geniş" sayılması için minimum boyut,
    # start_index'teki ATR'nin katı cinsinden. Kaynak yalnızca nitel olarak
    # ("2-3 mumluk alan geçersiz") belirtiyor -- bu sayısal eşik kod tarafında
    # bir varsayımdır, gerçek veriyle kalibre edilmesi gerekir.
    zone_min_size_atr_ratio: float = 3.0

    # --- Trendline Parametreleri ---
    # SR'nin swing_lookback'inden (5) BİLEREK farklı/geniş -- trendline'lar
    # SR seviyelerinden daha büyük ölçekli yapıları (Alan/Katman'daki gibi)
    # temsil ediyor. zone_swing_lookback (10) ile aynı değer, aynı gerekçe.
    trendline_swing_lookback: int = 10
    # Araştırmadan (TrendSpider, Tradeciety -- "iki nokta çizer, üç nokta
    # doğrular"): bir trendline sadece 2 swing noktasından GEOMETRİK olarak
    # çizilebilir, ama 3. bir swing noktası çizgiyi DOĞRULAMADAN önce
    # "aday" sayılır, gerçek/tradeable sayılmaz.
    trendline_min_touches: int = 3
    # Bir swing noktasının çizgiye "dokunmuş" sayılması için tolerans,
    # ATR'nin katı cinsinden -- support_resistance.py'nin
    # tolerance_atr_ratio'suyla aynı değer/mantık (fitil/swing bazlı temas,
    # tam piksel hassasiyeti aranmıyor).
    trendline_touch_tolerance_atr_ratio: float = 0.5


# Global varsayılan yapılandırma nesnesi
DEFAULT_CONFIG = StrategyConfig()


# --- Sembol / modül bazlı strateji parametreleri (2026-08-31'den itibaren,
# 101 sembol x 6 zaman dilimi R-katı çalışmalarından ve 95 sembollük
# $10.000 hesap simülasyonundan -- bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md
# "Sembol eleme turu" bölümleri -- kademeli olarak daraltıldı) ---
#
# Tarihçe (her tur bir öncekinin üzerine kademeli daraltma yaptı):
#   Tur 1 (2026-08-31): FVG+iFVG+OB'nin ortak en kötü 10'u -- GERTECH30,
#     NASDAQ, IT40, GERMID50, EURDKK, USFANG (6 sembol çıkarıldı).
#   Tur 2 (2026-09-01): 95 sembollük hesap simülasyonunda sabit-$ risk
#     modeline göre en düşük getirili 10 sembol -- EURTRY, SPAIN35, SA40,
#     TAIWAN, HK50, PALLADIUM, CHN50, CA60, USDTRY, USDHKD.
#   Tur 3 (2026-09-02): Aynı simülasyonda kazanma oranı %47'nin altında
#     olan 15 sembol -- EURPLN, CHINAH, EU50, GER40, EURHUF, NETH25,
#     BTCUSD, EURSEK, EURCHF, USDNOK, GBPNOK, SING30, DOGEUSD, UK100,
#     EURGBP (70 sembol kalmıştı).
#   Tur 4 (2026-09-02): Kullanıcı kararıyla kapsam GOLD, BTCUSD, EURGBP
#     ÜÇLÜSÜNE daraltıldı -- geri kalan HER ŞEY çıkarıldı (BTCUSD ve
#     EURGBP tur 3'te çıkarılmıştı, bu turda geri eklendi).
#
# Kanonik 101 sembollük evrenden (bkz. backtest/run_multi_symbol_validation.py)
# sadece bu üçü kalıyor -- sinyal üretiminden ve yeni testlerden tamamen
# çıkarılır, veri (data acquisition) listelerinden değil.
KEPT_SYMBOLS: tuple[str, ...] = ("GOLD", "BTCUSD", "EURGBP")

_ALL_101_SYMBOLS = (
    "EURUSD", "GBPUSD", "USDCHF", "USDCAD", "AUDCAD", "EURGBP", "USDJPY", "EURJPY", "EURCAD",
    "NASDAQ", "SILVER", "AUDUSD", "NZDUSD", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY",
    "EURAUD", "EURNZD", "EURCHF", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD", "AUDCHF", "AUDNZD",
    "CADCHF", "NZDCAD", "NZDCHF", "BTCUSD", "WTI", "GOLD", "CHFSGD", "EURDKK", "EURHKD",
    "EURHUF", "EURNOK", "EURPLN", "EURSEK", "EURSGD", "EURTRY", "EURZAR", "GBPDKK", "GBPNOK",
    "GBPSEK", "GBPSGD", "NZDSGD", "SGDJPY", "USDCNH", "USDDKK", "USDHKD", "USDHUF", "USDMXN",
    "USDNOK", "USDPLN", "USDSEK", "USDSGD", "USDTRY", "USDZAR", "AUS200", "CA60", "CHN50",
    "CHINAH", "EU50", "FRA40", "GER40", "GERMID50", "GERTECH30", "HK50", "IT40", "JP225",
    "NETH25", "SA40", "SWI20", "SING30", "SPAIN35", "TAIWAN", "UK100", "US2000", "US30",
    "US500", "USFANG", "PLATINUM", "PALLADIUM", "BRENT", "ETHUSD", "XRPUSD", "SOLUSD",
    "DOGEUSD", "ADAUSD", "DOTUSD", "LINKUSD", "AVAXUSD", "MATICUSD", "BCHUSD", "LTCUSD",
    "ATOMUSD", "UNIUSD", "XLMUSD", "ETCUSD",
)

EXCLUDED_SYMBOLS: tuple[str, ...] = tuple(s for s in _ALL_101_SYMBOLS if s not in KEPT_SYMBOLS)

# Modül başına TP hedefi (R katı). FVG ve iFVG'de beklenti (expectancy_r)
# R≈1.5'te tepe yapıp geriliyor; Order Block ve Trendline'da ise test
# edilen tüm aralıkta (5.0R'ye kadar) hiç tepe yapmadan artmaya devam
# ediyor -- PF ise OB'de R≈2.5-3.0'da, Trendline'da tam R=2.0'da tepe
# yapıyor, bu yüzden ikisinde de kendi PF tepe noktaları seçildi. R>5.0
# için OB/Trendline'ın gerçek beklenti tepe noktası henüz ölçülmedi.
MODULE_R_MULTIPLE: dict[str, float] = {
    "fvg": 1.5,
    "ifvg": 1.5,
    "ob": 3.0,
    "trendline": 2.0,
}

# Modülün SL tamponu -- FVG/iFVG/OB kendi bölge boyutunun (gap/gövde)
# katı, Trendline ise dokunuş/retest barının kendi ATR'sinin katı
# (bölge boyutu kavramı yok, diyagonal bir çizgi).
# fvg=15.0/ob=30.0/ifvg=15.0/trendline=5.0 (2026-09-03 GÜNCELLENDİ -- eski
# 1.0/3.0/1.0/0.5'ten): win-rate araştırmasının SL tamponu yeniden
# kalibrasyonu, DÜZELTİLMİŞ motorla ve YENİ giriş kuralıyla, KEPT_SYMBOLS'ün
# her birinde kendi kronolojik train+val (%80) kümesinde adaylar tarandı,
# TEK bir aday seçilip HİÇ BAKILMAMIŞ test (%20) holdout'unda TEK ATIMLIK
# doğrulandı (bkz. scratch_sl_buffer_holdout_check.py + scratch_ifvg_sl_
# buffer_holdout_check.py + scratch_trendline_sl_buffer_holdout_check.py,
# NOA_KONSEPTI_KAYNAK_ANALIZI.md "Aday 6/7/8" bölümleri). FVG/OB: 6/6,
# iFVG: 3/3, Trendline: 3/3 sembol×modül kombinasyonunda holdout'ta
# expectancy iyileşti (GOLD'un tümünde, Trendline'da ayrıca BTCUSD'de de
# pozitife döndü); bu oturumun EN SIKI doğrulanmış bulgusu.
MODULE_SL_BUFFER_RATIO: dict[str, float] = {
    "fvg": 15.0,
    "ifvg": 15.0,
    "ob": 30.0,
    "trendline": 5.0,
}

# Modül başına, o modülün kendi seçili R'sinde (yukarıdaki MODULE_R_MULTIPLE)
# en düşük kazanma oranını / en düşük profit factor'ü verdiği (yani en çok
# SL yediği) zaman dilimi -- o modül o zaman diliminde işlem açmaz.
MODULE_DISABLED_TIMEFRAMES: dict[str, tuple[str, ...]] = {
    "fvg": ("H4",),   # win=%48.2, pf=1.40 @ R=1.5 -- 6 dilim icinde en dusuk
    "ifvg": ("H4",),  # win=%50.9, pf=1.55 @ R=1.5 -- 6 dilim icinde en dusuk
    "ob": ("W1",),    # win=%35.3, pf=1.64 @ R=3.0 -- 6 dilim icinde en dusuk (M30'a cok yakin, orneklem kucuk)
    "trendline": ("H4",),  # win=%51.9, pf=2.16 @ R=2.0 -- 6 dilim icinde en dusuk (digerleri 2.16-2.35 araliginda, cok yakin)
}

# Trendline'ın kendi 101 sembol calismasinda (2026-09-01), en kotu 10
# sembolde bile pozitif beklenti cikti (en dusuk: AUS200 +0.390R, PF=1.73)
# -- FVG/iFVG/OB'de gorulen "bazi semboller yapisal olarak uygun degil"
# orintusu Trendline'da YOK, EXCLUDED_SYMBOLS'a Trendline'dan kaynakli
# yeni bir sembol eklenmedi.

# Kullanici karariyla eklendi (2026-09-02, bkz. scratch_breakeven_sl_study.py):
# bir islem TP mesafesinin bu orani kadarini kat ettiginde SL girise
# (entry) cekilir -- islem sonra donerse zarar degil, tam olarak 0R
# (breakeven) sayilir. FVG/iFVG/OB'de (GOLD, BTCUSD, EURGBP havuzunda)
# dogrulandi: PF'de belirgin artis (orn. iFVG GOLD'da 1.65 -> 2.02),
# beklenti hafif artis, hicbir modulde kotulesme yok. Sadece FVG/iFVG/OB
# icin etkin -- Trendline test edilmedi (kullanicinin sorusu bu uc
# moduladi).
#
# GUNCELLEME (2026-09-02, esik taramasi): kullanici "%50 kat edilince
# cekilirse ne olur" diye sordu. Uc asamali sweep yapildi (bkz.
# scratch_breakeven_trigger_sweep_study.py + _spread_sweep_study.py,
# NOA_KONSEPTI_KAYNAK_ANALIZI.md "Breakeven esik taramasi" bolumu):
#   1) Kaba tarama (%30-80, spread=0): expectancy esik dustukce
#      monoton artiyor, %60 optimal DEGIL -- %50 bile %60'tan iyi
#      (0.368 vs 0.363).
#   2) Ince tarama (%5-30, spread=0): egri duzlesiyor ama tepe hala
#      bulunamadi (%5'te en iyi, 0.393) -- ama breakeven orani %46'ya
#      cikiyor, spread=0 varsayimi bu noktada supheli hale geliyor.
#   3) Spread-DAHIL tarama (temsili spread -- GOLD=0.25, BTCUSD=20,
#      EURGBP=0.0002 -- veri kaynaginda gercek spread hic kayitli
#      degil, bu degerler tipik piyasa degerleri, kalibre edilmedi):
#      siralama DEGISMEDI (dusuk esik hala daha iyi, %10 en iyisiydi),
#      ama mutlak degerler cok daha kotu -- havuzlanmis (3 sembol)
#      expectancy TUM esiklerde NEGATIFE dondu (BTCUSD/EURGBP'nin
#      FVG/OB modullerinde spread, dar SL'lere gore orantisiz buyuk).
#      GOLD tek basina her esikte pozitif kaldi.
# KARAR: siralama tutarli oldugu icin (dusuk esik = daha iyi, her 3
# testte de) ama en agresif ucu (%5-10, %46 breakeven orani) test
# edilmemis/kalibre edilmemis riskli bir bolge oldugu icin, kullanicinin
# ozgun sorusu olan VE her 3 testte de acikca %60'tan iyi cikan %50
# resmi deger olarak benimsendi -- asiri agresif (%10-30) uc, ayri bir
# calismada (gercek spread verisiyle) dogrulanmadan benimsenmedi.
BREAKEVEN_TRIGGER_PCT: float = 0.5
BREAKEVEN_ENABLED_MODULES: tuple[str, ...] = ("fvg", "ifvg", "ob")
