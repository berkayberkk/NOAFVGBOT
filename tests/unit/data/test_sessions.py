"""Unit tests for forex_daytrade.data.sessions."""

import pandas as pd

from forex_daytrade.data.sessions import add_session_column, classify_sessions
from forex_daytrade.domain.session import TradingSession


def _series(*iso_timestamps: str) -> pd.Series:
    return pd.Series(pd.to_datetime(list(iso_timestamps), utc=True))


def test_classify_sessions_winter_london_only() -> None:
    # 2024-12-10 09:00 UTC: London local 09:00 (GMT), NY local 04:00 EST.
    labels = classify_sessions(_series("2024-12-10T09:00:00Z"))
    assert labels.iloc[0] == TradingSession.LONDON.value


def test_classify_sessions_winter_london_new_york_overlap() -> None:
    # 2024-12-10 14:00 UTC: London local 14:00 (GMT), NY local 09:00 EST.
    labels = classify_sessions(_series("2024-12-10T14:00:00Z"))
    assert labels.iloc[0] == TradingSession.LONDON_NEW_YORK_OVERLAP.value


def test_classify_sessions_asian_session() -> None:
    # 2024-12-10 02:00 UTC: Tokyo local 11:00 JST, outside London/NY hours.
    labels = classify_sessions(_series("2024-12-10T02:00:00Z"))
    assert labels.iloc[0] == TradingSession.ASIAN.value


def test_classify_sessions_off_session() -> None:
    # 2024-12-10 23:00 UTC: NY local 18:00 EST (closed), Tokyo local 08:00
    # JST (not yet open), London local 23:00 GMT (closed).
    labels = classify_sessions(_series("2024-12-10T23:00:00Z"))
    assert labels.iloc[0] == TradingSession.OFF_SESSION.value


def test_classify_sessions_rollover_window() -> None:
    # 2024-12-10 21:58 UTC: NY local 16:58 EST, inside the 16:55-17:05 window.
    labels = classify_sessions(_series("2024-12-10T21:58:00Z"))
    assert labels.iloc[0] == TradingSession.ROLLOVER.value


def test_classify_sessions_is_dst_aware() -> None:
    # 2024-06-10 07:30 UTC: London local 08:30 BST (summer, open).
    summer = classify_sessions(_series("2024-06-10T07:30:00Z"))
    assert summer.iloc[0] == TradingSession.LONDON.value

    # Same UTC clock time in December: London local 07:30 GMT (not yet open).
    winter = classify_sessions(_series("2024-12-10T07:30:00Z"))
    assert winter.iloc[0] != TradingSession.LONDON.value


def test_add_session_column() -> None:
    df = pd.DataFrame({"timestamp_utc": pd.to_datetime(["2024-12-10T09:00:00Z"], utc=True)})
    result = add_session_column(df)
    assert "session" in result.columns
    assert result.loc[0, "session"] == TradingSession.LONDON.value
