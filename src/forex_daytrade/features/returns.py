"""Return-based feature generators.

Both features are backward-looking only (`.shift(1)`/`.pct_change()` never
reference a future row), so the first row of any series is always NaN —
there is no prior bar to compute a return against.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from forex_daytrade.features.base import Feature
from forex_daytrade.features.registry import register_feature


@register_feature
class LogReturnFeature(Feature):
    """Log return of `close` versus the previous bar's `close`."""

    name = "log_return"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"log_return"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["log_return"] = np.log(df["close"] / df["close"].shift(1))
        self.validate_output(result)
        return result


@register_feature
class SimpleReturnFeature(Feature):
    """Simple (percentage) return of `close` versus the previous bar's `close`."""

    name = "simple_return"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"simple_return"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["simple_return"] = df["close"].pct_change()
        self.validate_output(result)
        return result
