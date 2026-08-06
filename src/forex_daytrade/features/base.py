"""Base interface for feature generators.

A `Feature` is a small, self-contained unit of computation: given a
DataFrame containing exactly its declared `required_columns`, it returns a
DataFrame containing exactly its declared `generated_columns`, computed
only from that bar and prior bars (never a future bar — see the Feature
Layer section of ARCHITECTURE.md).

Features must never read another feature's output or import another
feature class. `forex_daytrade.features.pipeline.FeaturePipeline` enforces
this structurally: it only ever passes a feature the columns that feature
itself declared as required, so a feature has no way to see another
feature's generated columns even if it tried.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import pandas as pd


class FeatureError(Exception):
    """Base class for all feature-layer errors."""


class MissingRequiredColumnsError(FeatureError):
    """Raised when a feature's input is missing one or more required columns."""


class UnexpectedOutputColumnsError(FeatureError):
    """Raised when `Feature.compute()` returns columns other than exactly
    its declared `generated_columns`."""


@dataclass(frozen=True, slots=True)
class FeatureMetadata:
    """Descriptive metadata for a single feature generator."""

    name: str
    required_columns: frozenset[str]
    generated_columns: frozenset[str]
    description: str


class Feature(ABC):
    """Common interface every feature generator implements.

    Concrete subclasses set `name`, `required_columns`, and
    `generated_columns` as plain class attributes (see `features/returns.py`
    etc. for examples) and implement `compute()`.
    """

    name: ClassVar[str]
    required_columns: ClassVar[frozenset[str]]
    generated_columns: ClassVar[frozenset[str]]

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute this feature's output columns from `df`.

        `df` contains exactly this feature's `required_columns` — never any
        other feature's generated columns, and never a column this feature
        did not declare it needs. The returned DataFrame must contain
        exactly `generated_columns`, sharing `df`'s index.
        """

    def validate_input(self, df: pd.DataFrame) -> None:
        """Raise `MissingRequiredColumnsError` if `df` lacks a required column."""
        missing = self.required_columns - set(df.columns)
        if missing:
            raise MissingRequiredColumnsError(
                f"{self.name!r} requires column(s) {sorted(missing)}, "
                f"not present in input (has {sorted(df.columns)})."
            )

    def validate_output(self, result: pd.DataFrame) -> None:
        """Raise `UnexpectedOutputColumnsError` if `result`'s columns don't
        exactly match `generated_columns`."""
        actual = frozenset(result.columns)
        if actual != self.generated_columns:
            raise UnexpectedOutputColumnsError(
                f"{self.name!r}.compute() returned columns {sorted(actual)}, "
                f"expected exactly {sorted(self.generated_columns)}."
            )

    def metadata(self) -> FeatureMetadata:
        """Return this feature's descriptive metadata."""
        return FeatureMetadata(
            name=self.name,
            required_columns=self.required_columns,
            generated_columns=self.generated_columns,
            description=(self.__doc__ or "").strip(),
        )
