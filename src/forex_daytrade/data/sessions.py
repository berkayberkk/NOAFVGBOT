"""Trading-session classification for UTC timestamps, DST-aware.

Session windows are defined in each market's local time zone and evaluated
per UTC timestamp using `zoneinfo`, so daylight-saving transitions (which
happen on different calendar dates in the UK/EU vs. the US) are handled
correctly without any hardcoded UTC-offset table.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from forex_daytrade.domain.session import TradingSession

_LONDON_TZ = ZoneInfo("Europe/London")
_NEW_YORK_TZ = ZoneInfo("America/New_York")
_TOKYO_TZ = ZoneInfo("Asia/Tokyo")

_LONDON_OPEN_HOUR, _LONDON_CLOSE_HOUR = 8, 17
_NEW_YORK_OPEN_HOUR, _NEW_YORK_CLOSE_HOUR = 8, 17
_ASIAN_OPEN_HOUR, _ASIAN_CLOSE_HOUR = 9, 18

# Rollover: the daily forex swap/liquidity-gap window around the NY 17:00
# close, defined as 16:55-17:05 in New York local time.
_ROLLOVER_START_HOUR, _ROLLOVER_START_MINUTE = 16, 55
_ROLLOVER_END_HOUR, _ROLLOVER_END_MINUTE = 17, 5


def _local_hour_minute(
    timestamp_utc: pd.Series[Any], tz: ZoneInfo
) -> tuple[pd.Series[Any], pd.Series[Any]]:
    local = timestamp_utc.dt.tz_convert(tz)
    return local.dt.hour, local.dt.minute


def classify_sessions(timestamp_utc: pd.Series[Any]) -> pd.Series[Any]:
    """Classify each UTC timestamp into a trading session label.

    Priority (highest first) is: rollover, london/new-york overlap, london,
    new_york, asian, off_session.
    """
    london_hour, _ = _local_hour_minute(timestamp_utc, _LONDON_TZ)
    ny_hour, ny_minute = _local_hour_minute(timestamp_utc, _NEW_YORK_TZ)
    tokyo_hour, _ = _local_hour_minute(timestamp_utc, _TOKYO_TZ)

    in_london = (london_hour >= _LONDON_OPEN_HOUR) & (london_hour < _LONDON_CLOSE_HOUR)
    in_new_york = (ny_hour >= _NEW_YORK_OPEN_HOUR) & (ny_hour < _NEW_YORK_CLOSE_HOUR)
    in_asian = (tokyo_hour >= _ASIAN_OPEN_HOUR) & (tokyo_hour < _ASIAN_CLOSE_HOUR)
    in_rollover = ((ny_hour == _ROLLOVER_START_HOUR) & (ny_minute >= _ROLLOVER_START_MINUTE)) | (
        (ny_hour == _ROLLOVER_END_HOUR) & (ny_minute <= _ROLLOVER_END_MINUTE)
    )

    labels = pd.Series(TradingSession.OFF_SESSION.value, index=timestamp_utc.index)
    labels[in_asian] = TradingSession.ASIAN.value
    labels[in_london] = TradingSession.LONDON.value
    labels[in_new_york] = TradingSession.NEW_YORK.value
    labels[in_london & in_new_york] = TradingSession.LONDON_NEW_YORK_OVERLAP.value
    labels[in_rollover] = TradingSession.ROLLOVER.value
    return labels


def add_session_column(df: pd.DataFrame, timestamp_column: str = "timestamp_utc") -> pd.DataFrame:
    """Return a copy of `df` with a `session` column classifying each row."""
    result = df.copy()
    result["session"] = classify_sessions(result[timestamp_column])
    return result
