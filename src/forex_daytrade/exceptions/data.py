"""Domain-model data-contract exceptions.

Raised by constructors in `forex_daytrade.domain` when a value violates the
domain model's own invariants (e.g. `high < low` on a `Candle`). Distinct
from `forex_daytrade.data.exceptions`, which covers data-layer
*infrastructure* failures (MT5 connectivity, storage I/O) and is unrelated
to these.
"""

from forex_daytrade.exceptions.base import DomainError


class InvalidCandleError(DomainError):
    """Raised when a `Candle`'s OHLC/volume/timestamp values violate domain invariants."""


class InvalidTickError(DomainError):
    """Raised when a `Tick`'s bid/ask/timestamp values violate domain invariants."""


class InvalidSymbolError(DomainError):
    """Raised when a `Symbol`'s contract/volume parameters violate domain invariants."""


class InvalidMetadataError(DomainError):
    """Raised when a `DatasetMetadata`'s fields are internally inconsistent."""


class InvalidMarketDataError(DomainError):
    """Raised when a `MarketData` container's contents are internally inconsistent."""
