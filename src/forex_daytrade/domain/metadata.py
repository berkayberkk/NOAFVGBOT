"""Dataset metadata domain contract.

Distinct from `forex_daytrade.data.metadata.IngestionMetadata`, which is
the data layer's pandas-based, JSON-sidecar-specific metadata format
(embeds symbol/timeframe, ISO-string timestamps). This is the pandas-free,
canonical metadata contract for the domain layer's `MarketData` container
(see `market_data.py`); see the Domain Layer section of ARCHITECTURE.md
for why the two are not consolidated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from forex_daytrade.exceptions.data import InvalidMetadataError


@dataclass(frozen=True, slots=True)
class DatasetMetadata:
    """Descriptive metadata for a dataset of domain-model bars."""

    source: str
    created_at: datetime
    dataset_version: str
    row_count: int
    start_timestamp: datetime
    end_timestamp: datetime

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise InvalidMetadataError(
                f"DatasetMetadata.row_count must be >= 0, got {self.row_count}."
            )
        if self.row_count > 0 and self.start_timestamp > self.end_timestamp:
            raise InvalidMetadataError(
                f"DatasetMetadata.start_timestamp ({self.start_timestamp}) must be <= "
                f"end_timestamp ({self.end_timestamp})."
            )
