"""Project-wide domain exception hierarchy.

Distinct from `forex_daytrade.data.exceptions`, which covers data-layer
*infrastructure* failures (MT5 connectivity, storage I/O). These describe
violations of the domain model's own invariants.
"""

from forex_daytrade.exceptions.base import DomainError
from forex_daytrade.exceptions.data import (
    InvalidCandleError,
    InvalidMarketDataError,
    InvalidMetadataError,
    InvalidSymbolError,
    InvalidTickError,
)

__all__ = [
    "DomainError",
    "InvalidCandleError",
    "InvalidMarketDataError",
    "InvalidMetadataError",
    "InvalidSymbolError",
    "InvalidTickError",
]
