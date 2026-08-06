"""Volatility feature generators.

Raw statistical dispersion measures only — no EMA, RSI, ATR, MACD, or any
other indicator that encodes a strategy decision (e.g. a smoothing period
chosen to tune signal responsiveness). `true_range` here is the raw True
Range value for each bar, not the smoothed/averaged ATR.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from forex_daytrade.features.base import Feature
from forex_daytrade.features.registry import register_feature

_ROLLING_STD_WINDOW = 20


@register_feature
class TrueRangeFeature(Feature):
    """True range: the greatest of `high-low`, `abs(high-prev_close)`, and
    `abs(low-prev_close)`.

    The first bar has no previous close, so `prev_close` is NaN for that
    row; pandas' NaN-skipping `max` then falls back to `high-low` for it,
    which is the standard convention for a series' first true-range value.
    """

    name = "true_range"
    required_columns = frozenset({"high", "low", "close"})
    generated_columns = frozenset({"true_range"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        prev_close = df["close"].shift(1)
        ranges = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        )
        result = pd.DataFrame(index=df.index)
        result["true_range"] = ranges.max(axis=1)
        self.validate_output(result)
        return result


@register_feature
class RollingStdFeature(Feature):
    """Rolling standard deviation of log returns over a fixed 20-bar window.

    The window is fixed (not a constructor parameter) to keep this a plain,
    zero-argument baseline feature like the others in this sprint; a
    configurable-window variant is natural future work if downstream
    consumers need it, not implemented speculatively here.
    """

    name = "rolling_std_20"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"rolling_std_20"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        log_return = pd.Series(np.log(df["close"] / df["close"].shift(1)), index=df.index)
        result = pd.DataFrame(index=df.index)
        result["rolling_std_20"] = log_return.rolling(window=_ROLLING_STD_WINDOW).std()
        self.validate_output(result)
        return result
