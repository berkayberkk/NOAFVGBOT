"""Unit tests for forex_daytrade.features.price."""

from __future__ import annotations

import pandas as pd

from forex_daytrade.features.price import (
    BodySizeFeature,
    CloseOpenDistanceFeature,
    HighLowRangeFeature,
    LowerWickFeature,
    UpperWickFeature,
)


def test_high_low_range(sample_ohlcv_df: pd.DataFrame) -> None:
    feature = HighLowRangeFeature()
    assert feature.required_columns == frozenset({"high", "low"})
    result = feature.compute(sample_ohlcv_df[["high", "low"]])
    expected = sample_ohlcv_df["high"] - sample_ohlcv_df["low"]
    pd.testing.assert_series_equal(result["high_low_range"], expected, check_names=False)
    assert (result["high_low_range"] >= 0).all()


def test_close_open_distance(sample_ohlcv_df: pd.DataFrame) -> None:
    feature = CloseOpenDistanceFeature()
    assert feature.required_columns == frozenset({"open", "close"})
    result = feature.compute(sample_ohlcv_df[["open", "close"]])
    expected = sample_ohlcv_df["close"] - sample_ohlcv_df["open"]
    pd.testing.assert_series_equal(result["close_open_distance"], expected, check_names=False)


def test_body_size_is_always_non_negative(sample_ohlcv_df: pd.DataFrame) -> None:
    feature = BodySizeFeature()
    result = feature.compute(sample_ohlcv_df[["open", "close"]])
    expected = (sample_ohlcv_df["close"] - sample_ohlcv_df["open"]).abs()
    pd.testing.assert_series_equal(result["body_size"], expected, check_names=False)
    assert (result["body_size"] >= 0).all()


def test_upper_wick(sample_ohlcv_df: pd.DataFrame) -> None:
    feature = UpperWickFeature()
    result = feature.compute(sample_ohlcv_df[["open", "high", "close"]])
    expected = sample_ohlcv_df["high"] - sample_ohlcv_df[["open", "close"]].max(axis=1)
    pd.testing.assert_series_equal(result["upper_wick"], expected, check_names=False)
    assert (result["upper_wick"] >= 0).all()


def test_lower_wick(sample_ohlcv_df: pd.DataFrame) -> None:
    feature = LowerWickFeature()
    result = feature.compute(sample_ohlcv_df[["open", "low", "close"]])
    expected = sample_ohlcv_df[["open", "close"]].min(axis=1) - sample_ohlcv_df["low"]
    pd.testing.assert_series_equal(result["lower_wick"], expected, check_names=False)
    assert (result["lower_wick"] >= 0).all()


def test_price_features_produce_no_nans(sample_ohlcv_df: pd.DataFrame) -> None:
    for feature_cls in (
        HighLowRangeFeature,
        CloseOpenDistanceFeature,
        BodySizeFeature,
        UpperWickFeature,
        LowerWickFeature,
    ):
        feature = feature_cls()
        result = feature.compute(sample_ohlcv_df[list(feature.required_columns)])
        assert result.notna().all().all()
