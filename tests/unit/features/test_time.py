"""Unit tests for forex_daytrade.features.time."""

from __future__ import annotations

import pandas as pd
import pytest

from forex_daytrade.features.base import MissingRequiredColumnsError
from forex_daytrade.features.time import (
    DayOfWeekFeature,
    HourOfDayFeature,
    SessionPlaceholderFeature,
)


def test_hour_of_day(sample_ohlcv_df: pd.DataFrame) -> None:
    feature = HourOfDayFeature()
    assert feature.required_columns == frozenset({"timestamp_utc"})
    result = feature.compute(sample_ohlcv_df[["timestamp_utc"]])
    assert list(result["hour_of_day"]) == [8, 8, 8, 8, 8]


def test_hour_of_day_missing_column_raises() -> None:
    with pytest.raises(MissingRequiredColumnsError):
        HourOfDayFeature().compute(pd.DataFrame({"open": [1.0]}))


def test_day_of_week_monday_is_zero(sample_ohlcv_df: pd.DataFrame) -> None:
    # 2024-03-04 is a Monday.
    feature = DayOfWeekFeature()
    result = feature.compute(sample_ohlcv_df[["timestamp_utc"]])
    assert list(result["day_of_week"]) == [0, 0, 0, 0, 0]


def test_session_placeholder_passes_through_session_column(sample_ohlcv_df: pd.DataFrame) -> None:
    feature = SessionPlaceholderFeature()
    assert feature.required_columns == frozenset({"session"})
    result = feature.compute(sample_ohlcv_df[["session"]])
    assert list(result["session_placeholder"]) == ["london"] * 5


def test_session_placeholder_missing_column_raises() -> None:
    with pytest.raises(MissingRequiredColumnsError):
        SessionPlaceholderFeature().compute(pd.DataFrame({"open": [1.0]}))
