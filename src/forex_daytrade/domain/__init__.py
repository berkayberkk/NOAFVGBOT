"""Domain layer: shared data structures, contracts, and enums used by every
other layer (see the Domain Layer section of ARCHITECTURE.md).

Pure data contracts only: no pandas dependency, no MT5 dependency, no
strategy/risk/execution logic.
"""

from forex_daytrade.domain.candle import Candle
from forex_daytrade.domain.market_data import MarketData
from forex_daytrade.domain.metadata import DatasetMetadata
from forex_daytrade.domain.session import TradingSession
from forex_daytrade.domain.symbol import Symbol, TradeMode
from forex_daytrade.domain.tick import Tick
from forex_daytrade.domain.timeframe import Timeframe
from forex_daytrade.domain.validation import Severity, ValidationIssue, ValidationReport

__all__ = [
    "Candle",
    "DatasetMetadata",
    "MarketData",
    "Severity",
    "Symbol",
    "Tick",
    "Timeframe",
    "TradeMode",
    "TradingSession",
    "ValidationIssue",
    "ValidationReport",
]
