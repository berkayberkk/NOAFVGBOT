"""Symbol (tradeable instrument) domain model.

Describes instrument static parameters needed by every future layer
(feature scaling, position sizing, cost modeling) without holding any
broker connection or live state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forex_daytrade.exceptions.data import InvalidSymbolError


class TradeMode(StrEnum):
    """Placeholder trade-mode classification; carries no broker semantics yet."""

    UNKNOWN = "unknown"
    DISABLED = "disabled"
    FULL = "full"
    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"
    CLOSE_ONLY = "close_only"


@dataclass(frozen=True, slots=True)
class Symbol:
    """A tradeable instrument's static contract parameters."""

    name: str
    digits: int
    point_size: float
    contract_size: float
    tick_value: float
    min_volume: float
    max_volume: float
    volume_step: float
    trade_mode: TradeMode = TradeMode.UNKNOWN

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidSymbolError("Symbol.name must not be empty.")
        if self.digits < 0:
            raise InvalidSymbolError(f"Symbol.digits must be >= 0, got {self.digits}.")
        if self.point_size <= 0:
            raise InvalidSymbolError(
                f"Symbol.point_size must be positive, got {self.point_size}."
            )
        if self.contract_size <= 0:
            raise InvalidSymbolError(
                f"Symbol.contract_size must be positive, got {self.contract_size}."
            )
        if self.tick_value <= 0:
            raise InvalidSymbolError(
                f"Symbol.tick_value must be positive, got {self.tick_value}."
            )
        if self.min_volume <= 0:
            raise InvalidSymbolError(
                f"Symbol.min_volume must be positive, got {self.min_volume}."
            )
        if self.max_volume < self.min_volume:
            raise InvalidSymbolError(
                f"Symbol.max_volume ({self.max_volume}) must be >= min_volume "
                f"({self.min_volume})."
            )
        if self.volume_step <= 0:
            raise InvalidSymbolError(
                f"Symbol.volume_step must be positive, got {self.volume_step}."
            )
