"""Unit tests for forex_daytrade.data.storage."""

from pathlib import Path

import pandas as pd
import pytest

from forex_daytrade.data.exceptions import EmptyDatasetError
from forex_daytrade.data.storage import (
    load_normalized_dataset,
    normalized_dataset_path,
    save_normalized_dataset,
)
from forex_daytrade.data.types import IngestionTimeframe


def _normalized_df() -> pd.DataFrame:
    timestamps = pd.date_range("2024-03-04T08:00:00Z", periods=3, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "symbol": ["EURUSD"] * 3,
            "close": [1.10, 1.11, 1.12],
        }
    )


def test_normalized_dataset_path_naming(tmp_path: Path) -> None:
    path = normalized_dataset_path(tmp_path, "EURUSD", IngestionTimeframe.M15)
    assert path == tmp_path / "EURUSD_M15.parquet"


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    df = _normalized_df()
    saved_path = save_normalized_dataset(df, tmp_path, "EURUSD", IngestionTimeframe.M5)

    assert saved_path.exists()
    loaded = load_normalized_dataset(tmp_path, "EURUSD", IngestionTimeframe.M5)
    pd.testing.assert_frame_equal(loaded, df)


def test_save_raises_on_empty_dataset(tmp_path: Path) -> None:
    empty = _normalized_df().iloc[0:0]
    with pytest.raises(EmptyDatasetError):
        save_normalized_dataset(empty, tmp_path, "EURUSD", IngestionTimeframe.M5)
