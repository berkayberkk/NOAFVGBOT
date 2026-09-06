"""
MT5'ten canli mum verisi cekme + veri butunlugu kontrolu (bkz. proje talebi
"12. VERI BUTUNLUGU"): yeterli candle, dogru/sirali timestamp, duplicate
kontrolu, eksik-mum (gap) kontrolu, stale-data kontrolu.

Hicbir strateji mantigi burada YOK -- sadece MT5 -> strategy'nin bekledigi
candle dict formatina (time/open/high/low/close/tick_volume) donusum.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from scanner.timeframes import TIMEFRAME_SPECS

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False


@dataclass
class FetchResult:
    status: str  # "OK" | "DATA_INCOMPLETE" | "SYMBOL_UNAVAILABLE" | "FETCH_ERROR"
    candles: list[dict] | None = None
    reason: str | None = None
    data_through: str | None = None  # ISO -- son mumun kapanis zamani
    n_candles: int = 0


def fetch_candles(symbol: str, tf_name: str, mt5_module=None) -> FetchResult:
    """mt5_module: testlerde sahte bir MT5 arayuzu enjekte etmek icin (bkz.
    tests/test_mt5_shadow.py'deki ayni desen) -- None ise gercek MetaTrader5
    paketi kullanilir."""
    m = mt5_module if mt5_module is not None else (mt5 if _MT5_AVAILABLE else None)
    if m is None:
        return FetchResult(status="FETCH_ERROR", reason="MetaTrader5 paketi yuklu degil")

    spec = TIMEFRAME_SPECS[tf_name]
    mt5_tf = getattr(m, spec.mt5_constant_name, None)
    if mt5_tf is None:
        return FetchResult(status="FETCH_ERROR", reason=f"bilinmeyen MT5 timeframe sabiti: {spec.mt5_constant_name}")

    if not m.initialize():
        return FetchResult(status="FETCH_ERROR", reason=f"mt5.initialize() basarisiz: {m.last_error()}")

    info = m.symbol_info(symbol)
    if info is None:
        return FetchResult(status="SYMBOL_UNAVAILABLE", reason=f"'{symbol}' bu broker'da Market Watch'ta bulunamadi (isim uyusmazligi olabilir)")
    if not info.visible:
        if not m.symbol_select(symbol, True):
            return FetchResult(status="SYMBOL_UNAVAILABLE", reason=f"'{symbol}' Market Watch'a eklenemedi")

    try:
        rates = m.copy_rates_from_pos(symbol, mt5_tf, 0, spec.fetch_bars)
    except Exception as e:
        return FetchResult(status="FETCH_ERROR", reason=f"{type(e).__name__}: {e}")

    if rates is None or len(rates) == 0:
        return FetchResult(status="DATA_INCOMPLETE", reason=f"MT5'ten hic mum donmedi: {m.last_error()}")

    # --- Veri butunlugu kontrolleri ---
    times = [r["time"] for r in rates]
    if len(times) != len(set(times)):
        return FetchResult(status="DATA_INCOMPLETE", reason="duplicate mum (ayni zaman damgasi birden fazla kez)")
    if times != sorted(times):
        return FetchResult(status="DATA_INCOMPLETE", reason="mumlar zaman siralamasina gore sirali degil")
    if len(rates) < spec.min_required_bars:
        return FetchResult(
            status="DATA_INCOMPLETE",
            reason=f"yetersiz mum: {len(rates)} < gereken min {spec.min_required_bars}",
            n_candles=len(rates),
        )

    candles = [
        {
            "time": datetime.fromtimestamp(int(r["time"]), tz=timezone.utc),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
        }
        for r in rates
    ]

    data_through = candles[-1]["time"]

    # Stale-data kontrolu: son mumun kapanisindan bu yana gecen sure, beklenen
    # bar araligina gore COK uzunsa (piyasa kapali olsa bile -- W1/D1'de hafta
    # sonu gecikmesi normal, bu yuzden cok gevsek bir esik: 5x bar suresi VE
    # en az 3 gun, hangisi buyukse).
    from scanner.timeframes import TIMEFRAMES  # noqa: F401 (dokumantasyon amacli)
    bar_seconds = {"M30": 1800, "H1": 3600, "H2": 7200, "H4": 14400, "D1": 86400, "W1": 604800}[tf_name]
    age_seconds = (datetime.now(tz=timezone.utc) - data_through).total_seconds()
    stale_threshold = max(bar_seconds * 5, 3 * 86400)
    if age_seconds > stale_threshold:
        return FetchResult(
            status="DATA_INCOMPLETE",
            reason=f"veri bayat: son mum {age_seconds/3600:.1f} saat once (esik {stale_threshold/3600:.1f} saat)",
            candles=candles, data_through=data_through.isoformat(), n_candles=len(candles),
        )

    return FetchResult(status="OK", candles=candles, data_through=data_through.isoformat(), n_candles=len(candles))
