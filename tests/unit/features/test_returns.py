"""Unit tests for forex_daytrade.features.returns."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forex_daytrade.features.base import MissingRequiredColumnsError
from forex_daytrade.features.returns import LogReturnFeature, SimpleReturnFeature


def test_log_return_metadata() -> None:
    feature = LogReturnFeature()
    assert feature.name == "log_return"
    assert feature.required_columns == frozenset({"close"})
    assert feature.generated_columns == frozenset({"log_return"})


def test_log_return_values(sample_ohlcv_df: pd.DataFrame) -> None:
    result = LogReturnFeature().compute(sample_ohlcv_df[["close"]])
    expected = np.log(sample_ohlcv_df["close"] / sample_ohlcv_df["close"].shift(1))
    pd.testing.assert_series_equal(result["log_return"], expected, check_names=False)


def test_log_return_first_row_is_nan(sample_ohlcv_df: pd.DataFrame) -> None:
    result = LogReturnFeature().compute(sample_ohlcv_df[["close"]])
    assert pd.isna(result["log_return"].iloc[0])
    assert result["log_return"].iloc[1:].notna().all()


def test_log_return_missing_column_raises() -> None:
    with pytest.raises(MissingRequiredColumnsError):
        LogReturnFeature().compute(pd.DataFrame({"open": [1.0]}))


def test_simple_return_metadata() -> None:
    feature = SimpleReturnFeature()
    assert feature.name == "simple_return"
    assert feature.required_columns == frozenset({"close"})
    assert feature.generated_columns == frozenset({"simple_return"})


def test_simple_return_values(sample_ohlcv_df: pd.DataFrame) -> None:
    result = SimpleReturnFeature().compute(sample_ohlcv_df[["close"]])
    expected = sample_ohlcv_df["close"].pct_change()
    pd.testing.assert_series_equal(result["simple_return"], expected, check_names=False)


def test_simple_return_first_row_is_nan(sample_ohlcv_df: pd.DataFrame) -> None:
    result = SimpleReturnFeature().compute(sample_ohlcv_df[["close"]])
    assert pd.isna(result["simple_return"].iloc[0])
