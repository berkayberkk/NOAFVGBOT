"""Unit tests for forex_daytrade.features.pipeline."""

from __future__ import annotations

import pandas as pd
import pytest

from forex_daytrade.features.base import (
    Feature,
    MissingRequiredColumnsError,
    UnexpectedOutputColumnsError,
)
from forex_daytrade.features.pipeline import (
    ColumnConflictError,
    DuplicateColumnError,
    FeaturePipeline,
)


class _AddOne(Feature):
    name = "add_one"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"close_plus_one"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=df.index)
        result["close_plus_one"] = df["close"] + 1
        return result


class _TimesTwo(Feature):
    name = "times_two"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"close_times_two"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=df.index)
        result["close_times_two"] = df["close"] * 2
        return result


class _LeadingNan(Feature):
    name = "leading_nan"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"leading_nan"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=df.index)
        result["leading_nan"] = df["close"].shift(1)
        return result


class _ConflictingDeclaration(Feature):
    """Declares the same generated column name as `_AddOne`."""

    name = "conflicting"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"close_plus_one"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=df.index)
        result["close_plus_one"] = df["close"]
        return result


class _OverwritesInputColumn(Feature):
    """Declares a generated column that collides with a raw input column."""

    name = "overwriter"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"close"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=df.index)
        result["close"] = df["close"] * 100
        return result


class _PeeksAtOtherColumns(Feature):
    """A feature that (incorrectly) tries to read a column it didn't declare."""

    name = "peeker"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"peeked"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=df.index)
        result["peeked"] = df["open"]  # not in required_columns
        return result


class _WrongOutputColumns(Feature):
    """Declares one generated column but returns a different one."""

    name = "wrong_output"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"expected_column"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame(index=df.index)
        result["actually_returned_column"] = df["close"]
        return result


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame({"open": [1.0, 2.0, 3.0], "close": [1.5, 2.5, 3.5]})


def test_pipeline_merges_generated_columns_with_input() -> None:
    pipeline = FeaturePipeline([_AddOne(), _TimesTwo()])
    result, _ = pipeline.run(_sample_df())
    assert list(result["close_plus_one"]) == [2.5, 3.5, 4.5]
    assert list(result["close_times_two"]) == [3.0, 5.0, 7.0]
    assert "open" in result.columns
    assert "close" in result.columns


def test_pipeline_missing_required_columns_raises() -> None:
    pipeline = FeaturePipeline([_AddOne()])
    with pytest.raises(MissingRequiredColumnsError, match="add_one"):
        pipeline.run(pd.DataFrame({"open": [1.0]}))


def test_pipeline_duplicate_generated_columns_raises_at_construction() -> None:
    with pytest.raises(DuplicateColumnError, match="close_plus_one"):
        FeaturePipeline([_AddOne(), _ConflictingDeclaration()])


def test_pipeline_column_conflict_with_input_raises_at_run() -> None:
    pipeline = FeaturePipeline([_OverwritesInputColumn()])
    with pytest.raises(ColumnConflictError, match="close"):
        pipeline.run(_sample_df())


def test_pipeline_report_tracks_features_columns_and_nan_counts() -> None:
    pipeline = FeaturePipeline([_AddOne(), _LeadingNan()])
    _, report = pipeline.run(_sample_df())
    assert report.computed_features == ("add_one", "leading_nan")
    assert set(report.generated_columns) == {"close_plus_one", "leading_nan"}
    assert report.nan_counts["leading_nan"] == 1
    assert report.nan_counts["close_plus_one"] == 0
    assert report.has_nans is True
    assert report.row_count == 3


def test_pipeline_report_has_nans_false_when_no_nans() -> None:
    pipeline = FeaturePipeline([_AddOne(), _TimesTwo()])
    _, report = pipeline.run(_sample_df())
    assert report.has_nans is False


def test_pipeline_order_does_not_affect_individual_feature_output() -> None:
    forward, _ = FeaturePipeline([_AddOne(), _TimesTwo()]).run(_sample_df())
    backward, _ = FeaturePipeline([_TimesTwo(), _AddOne()]).run(_sample_df())
    pd.testing.assert_series_equal(forward["close_plus_one"], backward["close_plus_one"])
    pd.testing.assert_series_equal(forward["close_times_two"], backward["close_times_two"])


def test_pipeline_only_passes_declared_required_columns_to_each_feature() -> None:
    pipeline = FeaturePipeline([_PeeksAtOtherColumns()])
    with pytest.raises(KeyError):
        pipeline.run(_sample_df())


def test_pipeline_enforces_feature_output_contract() -> None:
    pipeline = FeaturePipeline([_WrongOutputColumns()])
    with pytest.raises(UnexpectedOutputColumnsError):
        pipeline.run(_sample_df())


def test_empty_pipeline_returns_input_unchanged_with_empty_report() -> None:
    pipeline = FeaturePipeline([])
    result, report = pipeline.run(_sample_df())
    pd.testing.assert_frame_equal(result, _sample_df())
    assert report.computed_features == ()
    assert report.generated_columns == ()
    assert report.row_count == 3
