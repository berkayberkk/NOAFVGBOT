"""Composable feature pipeline.

`FeaturePipeline` validates its input, runs each configured `Feature`
exactly once against *only that feature's declared required columns* (never
the full input, and never another feature's output), collects the results,
and reports on what it computed. Slicing each feature's input down to just
its `required_columns` is what makes "no feature may know about another
feature" an enforced property rather than just a convention: a feature
literally cannot read a column it did not declare.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import pandas as pd

from forex_daytrade.features.base import Feature, FeatureError, MissingRequiredColumnsError


class DuplicateColumnError(FeatureError):
    """Raised when two features in the same pipeline declare overlapping
    `generated_columns`."""


class ColumnConflictError(FeatureError):
    """Raised when a feature's actual output columns collide with columns
    already present in the input data or produced by an earlier feature."""


@dataclass(frozen=True, slots=True)
class FeatureReport:
    """Summary of a single `FeaturePipeline.run()` call."""

    computed_features: tuple[str, ...]
    generated_columns: tuple[str, ...]
    nan_counts: Mapping[str, int]
    row_count: int

    @property
    def has_nans(self) -> bool:
        """Whether any generated column contains at least one NaN value.

        This is informational, not an error: leading NaNs are expected and
        correct for features like `log_return` (no prior bar for the first
        row) or `rolling_std_20` (fewer than 20 prior bars for the first 19
        rows) — rejecting them would mean either fabricating data for bars
        that don't exist, or silently dropping rows, both worse than
        surfacing the NaN and letting downstream consumers decide.
        """
        return any(count > 0 for count in self.nan_counts.values())


class FeaturePipeline:
    """Runs an ordered sequence of `Feature` generators over a DataFrame.

    Order is caller-controlled: pass features in the desired order. Because
    each feature only ever sees its own declared `required_columns`,
    reordering the list can never change what any individual feature
    computes — order only affects `FeatureReport.computed_features`'
    ordering and, if two features' declared columns overlap, which one is
    reported as the original owner in `DuplicateColumnError`.
    """

    def __init__(self, features: Sequence[Feature]) -> None:
        self._features = tuple(features)
        self._validate_no_declared_column_overlap()

    @property
    def features(self) -> tuple[Feature, ...]:
        return self._features

    def _validate_no_declared_column_overlap(self) -> None:
        seen: dict[str, str] = {}
        for feature in self._features:
            for column in feature.generated_columns:
                if column in seen:
                    raise DuplicateColumnError(
                        f"Both {seen[column]!r} and {feature.name!r} declare "
                        f"generated column {column!r}."
                    )
                seen[column] = feature.name

    def _validate_required_columns(self, df: pd.DataFrame) -> None:
        available = set(df.columns)
        missing = {
            feature.name: sorted(feature.required_columns - available)
            for feature in self._features
            if feature.required_columns - available
        }
        if missing:
            details = ", ".join(f"{name}: {cols}" for name, cols in missing.items())
            raise MissingRequiredColumnsError(
                f"Input is missing required columns for one or more features: {details}"
            )

    def run(self, df: pd.DataFrame) -> tuple[pd.DataFrame, FeatureReport]:
        """Run every feature against `df`.

        Returns `df` augmented with every feature's generated columns,
        plus a `FeatureReport` describing what was computed.
        """
        self._validate_required_columns(df)

        result = df.copy()
        seen_columns = set(df.columns)
        nan_counts: dict[str, int] = {}
        computed_features: list[str] = []

        for feature in self._features:
            feature_input = df[list(feature.required_columns)]
            output = feature.compute(feature_input)
            feature.validate_output(output)

            conflicts = set(output.columns) & seen_columns
            if conflicts:
                raise ColumnConflictError(
                    f"{feature.name!r} produced column(s) {sorted(conflicts)} that "
                    f"already exist in the input or an earlier feature's output."
                )

            for column in output.columns:
                nan_counts[column] = int(output[column].isna().sum())
            seen_columns.update(output.columns)
            result = result.join(output)
            computed_features.append(feature.name)

        return result, FeatureReport(
            computed_features=tuple(computed_features),
            generated_columns=tuple(nan_counts),
            nan_counts=MappingProxyType(nan_counts),
            row_count=len(df),
        )
