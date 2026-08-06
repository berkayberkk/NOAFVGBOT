"""Unit tests for forex_daytrade.data.types."""

from datetime import timedelta

from forex_daytrade.data.types import IngestionTimeframe
from forex_daytrade.domain.timeframe import Timeframe as DomainTimeframe


def test_ingestion_timeframe_mt5_constant_name() -> None:
    assert IngestionTimeframe.M5.mt5_constant_name == "TIMEFRAME_M5"
    assert IngestionTimeframe.M15.mt5_constant_name == "TIMEFRAME_M15"
    assert IngestionTimeframe.H1.mt5_constant_name == "TIMEFRAME_H1"


def test_ingestion_timeframe_pandas_freq() -> None:
    assert IngestionTimeframe.M5.pandas_freq == "5min"
    assert IngestionTimeframe.M15.pandas_freq == "15min"
    assert IngestionTimeframe.H1.pandas_freq == "1h"


def test_ingestion_timeframe_timedelta_matches_domain_timeframe() -> None:
    assert IngestionTimeframe.M5.timedelta == timedelta(minutes=5)
    assert IngestionTimeframe.M15.timedelta == timedelta(minutes=15)
    assert IngestionTimeframe.H1.timedelta == timedelta(hours=1)


def test_ingestion_timeframe_only_supports_ingestion_pipeline_timeframes() -> None:
    assert {member.value for member in IngestionTimeframe} == {"M5", "M15", "H1"}


def test_ingestion_timeframe_timedelta_delegates_to_domain_timeframe() -> None:
    for member in IngestionTimeframe:
        assert member.timedelta == DomainTimeframe(member.value).timedelta
