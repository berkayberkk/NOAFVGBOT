"""Thin, read-only wrapper around the MetaTrader5 terminal API.

This module never places, modifies, or cancels orders. It only manages the
terminal connection lifecycle and downloads historical bar data. It assumes
the MT5 terminal is already installed and logged into a broker account by
the user; per docs/ARCHITECTURE.md, the data layer never supplies broker
credentials.

The MetaTrader5 package is Windows-only and is imported lazily (inside
function bodies, never at module import time) so that this module can be
imported and unit-tested with mocks on platforms where the package cannot
be installed, such as CI running on Linux.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd

from forex_daytrade.data.exceptions import (
    MT5ConnectionError,
    MT5NotAvailableError,
    SymbolNotFoundError,
)
from forex_daytrade.data.types import IngestionTimeframe

logger = logging.getLogger(__name__)


def _import_mt5() -> Any:
    """Import the MetaTrader5 package, raising a clear error if unavailable."""
    try:
        import MetaTrader5 as mt5  # noqa: N813
    except ImportError as exc:
        raise MT5NotAvailableError(
            "The MetaTrader5 package is not installed or not available on this platform."
        ) from exc
    return mt5


class MT5Client:
    """Connection-lifecycle and historical-data wrapper for the MT5 terminal."""

    def __init__(self, terminal_path: str | None = None) -> None:
        self._terminal_path = terminal_path
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def initialize(self) -> None:
        """Connect to a running MT5 terminal."""
        mt5 = _import_mt5()
        kwargs: dict[str, Any] = {}
        if self._terminal_path:
            kwargs["path"] = self._terminal_path
        if not mt5.initialize(**kwargs):
            raise MT5ConnectionError(f"MT5 initialize() failed: {mt5.last_error()}")
        self._connected = True
        logger.info("MT5 terminal initialized", extra={"terminal_path": self._terminal_path})

    def shutdown(self) -> None:
        """Disconnect from the MT5 terminal, if connected."""
        if not self._connected:
            return
        mt5 = _import_mt5()
        mt5.shutdown()
        self._connected = False
        logger.info("MT5 terminal connection closed")

    def reconnect(self) -> None:
        """Shut down and re-initialize the MT5 terminal connection."""
        logger.info("Reconnecting to MT5 terminal")
        self.shutdown()
        self.initialize()

    def symbol_exists(self, symbol: str) -> bool:
        """Return whether `symbol` is available in the connected terminal."""
        mt5 = _import_mt5()
        return bool(mt5.symbol_info(symbol) is not None)

    def copy_rates_range(
        self,
        symbol: str,
        timeframe: IngestionTimeframe,
        date_from: datetime,
        date_to: datetime,
    ) -> pd.DataFrame:
        """Download raw historical bars for `symbol` between two timestamps.

        Callers are responsible for normalization and validation of the
        returned data.
        """
        if not self._connected:
            raise MT5ConnectionError("MT5Client is not initialized; call initialize() first.")
        mt5 = _import_mt5()
        if not self.symbol_exists(symbol):
            raise SymbolNotFoundError(f"Symbol not found in MT5 terminal: {symbol}")
        tf_constant = getattr(mt5, timeframe.mt5_constant_name)
        rates = mt5.copy_rates_range(symbol, tf_constant, date_from, date_to)
        if rates is None:
            raise MT5ConnectionError(
                f"copy_rates_range returned no data for {symbol} {timeframe.value}: "
                f"{mt5.last_error()}"
            )
        return pd.DataFrame(rates)

    def __enter__(self) -> MT5Client:
        self.initialize()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.shutdown()
