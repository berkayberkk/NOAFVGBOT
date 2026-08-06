"""The dataset manifest: a portable, path-free record of exactly how a
`ResearchDataset` was built — enough to audit and reproduce it from the
same raw inputs. Every field is a primitive, a version object, or a plain
string/mapping — never an absolute local filesystem path — so a manifest
can be copied between machines or committed to source control without
leaking anything environment-specific.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from forex_daytrade.research.version import DatasetVersion, FeatureVersion, GeneratorVersion


class InvalidManifestError(Exception):
    """Raised when a `DatasetManifest`'s fields are internally inconsistent."""


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Everything needed to describe, audit, and reproduce a dataset build.

    `configuration` holds the actual configuration values that affected
    construction (e.g. `{"broker_timezone": "UTC", "source": "MT5"}`), not
    an opaque version tag — callers must never put an absolute local path
    into it. It is coerced to a read-only mapping in `__post_init__`.
    """

    dataset_version: DatasetVersion
    feature_version: FeatureVersion
    generator_version: GeneratorVersion
    created_at: datetime
    feature_names: tuple[str, ...]
    configuration: Mapping[str, str]
    python_version: str
    project_version: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    row_count: int
    hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration", MappingProxyType(dict(self.configuration)))
        if len(self.feature_names) != len(set(self.feature_names)):
            raise InvalidManifestError(
                f"feature_names must not contain duplicates: {self.feature_names}."
            )
        if self.row_count < 0:
            raise InvalidManifestError(f"row_count must be >= 0, got {self.row_count}.")
        if self.row_count > 0 and self.start_date > self.end_date:
            raise InvalidManifestError(
                f"start_date ({self.start_date}) must be <= end_date ({self.end_date})."
            )
        if not self.hash:
            raise InvalidManifestError("hash must not be empty.")
