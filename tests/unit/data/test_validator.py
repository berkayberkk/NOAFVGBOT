"""Unit tests for forex_daytrade.data.validator."""

from datetime import UTC, datetime

import pandas as pd

from forex_daytrade.data.types import IngestionTimeframe
from forex_daytrade.data.validator import validate_dataset
from forex_daytrade.domain.validation import Severity


def _valid_m5_bars(n: int = 5, start: str = "2024-03-04T08:00:00Z") -> pd.DataFrame:
    """Five consecutive, well-formed weekday M5 bars (2024-03-04 is a Monday)."""
    timestamps = pd.date_range(start=start, periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "broker_timestamp": timestamps,
            "symbol": ["EURUSD"] * n,
            "open": [1.10 + i * 0.001 for i in range(n)],
            "high": [1.12 + i * 0.001 for i in range(n)],
            "low": [1.08 + i * 0.001 for i in range(n)],
            "close": [1.11 + i * 0.001 for i in range(n)],
            "tick_volume": [100] * n,
            "spread": [10] * n,
            "real_volume": [0] * n,
        }
    )


def test_valid_dataset_has_no_issues() -> None:
    report = validate_dataset(_valid_m5_bars(), "EURUSD", IngestionTimeframe.M5)
    assert report.is_valid
    assert report.issues == ()
    assert report.total_rows == 5


def test_empty_dataset_is_an_error() -> None:
    empty = _valid_m5_bars(0)
    report = validate_dataset(empty, "EURUSD", IngestionTimeframe.M5)
    assert not report.is_valid
    assert report.issues[0].check == "empty_dataset"
    assert report.issues[0].severity == Severity.ERROR


def test_duplicate_timestamps_is_an_error() -> None:
    df = _valid_m5_bars()
    df.loc[1, "timestamp_utc"] = df.loc[0, "timestamp_utc"]
    report = validate_dataset(df, "EURUSD", IngestionTimeframe.M5)
    checks = {issue.check: issue for issue in report.issues}
    assert "duplicate_timestamps" in checks
    assert checks["duplicate_timestamps"].severity == Severity.ERROR
    assert not report.is_valid


def test_negative_price_is_an_error() -> None:
    df = _valid_m5_bars()
    df.loc[2, "close"] = -1.0
    report = validate_dataset(df, "EURUSD", IngestionTimeframe.M5)
    checks = {issue.check: issue for issue in report.issues}
    assert "negative_or_zero_prices" in checks
    assert checks["negative_or_zero_prices"].severity == Severity.ERROR


def test_ohlc_inconsistency_is_an_error() -> None:
    df = _valid_m5_bars()
    df.loc[0, "high"] = df.loc[0, "low"] - 0.01  # high below low: impossible
    report = validate_dataset(df, "EURUSD", IngestionTimeframe.M5)
    checks = {issue.check: issue for issue in report.issues}
    assert "ohlc_consistency" in checks
    assert checks["ohlc_consistency"].severity == Severity.ERROR


def test_future_timestamp_is_an_error() -> None:
    df = _valid_m5_bars()
    now = datetime(2024, 3, 4, 8, 10, tzinfo=UTC)
    report = validate_dataset(df, "EURUSD", IngestionTimeframe.M5, now=now)
    checks = {issue.check: issue for issue in report.issues}
    assert "future_timestamps" in checks
    assert checks["future_timestamps"].severity == Severity.ERROR


def test_weekend_bar_is_a_warning() -> None:
    df = _valid_m5_bars(1, start="2024-03-09T08:00:00Z")  # Saturday
    report = validate_dataset(df, "EURUSD", IngestionTimeframe.M5)
    checks = {issue.check: issue for issue in report.issues}
    assert "weekend_bars" in checks
    assert checks["weekend_bars"].severity == Severity.WARNING
    assert report.is_valid  # warnings alone do not invalidate the dataset


def test_spread_anomaly_is_a_warning() -> None:
    df = _valid_m5_bars()
    df.loc[0, "spread"] = 5000
    report = validate_dataset(df, "EURUSD", IngestionTimeframe.M5)
    checks = {issue.check: issue for issue in report.issues}
    assert "spread_anomalies" in checks
    assert checks["spread_anomalies"].severity == Severity.WARNING


def test_missing_bar_gap_is_a_warning() -> None:
    df = _valid_m5_bars(n=6)
    df = df.drop(index=2).reset_index(drop=True)  # remove one weekday bar
    report = validate_dataset(df, "EURUSD", IngestionTimeframe.M5)
    checks = {issue.check: issue for issue in report.issues}
    assert "missing_bars" in checks
    assert checks["missing_bars"].severity == Severity.WARNING


def test_weekend_gap_is_not_flagged_as_missing_bars() -> None:
    # Friday 21:55 UTC directly followed by Sunday 22:00 UTC: a normal
    # weekend market closure, not a data gap.
    friday_bar = _valid_m5_bars(1, start="2024-03-08T21:55:00Z")
    sunday_bar = _valid_m5_bars(1, start="2024-03-10T22:00:00Z")
    df = pd.concat([friday_bar, sunday_bar], ignore_index=True)
    report = validate_dataset(df, "EURUSD", IngestionTimeframe.M5)
    checks = {issue.check: issue for issue in report.issues}
    assert "missing_bars" not in checks
