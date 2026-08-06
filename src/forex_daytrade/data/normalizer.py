"""Timestamp and schema normalization for raw MT5 bar data."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

RAW_TIME_COLUMN = "time"
NORMALIZED_COLUMNS = [
    "timestamp_utc",
    "broker_timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
]

_UTC = ZoneInfo("UTC")


def normalize_timestamps(df: pd.DataFrame, broker_timezone: str) -> pd.DataFrame:
    """Add timezone-safe `broker_timestamp` and `timestamp_utc` columns.

    MT5's raw `time` column is a Unix timestamp whose wall-clock value
    represents the broker server's local time, not true UTC. This function
    interprets it as `broker_timezone` (DST-aware, via `zoneinfo`) and
    derives true UTC from that, so downstream consumers never need to
    reason about broker time.
    """
    if RAW_TIME_COLUMN not in df.columns:
        raise KeyError(f"Expected raw MT5 column {RAW_TIME_COLUMN!r} not found")

    result = df.copy()
    naive_broker_time = pd.to_datetime(
        result[RAW_TIME_COLUMN], unit="s", utc=True
    ).dt.tz_localize(None)
    broker_tz = ZoneInfo(broker_timezone)
    broker_timestamp = naive_broker_time.dt.tz_localize(
        broker_tz, ambiguous="NaT", nonexistent="shift_forward"
    )
    result["broker_timestamp"] = broker_timestamp
    result["timestamp_utc"] = broker_timestamp.dt.tz_convert(_UTC)
    return result


def normalize_bars(df: pd.DataFrame, symbol: str, broker_timezone: str) -> pd.DataFrame:
    """Normalize raw MT5 bar data into the canonical internal schema.

    Converts timestamps to UTC, attaches the symbol, sorts chronologically,
    and returns only the canonical columns in a fixed order.
    """
    normalized = normalize_timestamps(df, broker_timezone)
    normalized["symbol"] = symbol
    normalized = normalized.sort_values("timestamp_utc").reset_index(drop=True)
    return normalized[NORMALIZED_COLUMNS]
