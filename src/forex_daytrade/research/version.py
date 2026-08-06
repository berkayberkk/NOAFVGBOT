"""Semantic version value objects for the research dataset layer.

Three distinct, non-interchangeable version types, each tracking a
different concern that evolves independently:

- `DatasetVersion`: the schema/contract version of `ResearchDataset`
  itself (its field shape) — bump when that shape changes.
- `FeatureVersion`: the version of the feature set/configuration used to
  build a dataset — bump when features are added, removed, or their
  computation changes.
- `GeneratorVersion`: the version of the dataset-generation code itself
  (`builder.py`/`fingerprint.py`) — bump when the *machinery* that builds
  datasets changes, independent of the dataset schema or the feature set.

All three share `SemanticVersion`'s `(major, minor, patch)` shape and
`parse`/`__str__` behavior, but are distinct types: two instances of
different subclasses are never `==`, even with identical field values
(dataclass equality compares exact class identity), and mypy will reject
passing a `FeatureVersion` where a `DatasetVersion` is expected. This is
deliberate: a dataset's schema version and its feature-set version must
never be silently confused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self

_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class InvalidVersionError(ValueError):
    """Raised when a version string cannot be parsed as `major.minor.patch`."""


@dataclass(frozen=True, slots=True, order=True)
class SemanticVersion:
    """A `major.minor.patch` version number."""

    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("major", self.major),
            ("minor", self.minor),
            ("patch", self.patch),
        ):
            if value < 0:
                raise InvalidVersionError(f"{field_name} must be >= 0, got {value}.")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse a `"major.minor.patch"` string into this version type."""
        match = _VERSION_PATTERN.match(value)
        if match is None:
            raise InvalidVersionError(
                f"{value!r} is not a valid major.minor.patch version string."
            )
        major, minor, patch = (int(part) for part in match.groups())
        return cls(major=major, minor=minor, patch=patch)


class DatasetVersion(SemanticVersion):
    """Schema/contract version of `ResearchDataset` itself."""


class FeatureVersion(SemanticVersion):
    """Version of the feature set/configuration used to build a dataset."""


class GeneratorVersion(SemanticVersion):
    """Version of the dataset-generation code (`builder.py`/`fingerprint.py`)."""
