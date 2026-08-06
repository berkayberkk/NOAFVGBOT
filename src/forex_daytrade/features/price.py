"""Price-shape feature generators: range, wicks, and body size.

Each feature is a pure function of a single bar's own OHLC values — none of
them look at any other row, so there is no warm-up/NaN period here (unlike
`returns.py` or `volatility.py`).
"""

from __future__ import annotations

import pandas as pd

from forex_daytrade.features.base import Feature
from forex_daytrade.features.registry import register_feature


@register_feature
class HighLowRangeFeature(Feature):
    """Bar range: `high - low`."""

    name = "high_low_range"
    required_columns = frozenset({"high", "low"})
    generated_columns = frozenset({"high_low_range"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["high_low_range"] = df["high"] - df["low"]
        self.validate_output(result)
        return result


@register_feature
class CloseOpenDistanceFeature(Feature):
    """Signed distance from `open` to `close`: `close - open`."""

    name = "close_open_distance"
    required_columns = frozenset({"open", "close"})
    generated_columns = frozenset({"close_open_distance"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["close_open_distance"] = df["close"] - df["open"]
        self.validate_output(result)
        return result


@register_feature
class BodySizeFeature(Feature):
    """Absolute candle body size: `abs(close - open)`."""

    name = "body_size"
    required_columns = frozenset({"open", "close"})
    generated_columns = frozenset({"body_size"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["body_size"] = (df["close"] - df["open"]).abs()
        self.validate_output(result)
        return result


@register_feature
class UpperWickFeature(Feature):
    """Upper wick length: `high - max(open, close)`."""

    name = "upper_wick"
    required_columns = frozenset({"open", "high", "close"})
    generated_columns = frozenset({"upper_wick"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
        self.validate_output(result)
        return result


@register_feature
class LowerWickFeature(Feature):
    """Lower wick length: `min(open, close) - low`."""

    name = "lower_wick"
    required_columns = frozenset({"open", "low", "close"})
    generated_columns = frozenset({"lower_wick"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
        self.validate_output(result)
        return result
