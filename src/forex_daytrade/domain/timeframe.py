"""Canonical chart timeframe enum for the domain layer.

This is the domain layer's complete timeframe vocabulary (M1 through D1).
It is intentionally separate from
`forex_daytrade.data.types.IngestionTimeframe`, which enumerates only the
subset (M5/M15/H1) the current MT5 ingestion pipeline supports and carries
MT5/pandas-specific properties this module must stay free of — see the
Domain Layer section of ARCHITECTURE.md for the full ownership rule.
`IngestionTimeframe.timedelta` delegates to this module rather than
redeclaring the interval table.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

_TIMEDELTAS = {
    "M1": timedelta(minutes=1),
    "M5": timedelta(minutes=5),
    "M15": timedelta(minutes=15),
    "M30": timedelta(minutes=30),
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
    "D1": timedelta(days=1),
}


class Timeframe(StrEnum):
    """Supported chart timeframes, from one minute to one day."""

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def timedelta(self) -> timedelta:
        """Expected duration between consecutive bars at this timeframe."""
        return _TIMEDELTAS[self.value]

    @property
    def minutes(self) -> int:
        """This timeframe's bar interval expressed in whole minutes."""
        return int(self.timedelta.total_seconds() // 60)
