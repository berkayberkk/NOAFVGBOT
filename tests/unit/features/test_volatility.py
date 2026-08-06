"""Unit tests for forex_daytrade.features.volatility."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from forex_daytrade.features.volatility import RollingStdFeature, TrueRangeFeature


def _closes_df(closes: list[float]) -> pd.DataFrame:
    start = datetime(2024, 3, 4, 8, 0, tzinfo=UTC)
    timestamps = [start + timedelta(minutes=5 * i) for i in range(len(closes))]
    return pd.DataFrame({"timestamp_utc": pd.to_datetime(timestamps, utc=True), "close": closes})


def test_true_range_metadata() -> None:
    feature = TrueRangeFeature()
    assert feature.name == "true_range"
    assert feature.required_columns == frozenset({"high", "low", "close"})
    assert feature.generated_columns == frozenset({"true_range"})


def test_true_range_first_row_falls_back_to_high_low(sample_ohlcv_df: pd.DataFrame) -> None:
    result = TrueRangeFeature().compute(sample_ohlcv_df[["high", "low", "close"]])
    expected_first = sample_ohlcv_df["high"].iloc[0] - sample_ohlcv_df["low"].iloc[0]
    assert result["true_range"].iloc[0] == pytest.approx(expected_first)
    assert result["true_range"].notna().all()


def test_true_range_uses_previous_close_when_it_widens_the_range() -> None:
    df = pd.DataFrame(
        {
            "high": [1.10, 1.12],
            "low": [1.08, 1.11],
            "close": [1.09, 1.115],
        }
    )
    result = TrueRangeFeature().compute(df)
    # Bar 2: high-low=0.01, high-prev_close=1.12-1.09=0.03, low-prev_close=|1.11-1.09|=0.02
    assert result["true_range"].iloc[1] == pytest.approx(0.03)


def test_true_range_is_never_negative(sample_ohlcv_df: pd.DataFrame) -> None:
    result = TrueRangeFeature().compute(sample_ohlcv_df[["high", "low", "close"]])
    assert (result["true_range"] >= 0).all()


def test_rolling_std_metadata() -> None:
    feature = RollingStdFeature()
    assert feature.name == "rolling_std_20"
    assert feature.required_columns == frozenset({"close"})
    assert feature.generated_columns == frozenset({"rolling_std_20"})


def test_rolling_std_all_nan_when_fewer_than_window_rows(sample_ohlcv_df: pd.DataFrame) -> None:
    # sample_ohlcv_df has 5 rows, well under the 20-bar window.
    result = RollingStdFeature().compute(sample_ohlcv_df[["close"]])
    assert result["rolling_std_20"].isna().all()


def test_rolling_std_matches_manual_calculation_once_window_is_full() -> None:
    closes = [1.10 + 0.001 * i for i in range(25)]
    df = _closes_df(closes)
    result = RollingStdFeature().compute(df[["close"]])

    log_return = np.log(df["close"] / df["close"].shift(1))
    expected = log_return.rolling(window=20).std()
    pd.testing.assert_series_equal(result["rolling_std_20"], expected, check_names=False)

    # log_return itself has 1 leading NaN (no prior bar), so a full 20-value
    # window of log returns isn't available until index 20 (0-indexed).
    assert result["rolling_std_20"].iloc[:20].isna().all()
    assert result["rolling_std_20"].iloc[20:].notna().all()
