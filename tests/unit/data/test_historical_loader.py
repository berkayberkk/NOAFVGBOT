"""Unit tests for forex_daytrade.data.historical_loader."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from forex_daytrade.data.exceptions import UnsupportedSymbolError
from forex_daytrade.data.historical_loader import load_historical_bars
from forex_daytrade.data.types import IngestionTimeframe


def _mock_client(return_value: pd.DataFrame) -> Any:
    client = MagicMock()
    client.copy_rates_range.return_value = return_value
    return client


def test_load_historical_bars_delegates_to_client() -> None:
    expected = pd.DataFrame({"time": [1700000000], "close": [1.1]})
    client = _mock_client(expected)
    date_from = datetime(2023, 11, 1, tzinfo=UTC)
    date_to = datetime(2023, 11, 2, tzinfo=UTC)

    result = load_historical_bars(client, "EURUSD", IngestionTimeframe.M5, date_from, date_to)

    client.copy_rates_range.assert_called_once_with(
        "EURUSD", IngestionTimeframe.M5, date_from, date_to
    )
    pd.testing.assert_frame_equal(result, expected)


def test_load_historical_bars_rejects_unsupported_symbol() -> None:
    client = _mock_client(pd.DataFrame())
    with pytest.raises(UnsupportedSymbolError):
        load_historical_bars(
            client,
            "GBPUSD",
            IngestionTimeframe.M5,
            datetime(2023, 11, 1, tzinfo=UTC),
            datetime(2023, 11, 2, tzinfo=UTC),
        )


def test_load_historical_bars_rejects_inverted_date_range() -> None:
    client = _mock_client(pd.DataFrame())
    with pytest.raises(ValueError, match="date_from"):
        load_historical_bars(
            client,
            "EURUSD",
            IngestionTimeframe.M5,
            datetime(2023, 11, 2, tzinfo=UTC),
            datetime(2023, 11, 1, tzinfo=UTC),
        )
