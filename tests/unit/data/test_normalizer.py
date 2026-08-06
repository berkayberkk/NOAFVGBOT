"""Unit tests for forex_daytrade.data.normalizer."""

from datetime import UTC, datetime

import pandas as pd

from forex_daytrade.data.normalizer import NORMALIZED_COLUMNS, normalize_bars, normalize_timestamps


def _epoch_for_broker_wall_clock(year: int, month: int, day: int, hour: int, minute: int) -> int:
    """Unix epoch whose UTC wall-clock digits equal the given broker-local time.

    This mirrors how MT5's raw `time` field encodes broker-local time.
    """
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp())


def _raw_bars(times: list[int]) -> pd.DataFrame:
    n = len(times)
    return pd.DataFrame(
        {
            "time": times,
            "open": [1.10 + i * 0.01 for i in range(n)],
            "high": [1.15 + i * 0.01 for i in range(n)],
            "low": [1.05 + i * 0.01 for i in range(n)],
            "close": [1.12 + i * 0.01 for i in range(n)],
            "tick_volume": [100 + i for i in range(n)],
            "spread": [10 + i for i in range(n)],
            "real_volume": [0] * n,
        }
    )


def test_normalize_timestamps_winter_offset_athens() -> None:
    winter_epoch = _epoch_for_broker_wall_clock(2024, 1, 15, 12, 0)
    df = _raw_bars([winter_epoch])

    result = normalize_timestamps(df, "Europe/Athens")

    assert result.loc[0, "broker_timestamp"] == pd.Timestamp("2024-01-15T12:00:00+02:00")
    assert result.loc[0, "timestamp_utc"] == pd.Timestamp("2024-01-15T10:00:00Z")


def test_normalize_timestamps_summer_offset_athens_is_dst_aware() -> None:
    summer_epoch = _epoch_for_broker_wall_clock(2024, 7, 15, 12, 0)
    df = _raw_bars([summer_epoch])

    result = normalize_timestamps(df, "Europe/Athens")

    assert result.loc[0, "broker_timestamp"] == pd.Timestamp("2024-07-15T12:00:00+03:00")
    assert result.loc[0, "timestamp_utc"] == pd.Timestamp("2024-07-15T09:00:00Z")


def test_normalize_timestamps_utc_broker_timezone_is_identity() -> None:
    epoch = _epoch_for_broker_wall_clock(2024, 3, 1, 8, 30)
    df = _raw_bars([epoch])

    result = normalize_timestamps(df, "UTC")

    assert result.loc[0, "broker_timestamp"] == result.loc[0, "timestamp_utc"]
    assert result.loc[0, "timestamp_utc"] == pd.Timestamp("2024-03-01T08:30:00Z")


def test_normalize_bars_produces_canonical_schema_sorted_ascending() -> None:
    later = _epoch_for_broker_wall_clock(2024, 3, 1, 9, 0)
    earlier = _epoch_for_broker_wall_clock(2024, 3, 1, 8, 0)
    df = _raw_bars([later, earlier])

    result = normalize_bars(df, "EURUSD", "UTC")

    assert list(result.columns) == NORMALIZED_COLUMNS
    assert result["timestamp_utc"].is_monotonic_increasing
    assert (result["symbol"] == "EURUSD").all()
