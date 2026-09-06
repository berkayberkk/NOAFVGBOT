"""
Taranacak 6 zaman dilimi -- MT5'in kendi native TIMEFRAME_* sabitleriyle
birebir eşleşiyor (resample gerekmiyor, MT5 Python API'si H2/D1/W1'i de
dogrudan destekliyor -- dogrulandi: mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_W1, 0, 5)).

Her zaman dilimi icin WARMUP_BARS: strategy modullerinin ihtiyac duydugu
maksimum warm-up penceresinden (ob_premium_discount_lookback=48,
volume_confirm_period=20, trendline_swing_lookback=10 + known_index gecikmesi,
ATR=14) GUVENLI PAYLA turetildi -- + sinyallerin "guncel" sayilabilmesi icin
yeterli taze bar sayisi (recency window).
"""
from dataclasses import dataclass

TIMEFRAMES = ["M30", "H1", "H2", "H4", "D1", "W1"]

SHORT_TERM = ("M30", "H1")
MEDIUM_TERM = ("H2", "H4")
HIGHER_TIMEFRAME = ("D1", "W1")


def tf_category(tf: str) -> str:
    if tf in SHORT_TERM:
        return "SHORT_TERM"
    if tf in MEDIUM_TERM:
        return "MEDIUM_TERM"
    return "HIGHER_TIMEFRAME"


@dataclass(frozen=True)
class TimeframeSpec:
    name: str
    mt5_constant_name: str  # mt5.TIMEFRAME_<X> -- gercek sabit data_fetch.py'de cozuluyor (import MT5 bagimliligi burada olmasin diye)
    fetch_bars: int         # MT5'ten cekilecek bar sayisi (warmup + recency)
    min_required_bars: int  # bundan azsa DATA_INCOMPLETE


TIMEFRAME_SPECS: dict[str, TimeframeSpec] = {
    "M30": TimeframeSpec("M30", "TIMEFRAME_M30", fetch_bars=2000, min_required_bars=200),
    "H1":  TimeframeSpec("H1",  "TIMEFRAME_H1",  fetch_bars=2000, min_required_bars=200),
    "H2":  TimeframeSpec("H2",  "TIMEFRAME_H2",  fetch_bars=1500, min_required_bars=150),
    "H4":  TimeframeSpec("H4",  "TIMEFRAME_H4",  fetch_bars=1000, min_required_bars=120),
    "D1":  TimeframeSpec("D1",  "TIMEFRAME_D1",  fetch_bars=750,  min_required_bars=100),
    "W1":  TimeframeSpec("W1",  "TIMEFRAME_W1",  fetch_bars=300,  min_required_bars=60),
}
