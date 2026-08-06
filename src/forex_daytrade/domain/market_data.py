"""MarketData: the canonical container binding a symbol/timeframe's bars to
their dataset metadata and validation report.
"""

from __future__ import annotations

from dataclasses import dataclass

from forex_daytrade.domain.candle import Candle
from forex_daytrade.domain.metadata import DatasetMetadata
from forex_daytrade.domain.symbol import Symbol
from forex_daytrade.domain.timeframe import Timeframe
from forex_daytrade.domain.validation import ValidationReport
from forex_daytrade.exceptions.data import InvalidMarketDataError


@dataclass(frozen=True, slots=True)
class MarketData:
    """A symbol/timeframe's bars, together with their metadata and validation report."""

    symbol: Symbol
    timeframe: Timeframe
    bars: tuple[Candle, ...]
    metadata: DatasetMetadata
    validation_report: ValidationReport

    def __post_init__(self) -> None:
        if self.metadata.row_count != len(self.bars):
            raise InvalidMarketDataError(
                f"MarketData.metadata.row_count ({self.metadata.row_count}) does not "
                f"match len(bars) ({len(self.bars)})."
            )
