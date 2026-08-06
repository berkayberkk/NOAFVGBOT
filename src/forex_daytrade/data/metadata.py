"""Dataset metadata generation and persistence.

Together with `storage.py`, this implements the Phase 1 data-versioning
scheme: one Parquet file plus one metadata JSON sidecar per symbol/
timeframe. Re-running ingestion overwrites both; `downloaded_at` on the
metadata sidecar records when each version was produced, giving simple
auditability without a heavier versioned-storage system.

`IngestionMetadata` is intentionally distinct from
`forex_daytrade.domain.metadata.DatasetMetadata`: it embeds `symbol` and
`timeframe` inline (the domain equivalent leaves those to the enclosing
`MarketData` container) and serializes timestamps as ISO strings to match
the on-disk JSON sidecar schema this module reads and writes. Changing
either shape to match the other would risk the stored sidecar format, so
the two are kept separate — see the Domain Layer section of
ARCHITECTURE.md.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from forex_daytrade.data.exceptions import EmptyDatasetError
from forex_daytrade.data.types import IngestionTimeframe

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionMetadata:
    symbol: str
    timeframe: str
    source: str
    downloaded_at: str
    row_count: int
    start_timestamp_utc: str
    end_timestamp_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_metadata(
    df: pd.DataFrame,
    symbol: str,
    timeframe: IngestionTimeframe,
    source: str,
    *,
    downloaded_at: datetime | None = None,
    timestamp_column: str = "timestamp_utc",
) -> IngestionMetadata:
    """Build metadata describing a normalized dataset."""
    if len(df) == 0:
        raise EmptyDatasetError(
            f"Cannot build metadata for an empty dataset ({symbol} {timeframe.value})"
        )
    downloaded = downloaded_at if downloaded_at is not None else datetime.now(UTC)
    timestamps = df[timestamp_column]
    return IngestionMetadata(
        symbol=symbol,
        timeframe=timeframe.value,
        source=source,
        downloaded_at=downloaded.isoformat(),
        row_count=len(df),
        start_timestamp_utc=str(timestamps.min()),
        end_timestamp_utc=str(timestamps.max()),
    )


def metadata_path(base_dir: Path, symbol: str, timeframe: IngestionTimeframe) -> Path:
    return base_dir / f"{symbol}_{timeframe.value}.json"


def save_metadata(metadata: IngestionMetadata, base_dir: Path) -> Path:
    """Persist metadata as JSON, returning the written path."""
    base_dir.mkdir(parents=True, exist_ok=True)
    timeframe = IngestionTimeframe(metadata.timeframe)
    path = metadata_path(base_dir, metadata.symbol, timeframe)
    path.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")
    logger.info("Saved dataset metadata", extra={"path": str(path)})
    return path


def load_metadata(base_dir: Path, symbol: str, timeframe: IngestionTimeframe) -> IngestionMetadata:
    """Load previously saved metadata."""
    path = metadata_path(base_dir, symbol, timeframe)
    data = json.loads(path.read_text(encoding="utf-8"))
    return IngestionMetadata(**data)
