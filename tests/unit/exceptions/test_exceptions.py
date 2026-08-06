"""Unit tests for forex_daytrade.exceptions."""

import pytest

from forex_daytrade.exceptions.base import DomainError
from forex_daytrade.exceptions.data import (
    InvalidCandleError,
    InvalidMarketDataError,
    InvalidMetadataError,
    InvalidSymbolError,
    InvalidTickError,
)


@pytest.mark.parametrize(
    "error_type",
    [
        InvalidCandleError,
        InvalidMarketDataError,
        InvalidMetadataError,
        InvalidSymbolError,
        InvalidTickError,
    ],
)
def test_data_exceptions_are_domain_errors(error_type: type[DomainError]) -> None:
    assert issubclass(error_type, DomainError)


def test_domain_error_is_exception() -> None:
    assert issubclass(DomainError, Exception)


def test_error_message_is_preserved() -> None:
    error = InvalidCandleError("bad candle")
    assert str(error) == "bad candle"
