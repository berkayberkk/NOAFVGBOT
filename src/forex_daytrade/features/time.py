"""Time-based feature generators."""

from __future__ import annotations

import pandas as pd

from forex_daytrade.features.base import Feature
from forex_daytrade.features.registry import register_feature


@register_feature
class HourOfDayFeature(Feature):
    """UTC hour of day (0-23) of `timestamp_utc`."""

    name = "hour_of_day"
    required_columns = frozenset({"timestamp_utc"})
    generated_columns = frozenset({"hour_of_day"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["hour_of_day"] = df["timestamp_utc"].dt.hour
        self.validate_output(result)
        return result


@register_feature
class DayOfWeekFeature(Feature):
    """Day of week (Monday=0 .. Sunday=6) of `timestamp_utc`."""

    name = "day_of_week"
    required_columns = frozenset({"timestamp_utc"})
    generated_columns = frozenset({"day_of_week"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["day_of_week"] = df["timestamp_utc"].dt.dayofweek
        self.validate_output(result)
        return result


@register_feature
class SessionPlaceholderFeature(Feature):
    """Passes through the data layer's already-classified `session` label.

    This is deliberately a placeholder, not a new classification: session
    detection is the Data Layer's responsibility
    (`forex_daytrade.data.sessions.classify_sessions`, itself backed by the
    canonical `forex_daytrade.domain.session.TradingSession` vocabulary).
    Recomputing it here would duplicate that logic and risk drifting from
    it. Real session-*derived* features (one-hot encoding, cyclical
    encoding, etc.) are deferred to a future sprint once it's clear what
    encoding the Regime/Strategy layers actually need.
    """

    name = "session_placeholder"
    required_columns = frozenset({"session"})
    generated_columns = frozenset({"session_placeholder"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["session_placeholder"] = df["session"]
        self.validate_output(result)
        return result
