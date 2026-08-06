"""The canonical, immutable research dataset identity object.

`ResearchDataset` is the identity contract every future research
component (Backtest, Regime, Strategy, ...) will consume: given the same
raw data, the same feature pipeline, and the same configuration,
`forex_daytrade.research.builder.DatasetBuilder` always produces a
`ResearchDataset` whose `hash` (see `fingerprint.py`) is identical.

This object deliberately does not hold the dataset's underlying
`pandas.DataFrame`. A DataFrame is mutable even inside a frozen dataclass
field — freezing only blocks *reassigning* the attribute, not mutating
the object it points to — which would silently violate "the dataset
object should not expose mutable internal state." Instead,
`DatasetBuilder.build()` returns this identity object and its
`pandas.DataFrame` payload as two separate values (see
`builder.DatasetBuildResult`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from forex_daytrade.domain.metadata import DatasetMetadata
from forex_daytrade.domain.symbol import Symbol
from forex_daytrade.domain.timeframe import Timeframe
from forex_daytrade.domain.validation import ValidationReport
from forex_daytrade.research.manifest import DatasetManifest
from forex_daytrade.research.version import DatasetVersion, FeatureVersion


class InvalidResearchDatasetError(Exception):
    """Raised when a `ResearchDataset`'s fields are internally inconsistent."""


@dataclass(frozen=True, slots=True)
class ResearchDataset:
    """An immutable, fingerprinted, reproducible research dataset identity.

    `label_columns` is a placeholder — always empty in this sprint. No
    strategy, signal, or ML label logic exists yet; the field exists so
    the schema doesn't need to change when that work begins.
    """

    dataset_id: str
    dataset_version: DatasetVersion
    feature_version: FeatureVersion
    symbol: Symbol
    timeframe: Timeframe
    start_date: datetime
    end_date: datetime
    number_of_rows: int
    feature_columns: tuple[str, ...]
    label_columns: tuple[str, ...]
    manifest: DatasetManifest
    metadata: DatasetMetadata
    validation_report: ValidationReport
    hash: str

    def __post_init__(self) -> None:
        if self.number_of_rows < 0:
            raise InvalidResearchDatasetError(
                f"number_of_rows must be >= 0, got {self.number_of_rows}."
            )
        if self.number_of_rows > 0 and self.start_date > self.end_date:
            raise InvalidResearchDatasetError(
                f"start_date ({self.start_date}) must be <= end_date ({self.end_date})."
            )
        if len(self.feature_columns) != len(set(self.feature_columns)):
            raise InvalidResearchDatasetError(
                f"feature_columns must not contain duplicates: {self.feature_columns}."
            )
        if len(self.label_columns) != len(set(self.label_columns)):
            raise InvalidResearchDatasetError(
                f"label_columns must not contain duplicates: {self.label_columns}."
            )
        if not self.hash:
            raise InvalidResearchDatasetError("hash must not be empty.")
        if self.hash != self.manifest.hash:
            raise InvalidResearchDatasetError(
                f"hash ({self.hash!r}) must match manifest.hash ({self.manifest.hash!r})."
            )
        if self.number_of_rows != self.manifest.row_count:
            raise InvalidResearchDatasetError(
                f"number_of_rows ({self.number_of_rows}) must match "
                f"manifest.row_count ({self.manifest.row_count})."
            )
