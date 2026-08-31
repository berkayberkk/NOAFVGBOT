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


# Global varsayılan yapılandırma nesnesi
DEFAULT_CONFIG = StrategyConfig()


# --- Sembol / modül bazlı strateji parametreleri (2026-08-31, 101 sembol x 6
# zaman dilimi R-katı calışmalarından -- fvg_tp_sl_study_results.json,
# ifvg_tp_sl_study_results.json, ob_tp_sl_study_results.json -- çıkarıldı) ---

# Her üç modülde de (FVG, iFVG, Order Block) aynı anda en kötü 10 sembol
# arasında çıkan, dolayısıyla yapısal olarak bu stratejiye uygun olmayan
# semboller. Sinyal üretiminden ve yeni testlerden tamamen çıkarılır --
# veri (data acquisition) listelerinden değil, sadece sinyal/backtest
# sembol listelerinden.
EXCLUDED_SYMBOLS: tuple[str, ...] = (
    "GERTECH30", "NASDAQ", "IT40", "GERMID50", "EURDKK", "USFANG",
)

# Modül başına TP hedefi (R katı). FVG ve iFVG'de beklenti (expectancy_r)
# R≈1.5'te tepe yapıp geriliyor; Order Block'ta ise test edilen tüm
# aralıkta (5.0R'ye kadar) hiç tepe yapmadan artmaya devam ediyor, PF ise
# R≈2.5-3.0'da tepe yapıyor -- bu yüzden OB için 3.0R (tepe PF bölgesi)
# seçildi. R>5.0 için OB'nin gerçek tepe noktası henüz ölçülmedi.
MODULE_R_MULTIPLE: dict[str, float] = {
    "fvg": 1.5,
    "ifvg": 1.5,
    "ob": 3.0,
}

# Modülün SL tamponu, kendi bölge boyutunun (FVG/iFVG: gap, OB: gövde) katı.
MODULE_SL_BUFFER_RATIO: dict[str, float] = {
    "fvg": 1.0,
    "ifvg": 1.0,
    "ob": 3.0,
}

# Modül başına, o modülün kendi seçili R'sinde (yukarıdaki MODULE_R_MULTIPLE)
# en düşük kazanma oranını / en düşük profit factor'ü verdiği (yani en çok
# SL yediği) zaman dilimi -- o modül o zaman diliminde işlem açmaz.
MODULE_DISABLED_TIMEFRAMES: dict[str, tuple[str, ...]] = {
    "fvg": ("H4",),   # win=%48.2, pf=1.40 @ R=1.5 -- 6 dilim icinde en dusuk
    "ifvg": ("H4",),  # win=%50.9, pf=1.55 @ R=1.5 -- 6 dilim icinde en dusuk
    "ob": ("W1",),    # win=%35.3, pf=1.64 @ R=3.0 -- 6 dilim icinde en dusuk (M30'a cok yakin, orneklem kucuk)
}
