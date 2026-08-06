"""Custom exceptions for the forex_daytrade data layer."""

from __future__ import annotations


class DataLayerError(Exception):
    """Base class for all data-layer errors."""


class MT5NotAvailableError(DataLayerError):
    """Raised when the MetaTrader5 package is not installed or importable."""


class MT5ConnectionError(DataLayerError):
    """Raised when connecting to or communicating with the MT5 terminal fails."""


class SymbolNotFoundError(DataLayerError):
    """Raised when a requested symbol is not available in the MT5 terminal."""


class UnsupportedSymbolError(DataLayerError):
    """Raised when a symbol is not supported by this data layer."""


class EmptyDatasetError(DataLayerError):
    """Raised when an operation requires a non-empty dataset but received none."""
