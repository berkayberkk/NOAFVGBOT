"""Unit tests for forex_daytrade.domain.market_data."""

from datetime import UTC, datetime

import pytest

from forex_daytrade.domain.candle import Candle
from forex_daytrade.domain.market_data import MarketData
from forex_daytrade.domain.metadata import DatasetMetadata
from forex_daytrade.domain.symbol import Symbol
from forex_daytrade.domain.timeframe import Timeframe
from forex_daytrade.domain.validation import ValidationReport
from forex_daytrade.exceptions.data import InvalidMarketDataError

_SYMBOL = Symbol(
    name="EURUSD",
    digits=5,
    point_size=0.00001,
    contract_size=100000.0,
    tick_value=1.0,
    min_volume=0.01,
    max_volume=100.0,
    volume_step=0.01,
)

_CANDLE = Candle(
    timestamp=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
    open=1.1000,
    high=1.1050,
    low=1.0950,
    close=1.1020,
    volume=100.0,
    timezone="UTC",
)


def _make_metadata(row_count: int) -> DatasetMetadata:
    return DatasetMetadata(
        source="mt5",
        created_at=datetime(2026, 1, 5, tzinfo=UTC),
        dataset_version="v1",
        row_count=row_count,
        start_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        end_timestamp=datetime(2026, 1, 5, tzinfo=UTC),
    )


def test_construction_with_matching_row_count() -> None:
    market_data = MarketData(
        symbol=_SYMBOL,
        timeframe=Timeframe.H1,
        bars=(_CANDLE,),
        metadata=_make_metadata(row_count=1),
        validation_report=ValidationReport(),
    )
    assert len(market_data.bars) == 1
    assert market_data.timeframe is Timeframe.H1


def test_mismatched_row_count_rejected() -> None:
    with pytest.raises(InvalidMarketDataError, match="row_count"):
        MarketData(
            symbol=_SYMBOL,
            timeframe=Timeframe.H1,
            bars=(_CANDLE,),
            metadata=_make_metadata(row_count=2),
            validation_report=ValidationReport(),
        )


def test_empty_bars_with_zero_row_count() -> None:
    market_data = MarketData(
        symbol=_SYMBOL,
        timeframe=Timeframe.H1,
        bars=(),
        metadata=_make_metadata(row_count=0),
        validation_report=ValidationReport(),
    )
    assert market_data.bars == ()


def test_equality() -> None:
    def build() -> MarketData:
        return MarketData(
            symbol=_SYMBOL,
            timeframe=Timeframe.H1,
            bars=(_CANDLE,),
            metadata=_make_metadata(row_count=1),
            validation_report=ValidationReport(),
        )

    assert build() == build()


def test_is_frozen() -> None:
    market_data = MarketData(
        symbol=_SYMBOL,
        timeframe=Timeframe.H1,
        bars=(_CANDLE,),
        metadata=_make_metadata(row_count=1),
        validation_report=ValidationReport(),
    )
    with pytest.raises(AttributeError):
        market_data.bars = ()  # type: ignore[misc]
