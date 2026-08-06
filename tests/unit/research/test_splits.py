"""Unit tests for forex_daytrade.research.splits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from forex_daytrade.research.splits import (
    DatasetSplit,
    InvalidSplitError,
    SplitKind,
    chronological_train_validation_test_split,
)

_START = datetime(2024, 3, 4, 8, 0, tzinfo=UTC)


def _timestamped_df(n: int, start: datetime) -> pd.DataFrame:
    timestamps = [start + timedelta(minutes=5 * i) for i in range(n)]
    return pd.DataFrame(
        {"timestamp_utc": pd.to_datetime(timestamps, utc=True), "close": list(range(n))}
    )


def test_split_partitions_all_rows() -> None:
    df = _timestamped_df(30, _START)
    train, validation, test = chronological_train_validation_test_split(
        df,
        train_end=_START + timedelta(minutes=5 * 19),
        validation_end=_START + timedelta(minutes=5 * 24),
    )
    assert train.row_count + validation.row_count + test.row_count == 30
    assert train.row_count == 20
    assert validation.row_count == 5
    assert test.row_count == 5


def test_splits_are_non_overlapping_and_ordered() -> None:
    df = _timestamped_df(30, _START)
    train, validation, test = chronological_train_validation_test_split(
        df,
        train_end=_START + timedelta(minutes=5 * 19),
        validation_end=_START + timedelta(minutes=5 * 24),
    )
    assert train.end_date is not None
    assert validation.start_date is not None
    assert train.end_date < validation.start_date
    assert validation.end_date is not None
    assert test.start_date is not None
    assert validation.end_date < test.start_date


def test_split_kinds_are_assigned_correctly() -> None:
    df = _timestamped_df(10, _START)
    train, validation, test = chronological_train_validation_test_split(
        df,
        train_end=_START + timedelta(minutes=5 * 4),
        validation_end=_START + timedelta(minutes=5 * 6),
    )
    assert train.kind is SplitKind.TRAIN
    assert validation.kind is SplitKind.VALIDATION
    assert test.kind is SplitKind.TEST


def test_unsorted_input_rejected() -> None:
    df = _timestamped_df(10, _START).iloc[::-1].reset_index(drop=True)
    with pytest.raises(InvalidSplitError, match="sorted"):
        chronological_train_validation_test_split(
            df,
            train_end=_START + timedelta(minutes=5),
            validation_end=_START + timedelta(minutes=10),
        )


def test_train_end_after_validation_end_rejected() -> None:
    df = _timestamped_df(10, _START)
    with pytest.raises(InvalidSplitError, match="train_end"):
        chronological_train_validation_test_split(
            df,
            train_end=_START + timedelta(minutes=20),
            validation_end=_START + timedelta(minutes=10),
        )


def test_train_end_equal_to_validation_end_rejected() -> None:
    df = _timestamped_df(10, _START)
    same = _START + timedelta(minutes=10)
    with pytest.raises(InvalidSplitError, match="train_end"):
        chronological_train_validation_test_split(df, train_end=same, validation_end=same)


def test_empty_segment_has_none_dates() -> None:
    df = _timestamped_df(5, _START)
    _, validation, test = chronological_train_validation_test_split(
        df,
        train_end=_START + timedelta(minutes=5 * 100),
        validation_end=_START + timedelta(minutes=5 * 200),
    )
    assert validation.row_count == 0
    assert validation.start_date is None
    assert validation.end_date is None
    assert test.row_count == 0
    assert test.start_date is None


def test_walk_forward_kind_exists_as_placeholder() -> None:
    assert SplitKind.WALK_FORWARD.value == "walk_forward"


def test_dataset_split_rejects_negative_row_count() -> None:
    with pytest.raises(InvalidSplitError):
        DatasetSplit(kind=SplitKind.TRAIN, start_date=None, end_date=None, row_count=-1)


def test_dataset_split_requires_dates_when_rows_present() -> None:
    with pytest.raises(InvalidSplitError):
        DatasetSplit(kind=SplitKind.TRAIN, start_date=None, end_date=None, row_count=5)


def test_dataset_split_rejects_start_after_end() -> None:
    with pytest.raises(InvalidSplitError):
        DatasetSplit(
            kind=SplitKind.TRAIN,
            start_date=_START + timedelta(minutes=10),
            end_date=_START,
            row_count=1,
        )


def test_dataset_split_allows_zero_rows_with_no_dates() -> None:
    split = DatasetSplit(kind=SplitKind.TEST, start_date=None, end_date=None, row_count=0)
    assert split.row_count == 0
