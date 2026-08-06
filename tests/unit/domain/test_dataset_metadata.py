"""Unit tests for forex_daytrade.domain.metadata."""

from datetime import UTC, datetime

import pytest

from forex_daytrade.domain.metadata import DatasetMetadata
from forex_daytrade.exceptions.data import InvalidMetadataError


def _make_metadata(**overrides: object) -> DatasetMetadata:
    defaults: dict[str, object] = {
        "source": "mt5",
        "created_at": datetime(2026, 1, 5, tzinfo=UTC),
        "dataset_version": "v1",
        "row_count": 10,
        "start_timestamp": datetime(2026, 1, 1, tzinfo=UTC),
        "end_timestamp": datetime(2026, 1, 5, tzinfo=UTC),
    }
    defaults.update(overrides)
    return DatasetMetadata(**defaults)  # type: ignore[arg-type]


def test_construction_with_valid_values() -> None:
    metadata = _make_metadata()
    assert metadata.row_count == 10
    assert metadata.source == "mt5"


def test_equality() -> None:
    assert _make_metadata() == _make_metadata()


def test_inequality() -> None:
    assert _make_metadata() != _make_metadata(source="other")


def test_zero_row_count_with_equal_timestamps_allowed() -> None:
    metadata = _make_metadata(
        row_count=0,
        start_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        end_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert metadata.row_count == 0


def test_negative_row_count_rejected() -> None:
    with pytest.raises(InvalidMetadataError, match="row_count"):
        _make_metadata(row_count=-1)


def test_start_after_end_rejected() -> None:
    with pytest.raises(InvalidMetadataError, match="start_timestamp"):
        _make_metadata(
            start_timestamp=datetime(2026, 1, 5, tzinfo=UTC),
            end_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        )
