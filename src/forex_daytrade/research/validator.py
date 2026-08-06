"""Research-dataset-level validation.

Reuses `forex_daytrade.domain.validation.ValidationReport`/
`ValidationIssue`/`Severity` directly rather than defining a parallel
report shape — a research dataset's validation concerns (duplicate rows,
missing timestamps, duplicate feature names, empty dataset, NaN summary,
row/feature counts, fingerprint consistency) are generic enough that the
canonical domain contract fits without modification (see the Domain Layer
ownership rules in ARCHITECTURE.md).

This module does not re-validate raw MT5 ingestion quality (OHLC
consistency, spread anomalies, missing-bar gaps, etc.) —
`forex_daytrade.data.validator` already owns that, upstream of this layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import MappingProxyType
from typing import Any

import pandas as pd

from forex_daytrade.domain.validation import Severity, ValidationIssue, ValidationReport


def check_empty(df: pd.DataFrame) -> ValidationIssue | None:
    if len(df) == 0:
        return ValidationIssue(
            check="empty_dataset", severity=Severity.ERROR, message="Dataset has zero rows."
        )
    return None


def check_duplicate_rows(df: pd.DataFrame) -> ValidationIssue | None:
    count = int(df.duplicated(keep=False).sum())
    if count == 0:
        return None
    return ValidationIssue(
        check="duplicate_rows",
        severity=Severity.ERROR,
        message=f"Found {count} fully duplicated rows.",
    )


def check_missing_timestamps(df: pd.DataFrame, timestamp_column: str) -> ValidationIssue | None:
    if timestamp_column not in df.columns:
        return ValidationIssue(
            check="missing_timestamps",
            severity=Severity.ERROR,
            message=f"Timestamp column {timestamp_column!r} not present in dataset.",
        )
    count = int(df[timestamp_column].isna().sum())
    if count == 0:
        return None
    return ValidationIssue(
        check="missing_timestamps",
        severity=Severity.ERROR,
        message=f"Found {count} rows with a missing (NaT) {timestamp_column!r} value.",
    )


def check_duplicate_feature_names(feature_columns: Sequence[str]) -> ValidationIssue | None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in feature_columns:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if not duplicates:
        return None
    return ValidationIssue(
        check="duplicate_feature_names",
        severity=Severity.ERROR,
        message=f"Duplicate feature column names: {sorted(duplicates)}.",
    )


def check_row_count(df: pd.DataFrame, expected_row_count: int | None) -> ValidationIssue | None:
    if expected_row_count is None:
        return None
    actual = len(df)
    if actual == expected_row_count:
        return None
    return ValidationIssue(
        check="row_count",
        severity=Severity.ERROR,
        message=f"Expected {expected_row_count} rows, found {actual}.",
    )


def check_fingerprint_consistency(
    computed_fingerprint: str | None, expected_fingerprint: str | None
) -> ValidationIssue | None:
    if computed_fingerprint is None or expected_fingerprint is None:
        return None
    if computed_fingerprint == expected_fingerprint:
        return None
    return ValidationIssue(
        check="fingerprint_consistency",
        severity=Severity.ERROR,
        message=(
            f"Computed fingerprint {computed_fingerprint!r} does not match "
            f"expected fingerprint {expected_fingerprint!r}."
        ),
    )


def _nan_summary(
    df: pd.DataFrame, feature_columns: Sequence[str]
) -> tuple[dict[str, int], list[ValidationIssue]]:
    counts: dict[str, int] = {}
    issues: list[ValidationIssue] = []
    for column in feature_columns:
        if column not in df.columns:
            continue
        nan_count = int(df[column].isna().sum())
        counts[column] = nan_count
        if len(df) > 0 and nan_count == len(df):
            issues.append(
                ValidationIssue(
                    check="all_nan_feature_column",
                    severity=Severity.WARNING,
                    message=f"Feature column {column!r} is entirely NaN.",
                )
            )
    return counts, issues


def validate_research_dataset(
    df: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
    timestamp_column: str = "timestamp_utc",
    expected_row_count: int | None = None,
    computed_fingerprint: str | None = None,
    expected_fingerprint: str | None = None,
) -> ValidationReport:
    """Run the full suite of research-dataset-level checks.

    `expected_row_count`/`computed_fingerprint`+`expected_fingerprint` are
    optional defense-in-depth checks: when supplied, they let a caller
    re-verify a previously-built dataset against its recorded manifest
    values, not just validate a fresh build.
    """
    issues: list[ValidationIssue] = []

    empty_issue = check_empty(df)
    if empty_issue is not None:
        issues.append(empty_issue)
    else:
        for issue in (
            check_duplicate_rows(df),
            check_missing_timestamps(df, timestamp_column),
            check_row_count(df, expected_row_count),
            check_fingerprint_consistency(computed_fingerprint, expected_fingerprint),
        ):
            if issue is not None:
                issues.append(issue)

    duplicate_features_issue = check_duplicate_feature_names(feature_columns)
    if duplicate_features_issue is not None:
        issues.append(duplicate_features_issue)

    nan_counts, nan_issues = _nan_summary(df, feature_columns)
    issues.extend(nan_issues)

    statistics: dict[str, Any] = {
        "row_count": len(df),
        "feature_count": len(feature_columns),
        "nan_counts": nan_counts,
    }

    return ValidationReport(issues=tuple(issues), statistics=MappingProxyType(statistics))
