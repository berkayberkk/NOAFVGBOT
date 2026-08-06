"""Orchestrates `ResearchDataset` construction.

`DatasetBuilder` runs the Feature Pipeline over already-validated market
data, validates the result, computes the manifest and fingerprint, and
assembles the immutable `ResearchDataset`. It knows nothing about trading
strategies, signals, backtesting, or execution — its only concern is
turning (raw data + feature pipeline + configuration) into a reproducible,
identity-stamped research artifact.

`raw_data` passed to `build()` must already be validated/normalized
market data — the Data Layer's responsibility (see
`forex_daytrade.data.validator`), not this builder's. This builder only
validates *dataset-construction* concerns (see `validator.py`).
"""

from __future__ import annotations

import platform
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from forex_daytrade.domain.metadata import DatasetMetadata
from forex_daytrade.domain.symbol import Symbol
from forex_daytrade.domain.timeframe import Timeframe
from forex_daytrade.features.pipeline import FeaturePipeline
from forex_daytrade.research.dataset import ResearchDataset
from forex_daytrade.research.fingerprint import compute_fingerprint
from forex_daytrade.research.manifest import DatasetManifest
from forex_daytrade.research.validator import validate_research_dataset
from forex_daytrade.research.version import DatasetVersion, FeatureVersion, GeneratorVersion
from forex_daytrade.version import __version__ as _project_version

# Bump when the dataset schema (`ResearchDataset`'s field shape) changes.
DATASET_SCHEMA_VERSION = DatasetVersion(1, 0, 0)

# Bump when the generation machinery (this module / fingerprint.py) changes,
# independent of the dataset schema or the feature set.
GENERATOR_VERSION = GeneratorVersion(1, 0, 0)


class DatasetBuildError(Exception):
    """Raised when a dataset build fails validation and cannot proceed."""


@dataclass(frozen=True, slots=True)
class DatasetBuildResult:
    """A built dataset's identity object plus its underlying data.

    Kept separate from `ResearchDataset` itself so the identity object
    never embeds a mutable `pandas.DataFrame` — see `dataset.py`.
    """

    dataset: ResearchDataset
    data: pd.DataFrame


class DatasetBuilder:
    """Builds `ResearchDataset`s from already-validated market data."""

    def __init__(self, feature_pipeline: FeaturePipeline, feature_version: FeatureVersion) -> None:
        self._feature_pipeline = feature_pipeline
        self._feature_version = feature_version

    def build(
        self,
        raw_data: pd.DataFrame,
        *,
        symbol: Symbol,
        timeframe: Timeframe,
        source: str,
        configuration: Mapping[str, str],
        timestamp_column: str = "timestamp_utc",
        now: datetime | None = None,
    ) -> DatasetBuildResult:
        """Run the feature pipeline over `raw_data` and assemble a `ResearchDataset`."""
        featured_df, feature_report = self._feature_pipeline.run(raw_data)

        fingerprint = compute_fingerprint(
            raw_data=raw_data,
            feature_names=feature_report.generated_columns,
            configuration=configuration,
            dataset_version=DATASET_SCHEMA_VERSION,
            feature_version=self._feature_version,
            symbol=symbol,
            timeframe=timeframe,
        )

        validation_report = validate_research_dataset(
            featured_df,
            feature_columns=feature_report.generated_columns,
            timestamp_column=timestamp_column,
        )
        if not validation_report.is_valid:
            raise DatasetBuildError(
                f"Dataset failed validation: "
                f"{[issue.message for issue in validation_report.errors]}"
            )

        created_at = now if now is not None else datetime.now(UTC)
        row_count = len(featured_df)
        timestamps = featured_df[timestamp_column]
        start_date = timestamps.min().to_pydatetime() if row_count else created_at
        end_date = timestamps.max().to_pydatetime() if row_count else created_at

        manifest = DatasetManifest(
            dataset_version=DATASET_SCHEMA_VERSION,
            feature_version=self._feature_version,
            generator_version=GENERATOR_VERSION,
            created_at=created_at,
            feature_names=feature_report.generated_columns,
            configuration=configuration,
            python_version=platform.python_version(),
            project_version=_PROJECT_VERSION,
            symbol=symbol.name,
            timeframe=timeframe.value,
            start_date=start_date,
            end_date=end_date,
            row_count=row_count,
            hash=fingerprint,
        )

        metadata = DatasetMetadata(
            source=source,
            created_at=created_at,
            dataset_version=str(DATASET_SCHEMA_VERSION),
            row_count=row_count,
            start_timestamp=start_date,
            end_timestamp=end_date,
        )

        dataset_id = f"{symbol.name}_{timeframe.value}_{fingerprint[:12]}"

        dataset = ResearchDataset(
            dataset_id=dataset_id,
            dataset_version=DATASET_SCHEMA_VERSION,
            feature_version=self._feature_version,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            number_of_rows=row_count,
            feature_columns=feature_report.generated_columns,
            label_columns=(),
            manifest=manifest,
            metadata=metadata,
            validation_report=validation_report,
            hash=fingerprint,
        )
        return DatasetBuildResult(dataset=dataset, data=featured_df)
