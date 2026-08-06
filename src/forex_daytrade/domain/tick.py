"""Tick (bid/ask quote) domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from forex_daytrade.domain.common import require_timezone_aware
from forex_daytrade.exceptions.data import InvalidTickError


@dataclass(frozen=True, slots=True)
class Tick:
    """A single bid/ask quote."""

    bid: float
    ask: float
    timestamp: datetime

    def __post_init__(self) -> None:
        require_timezone_aware(self.timestamp, InvalidTickError, "Tick.timestamp")
        if self.bid <= 0:
            raise InvalidTickError(f"Tick.bid must be positive, got {self.bid}.")
        if self.ask <= 0:
            raise InvalidTickError(f"Tick.ask must be positive, got {self.ask}.")
        if self.ask < self.bid:
            raise InvalidTickError(f"Tick.ask ({self.ask}) must be >= Tick.bid ({self.bid}).")

    @property
    def spread(self) -> float:
        """The bid/ask spread."""
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        """The bid/ask midpoint price."""
        return (self.bid + self.ask) / 2
