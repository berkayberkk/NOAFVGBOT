"""
NOAFVGBOT V2.DATA.1 — Read-Only MT5 Historical Acquisition Module.

Provides read-only historical M1 data acquisition from MetaTrader 5 with bounded chunking,
symbol discovery (XAUUSD / GOLD), forming bar exclusion, and UTC timestamp normalization.

INVARIANTS:
- READ-ONLY: Never invokes order_send, order_check, or trade execution functions.
- Fetches M1 ONLY; higher timeframes are derived via V2.1 resampling.
- Excludes forming bars; includes only completed candles.
- Normalizes open and close timestamps strictly to UTC string format.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from research.v2.data.models import CandleV2, Timeframe

logger = logging.getLogger(__name__)


import os

def discover_broker_symbol() -> Tuple[str, str]:
    """Discovers available broker symbol for Gold/XAUUSD."""
    research_symbol = "XAUUSD"
    broker_symbol = "XAUUSD"

    if os.environ.get("USE_LIVE_MT5") == "1":
        try:
            import MetaTrader5 as mt5
            if mt5.initialize():
                symbols = mt5.symbols_get()
                if symbols:
                    sym_names = [s.name for s in symbols]
                    for candidate in ["XAUUSD", "GOLD", "XAUUSD.", "XAUUSDm", "XAUUSD_"]:
                        if candidate in sym_names:
                            broker_symbol = candidate
                            break
                mt5.shutdown()
        except Exception as e:
            logger.info(f"MT5 unavailable during symbol discovery: {e}")

    return research_symbol, broker_symbol


def fetch_historical_m1_chunks(
    broker_symbol: str,
    start_date: datetime,
    end_date: datetime,
    chunk_days: int = 30,
) -> List[Dict[str, Any]]:
    """
    Fetches raw historical M1 rates in bounded chunks from MT5 if enabled.
    Returns list of raw rates dictionaries. Fast fallback if MT5 is disabled/offline.
    """
    raw_rates: List[Dict[str, Any]] = []

    if os.environ.get("USE_LIVE_MT5") == "1":
        try:
            import MetaTrader5 as mt5
            if mt5.initialize():
                curr_start = start_date
                while curr_start < end_date:
                    curr_end = min(curr_start + timedelta(days=chunk_days), end_date)

                    rates = mt5.copy_rates_range(
                        broker_symbol,
                        mt5.TIMEFRAME_M1,
                        curr_start,
                        curr_end,
                    )

                    if rates is not None and len(rates) > 0:
                        for r in rates:
                            dt_open = datetime.fromtimestamp(r['time'], tz=timezone.utc)
                            raw_rates.append({
                                "time": r['time'],
                                "timestamp_open_utc": dt_open.strftime("%Y-%m-%d %H:%M:%S"),
                                "open": float(r['open']),
                                "high": float(r['high']),
                                "low": float(r['low']),
                                "close": float(r['close']),
                                "tick_volume": int(r['tick_volume']),
                                "spread": int(r['spread']) if 'spread' in r.dtype.names else 0,
                            })

                    curr_start = curr_end

                mt5.shutdown()
        except Exception as e:
            logger.info(f"MT5 acquisition skipped: {e}")

    return raw_rates


def convert_raw_to_canonical_m1(raw_rates: List[Dict[str, Any]]) -> List[CandleV2]:
    """
    Converts raw broker rates into canonical CandleV2 series.
    Excludes forming candles strictly.
    """
    now_utc = datetime.now(timezone.utc)
    canonical: List[CandleV2] = []
    seen_open_ts = set()

    for r in raw_rates:
        ts_open_str = r.get("timestamp_open_utc")
        if not ts_open_str:
            dt_open = datetime.fromtimestamp(r["time"], tz=timezone.utc)
            ts_open_str = dt_open.strftime("%Y-%m-%d %H:%M:%S")

        dt_open = datetime.fromisoformat(ts_open_str).replace(tzinfo=timezone.utc)
        dt_close = dt_open + timedelta(seconds=60)
        ts_close_str = dt_close.strftime("%Y-%m-%d %H:%M:%S")

        # Exclude forming bar (close > now)
        if dt_close > now_utc:
            continue

        if ts_open_str in seen_open_ts:
            continue
        seen_open_ts.add(ts_open_str)

        c = CandleV2(
            timestamp_open_utc=ts_open_str,
            timestamp_close_utc=ts_close_str,
            timeframe=Timeframe.M1,
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r.get("tick_volume", 10.0)),
        )
        canonical.append(c)

    return sorted(canonical, key=lambda c: c.timestamp_open_utc)


def generate_synthetic_m1_dataset(
    start_ts: str = "2024-01-01 00:00:00",
    count: int = 1000,
    start_price: float = 2000.0,
) -> Tuple[List[Dict[str, Any]], List[CandleV2]]:
    """Generates synthetic deterministic M1 raw and canonical data for testing without MT5 network dependency."""
    dt = datetime.fromisoformat(start_ts).replace(tzinfo=timezone.utc)
    raw_list: List[Dict[str, Any]] = []
    p = start_price

    for i in range(count):
        # Skip weekend candles for synthetic realism (Saturday 00:00 to Sunday 22:00)
        if dt.weekday() == 5 or (dt.weekday() == 6 and dt.hour < 22):
            dt += timedelta(minutes=1)
            continue

        # Daily break 22:00-23:00 UTC
        if dt.hour == 22 and dt.minute < 59:
            dt += timedelta(minutes=1)
            continue

        ts_open = dt.strftime("%Y-%m-%d %H:%M:%S")
        ts_close = (dt + timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")

        raw_item = {
            "time": int(dt.timestamp()),
            "timestamp_open_utc": ts_open,
            "open": p,
            "high": p + 1.5,
            "low": p - 1.2,
            "close": p + 0.3,
            "tick_volume": 50,
            "spread": 30,
        }
        raw_list.append(raw_item)
        dt += timedelta(minutes=1)
        p += 0.1

    canonical = convert_raw_to_canonical_m1(raw_list)
    return raw_list, canonical
