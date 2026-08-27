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
