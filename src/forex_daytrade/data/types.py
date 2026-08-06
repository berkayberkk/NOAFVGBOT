"""Ingestion-pipeline-specific types for the forex_daytrade data layer.

`IngestionTimeframe` is the historical-data-ingestion pipeline's restricted,
MT5-flavored timeframe type: it supports only the timeframes the pipeline
currently downloads (M5/M15/H1) and carries MT5-connector and pandas-
resampling concerns (`mt5_constant_name`, `pandas_freq`) that have no place
in the domain layer. It is intentionally a distinct type from
`forex_daytrade.domain.timeframe.Timeframe` (the domain layer's complete,
MT5-free M1-D1 vocabulary) — see the Domain Layer section of
ARCHITECTURE.md for the ownership rule. Its `.timedelta` property delegates
to the domain type so bar-interval lengths have one source of truth.

Trading-session labels are fully owned by
`forex_daytrade.domain.session.TradingSession`; this module no longer
defines its own session enum (see `data/sessions.py`).
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from forex_daytrade.domain.timeframe import Timeframe as _DomainTimeframe


class IngestionTimeframe(StrEnum):
    """Timeframes the current MT5 historical-ingestion pipeline supports."""

    M5 = "M5"
    M15 = "M15"
    H1 = "H1"

    @property
    def mt5_constant_name(self) -> str:
        """Name of the corresponding constant on the MetaTrader5 module."""
        return f"TIMEFRAME_{self.value}"

    @property
    def pandas_freq(self) -> str:
        """Pandas frequency alias for this timeframe's bar interval."""
        mapping = {
            IngestionTimeframe.M5: "5min",
            IngestionTimeframe.M15: "15min",
            IngestionTimeframe.H1: "1h",
        }
        return mapping[self]

    @property
    def timedelta(self) -> timedelta:
        """Expected duration between consecutive bars (delegates to the domain type)."""
        return _DomainTimeframe(self.value).timedelta
