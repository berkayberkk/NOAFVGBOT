"""Unit tests for forex_daytrade.research.validator."""

from __future__ import annotations

import pandas as pd
import pytest

from forex_daytrade.domain.validation import Severity
from forex_daytrade.research.validator import validate_research_dataset


def _valid_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                ["2024-03-04T08:00Z", "2024-03-04T08:05Z", "2024-03-04T08:10Z"], utc=True
            ),
            "close": [1.10, 1.11, 1.12],
            "log_return": [None, 0.009, 0.009],
        }
    )


def test_valid_dataset_has_no_errors() -> None:
    report = validate_research_dataset(_valid_df(), feature_columns=["log_return"])
    assert report.is_valid
    assert report.errors == ()


def test_empty_dataset_is_an_error() -> None:
    report = validate_research_dataset(_valid_df().iloc[0:0], feature_columns=["log_return"])
    assert not report.is_valid
    assert report.errors[0].check == "empty_dataset"


def test_duplicate_rows_is_an_error() -> None:
    df = pd.concat([_valid_df(), _valid_df().iloc[[0]]], ignore_index=True)
    report = validate_research_dataset(df, feature_columns=["log_return"])
    checks = {issue.check for issue in report.issues}
    assert "duplicate_rows" in checks
    assert not report.is_valid


def test_missing_timestamp_column_is_an_error() -> None:
    report = validate_research_dataset(
        _valid_df(), feature_columns=["log_return"], timestamp_column="does_not_exist"
    )
    checks = {issue.check for issue in report.issues}
    assert "missing_timestamps" in checks
    assert not report.is_valid


def test_missing_timestamp_values_is_an_error() -> None:
    df = _valid_df()
    df.loc[1, "timestamp_utc"] = pd.NaT
    report = validate_research_dataset(df, feature_columns=["log_return"])
    checks = {issue.check for issue in report.issues}
    assert "missing_timestamps" in checks
    assert not report.is_valid


def test_duplicate_feature_names_is_an_error() -> None:
    report = validate_research_dataset(_valid_df(), feature_columns=["log_return", "log_return"])
    checks = {issue.check for issue in report.issues}
    assert "duplicate_feature_names" in checks
    assert not report.is_valid


def test_all_nan_feature_column_is_a_warning() -> None:
    df = _valid_df()
    df["log_return"] = None
    report = validate_research_dataset(df, feature_columns=["log_return"])
    checks = {issue.check: issue for issue in report.issues}
    assert "all_nan_feature_column" in checks
    assert checks["all_nan_feature_column"].severity == Severity.WARNING
    assert report.is_valid  # warnings alone don't invalidate the dataset


def test_statistics_include_row_and_feature_counts() -> None:
    report = validate_research_dataset(_valid_df(), feature_columns=["log_return"])
    assert report.statistics["row_count"] == 3
    assert report.statistics["feature_count"] == 1
    assert report.statistics["nan_counts"]["log_return"] == 1


def test_row_count_mismatch_is_an_error() -> None:
    report = validate_research_dataset(
        _valid_df(), feature_columns=["log_return"], expected_row_count=99
    )
    checks = {issue.check for issue in report.issues}
    assert "row_count" in checks


def test_row_count_match_is_not_an_error() -> None:
    report = validate_research_dataset(
        _valid_df(), feature_columns=["log_return"], expected_row_count=3
    )
    checks = {issue.check for issue in report.issues}
    assert "row_count" not in checks


def test_fingerprint_mismatch_is_an_error() -> None:
    report = validate_research_dataset(
        _valid_df(),
        feature_columns=["log_return"],
        computed_fingerprint="abc",
        expected_fingerprint="def",
    )
    checks = {issue.check for issue in report.issues}
    assert "fingerprint_consistency" in checks


def test_fingerprint_match_is_not_an_error() -> None:
    report = validate_research_dataset(
        _valid_df(),
        feature_columns=["log_return"],
        computed_fingerprint="abc",
        expected_fingerprint="abc",
    )
    checks = {issue.check for issue in report.issues}
    assert "fingerprint_consistency" not in checks


def test_fingerprint_check_skipped_when_not_provided() -> None:
    report = validate_research_dataset(_valid_df(), feature_columns=["log_return"])
    checks = {issue.check for issue in report.issues}
    assert "fingerprint_consistency" not in checks


def test_statistics_are_read_only() -> None:
    report = validate_research_dataset(_valid_df(), feature_columns=["log_return"])
    with pytest.raises(TypeError):
        report.statistics["row_count"] = 0  # type: ignore[index]
