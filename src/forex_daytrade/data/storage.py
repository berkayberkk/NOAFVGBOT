"""Parquet-based storage for normalized datasets."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from forex_daytrade.data.exceptions import EmptyDatasetError
from forex_daytrade.data.types import IngestionTimeframe

logger = logging.getLogger(__name__)


def normalized_dataset_path(base_dir: Path, symbol: str, timeframe: IngestionTimeframe) -> Path:
    """Build the canonical file path for a symbol/timeframe's normalized dataset."""
    return base_dir / f"{symbol}_{timeframe.value}.parquet"


def save_normalized_dataset(
    df: pd.DataFrame, base_dir: Path, symbol: str, timeframe: IngestionTimeframe
) -> Path:
    """Persist a normalized dataset as Parquet, returning the written path."""
    if len(df) == 0:
        raise EmptyDatasetError(f"Refusing to save empty dataset for {symbol} {timeframe.value}")
    base_dir.mkdir(parents=True, exist_ok=True)
    path = normalized_dataset_path(base_dir, symbol, timeframe)
    df.to_parquet(path, engine="pyarrow", index=False)
    logger.info("Saved normalized dataset", extra={"path": str(path), "rows": len(df)})
    return path


def load_normalized_dataset(
    base_dir: Path, symbol: str, timeframe: IngestionTimeframe
) -> pd.DataFrame:
    """Load a previously saved normalized dataset from Parquet."""
    path = normalized_dataset_path(base_dir, symbol, timeframe)
    df: pd.DataFrame = pd.read_parquet(path)
    return df
