"""Unit tests for forex_daytrade.data.metadata."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from forex_daytrade.data.exceptions import EmptyDatasetError
from forex_daytrade.data.metadata import build_metadata, load_metadata, save_metadata
from forex_daytrade.data.types import IngestionTimeframe


def _normalized_df() -> pd.DataFrame:
    timestamps = pd.date_range("2024-03-04T08:00:00Z", periods=3, freq="5min", tz="UTC")
    return pd.DataFrame({"timestamp_utc": timestamps, "close": [1.1, 1.11, 1.12]})


def test_build_metadata_fields() -> None:
    downloaded_at = datetime(2024, 3, 4, 9, 0, tzinfo=UTC)
    metadata = build_metadata(
        _normalized_df(), "EURUSD", IngestionTimeframe.M5, source="MT5", downloaded_at=downloaded_at
    )
    assert metadata.symbol == "EURUSD"
    assert metadata.timeframe == "M5"
    assert metadata.source == "MT5"
    assert metadata.row_count == 3
    assert metadata.downloaded_at == downloaded_at.isoformat()
    assert "2024-03-04 08:00:00" in metadata.start_timestamp_utc
    assert "2024-03-04 08:10:00" in metadata.end_timestamp_utc


def test_build_metadata_raises_on_empty_dataset() -> None:
    with pytest.raises(EmptyDatasetError):
        build_metadata(_normalized_df().iloc[0:0], "EURUSD", IngestionTimeframe.M5, source="MT5")


def test_save_and_load_metadata_round_trip(tmp_path: Path) -> None:
    metadata = build_metadata(_normalized_df(), "EURUSD", IngestionTimeframe.M5, source="MT5")
    saved_path = save_metadata(metadata, tmp_path)

    assert saved_path.exists()
    loaded = load_metadata(tmp_path, "EURUSD", IngestionTimeframe.M5)
    assert loaded == metadata
