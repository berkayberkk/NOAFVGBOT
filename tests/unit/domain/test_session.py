"""Unit tests for forex_daytrade.domain.session."""

import pytest

from forex_daytrade.domain.session import TradingSession


def test_trading_session_values() -> None:
    assert TradingSession.ASIAN.value == "asian"
    assert TradingSession.LONDON.value == "london"
    assert TradingSession.NEW_YORK.value == "new_york"
    assert TradingSession.LONDON_NEW_YORK_OVERLAP.value == "london_newyork_overlap"
    assert TradingSession.ROLLOVER.value == "rollover"
    assert TradingSession.OFF_SESSION.value == "off_session"


def test_trading_session_members_are_complete() -> None:
    assert {member.value for member in TradingSession} == {
        "asian",
        "london",
        "new_york",
        "london_newyork_overlap",
        "rollover",
        "off_session",
    }


def test_trading_session_is_str_enum() -> None:
    assert isinstance(TradingSession.LONDON, str)
    assert TradingSession.LONDON == "london"


def test_trading_session_construction_from_string() -> None:
    assert TradingSession("asian") is TradingSession.ASIAN


def test_trading_session_invalid_value_raises() -> None:
    with pytest.raises(ValueError, match="mars"):
        TradingSession("mars")
