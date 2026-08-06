"""Candle (OHLCV bar) domain model — the canonical price-bar contract.

Pure data contract: no pandas dependency, no business logic. Consumers
(feature/regime/strategy layers) build `Candle` instances from whatever
tabular representation the data layer produces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from forex_daytrade.domain.common import require_timezone_aware
from forex_daytrade.exceptions.data import InvalidCandleError


@dataclass(frozen=True, slots=True)
class Candle:
    """A single OHLCV price bar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timezone: str
    spread: float | None = None

    def __post_init__(self) -> None:
        require_timezone_aware(self.timestamp, InvalidCandleError, "Candle.timestamp")
        if not self.timezone:
            raise InvalidCandleError("Candle.timezone must not be empty.")
        if str(self.timestamp.tzinfo) != self.timezone:
            raise InvalidCandleError(
                f"Candle.timezone ({self.timezone!r}) does not match "
                f"timestamp.tzinfo ({str(self.timestamp.tzinfo)!r})."
            )
        if any(value <= 0 for value in (self.open, self.high, self.low, self.close)):
            raise InvalidCandleError("Candle OHLC values must all be positive.")
        if self.low > self.high:
            raise InvalidCandleError(
                f"Candle.low ({self.low}) must be <= Candle.high ({self.high})."
            )
        for field_name, value in (("open", self.open), ("close", self.close)):
            if not (self.low <= value <= self.high):
                raise InvalidCandleError(
                    f"Candle.{field_name} ({value}) must be within [low, high] "
                    f"([{self.low}, {self.high}])."
                )
        if self.volume < 0:
            raise InvalidCandleError(f"Candle.volume must be >= 0, got {self.volume}.")
        if self.spread is not None and self.spread < 0:
            raise InvalidCandleError(f"Candle.spread must be >= 0 if set, got {self.spread}.")

    @property
    def is_bullish(self) -> bool:
        """Whether this bar closed above where it opened."""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """Whether this bar closed below where it opened."""
        return self.close < self.open

    @property
    def range(self) -> float:
        """The bar's high-low range."""
        return self.high - self.low
