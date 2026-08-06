"""Chronological dataset splits: train / validation / test.

Only time-ordered, boundary-based splits are supported — there is no
random splitting anywhere in this module, and split boundaries never
overlap, so a later split can never leak into an earlier one's training
data. This mirrors the same no-look-ahead-bias discipline the Data and
Feature layers already enforce (see ARCHITECTURE.md).

`SplitKind.WALK_FORWARD` exists as a vocabulary placeholder only — no
walk-forward window-generation function is implemented here. Walk-forward
*validation* is Phase 5 work (see DEVELOPMENT_ROADMAP.md); this sprint
only ensures the vocabulary already has a place for it so that work won't
need to change this enum later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import pandas as pd


class InvalidSplitError(Exception):
    """Raised when requested split boundaries would overlap or aren't chronological."""


class SplitKind(StrEnum):
    """The role a chronological segment of a dataset plays in research."""

    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    WALK_FORWARD = "walk_forward"


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    """A single named, chronologically-bounded segment of a dataset."""

    kind: SplitKind
    start_date: datetime | None
    end_date: datetime | None
    row_count: int

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise InvalidSplitError(f"row_count must be >= 0, got {self.row_count}.")
        if self.row_count > 0:
            if self.start_date is None or self.end_date is None:
                raise InvalidSplitError(
                    "start_date and end_date are required when row_count > 0."
                )
            if self.start_date > self.end_date:
                raise InvalidSplitError(
                    f"start_date ({self.start_date}) must be <= end_date ({self.end_date})."
                )


def _require_sorted(df: pd.DataFrame, timestamp_column: str) -> None:
    if not df[timestamp_column].is_monotonic_increasing:
        raise InvalidSplitError(
            f"Input must be sorted ascending by {timestamp_column!r} before splitting "
            f"(an unsorted input could otherwise silently leak future rows into an "
            f"earlier split)."
        )


def _build_split(kind: SplitKind, segment: pd.DataFrame, timestamp_column: str) -> DatasetSplit:
    if len(segment) == 0:
        return DatasetSplit(kind=kind, start_date=None, end_date=None, row_count=0)
    timestamps = segment[timestamp_column]
    return DatasetSplit(
        kind=kind,
        start_date=timestamps.min().to_pydatetime(),
        end_date=timestamps.max().to_pydatetime(),
        row_count=len(segment),
    )


def chronological_train_validation_test_split(
    df: pd.DataFrame,
    *,
    train_end: datetime,
    validation_end: datetime,
    timestamp_column: str = "timestamp_utc",
) -> tuple[DatasetSplit, DatasetSplit, DatasetSplit]:
    """Split `df` into three chronologically-ordered, non-overlapping segments.

    Rows with `timestamp <= train_end` become TRAIN; rows with
    `train_end < timestamp <= validation_end` become VALIDATION;
    everything after `validation_end` becomes TEST. `df` must already be
    sorted ascending by `timestamp_column` — this is checked, not assumed.
    """
    _require_sorted(df, timestamp_column)
    if train_end >= validation_end:
        raise InvalidSplitError(
            f"train_end ({train_end}) must be strictly before validation_end "
            f"({validation_end})."
        )

    timestamps = df[timestamp_column]
    train_mask = timestamps <= train_end
    validation_mask = (timestamps > train_end) & (timestamps <= validation_end)
    test_mask = timestamps > validation_end

    return (
        _build_split(SplitKind.TRAIN, df.loc[train_mask], timestamp_column),
        _build_split(SplitKind.VALIDATION, df.loc[validation_mask], timestamp_column),
        _build_split(SplitKind.TEST, df.loc[test_mask], timestamp_column),
    )
