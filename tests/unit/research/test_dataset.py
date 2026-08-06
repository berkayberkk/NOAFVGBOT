"""Unit tests for forex_daytrade.research.dataset."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from forex_daytrade.domain.metadata import DatasetMetadata
from forex_daytrade.domain.symbol import Symbol
from forex_daytrade.domain.timeframe import Timeframe
from forex_daytrade.domain.validation import ValidationReport
from forex_daytrade.research.dataset import InvalidResearchDatasetError, ResearchDataset
from forex_daytrade.research.manifest import DatasetManifest
from forex_daytrade.research.version import DatasetVersion, FeatureVersion, GeneratorVersion

_SYMBOL = Symbol(
    name="EURUSD",
    digits=5,
    point_size=0.00001,
    contract_size=100000.0,
    tick_value=1.0,
    min_volume=0.01,
    max_volume=100.0,
    volume_step=0.01,
)


def _make_manifest(**overrides: object) -> DatasetManifest:
    defaults: dict[str, object] = {
        "dataset_version": DatasetVersion(1, 0, 0),
        "feature_version": FeatureVersion(1, 0, 0),
        "generator_version": GeneratorVersion(1, 0, 0),
        "created_at": datetime(2024, 3, 4, tzinfo=UTC),
        "feature_names": ("log_return",),
        "configuration": {},
        "python_version": "3.12.0",
        "project_version": "0.1.0",
        "symbol": "EURUSD",
        "timeframe": "M5",
        "start_date": datetime(2024, 3, 4, tzinfo=UTC),
        "end_date": datetime(2024, 3, 5, tzinfo=UTC),
        "row_count": 10,
        "hash": "a" * 64,
    }
    defaults.update(overrides)
    return DatasetManifest(**defaults)  # type: ignore[arg-type]


def _make_dataset(**overrides: object) -> ResearchDataset:
    defaults: dict[str, object] = {
        "dataset_id": "EURUSD_M5_abc123",
        "dataset_version": DatasetVersion(1, 0, 0),
        "feature_version": FeatureVersion(1, 0, 0),
        "symbol": _SYMBOL,
        "timeframe": Timeframe.M5,
        "start_date": datetime(2024, 3, 4, tzinfo=UTC),
        "end_date": datetime(2024, 3, 5, tzinfo=UTC),
        "number_of_rows": 10,
        "feature_columns": ("log_return",),
        "label_columns": (),
        "manifest": _make_manifest(),
        "metadata": DatasetMetadata(
            source="MT5",
            created_at=datetime(2024, 3, 4, tzinfo=UTC),
            dataset_version="1.0.0",
            row_count=10,
            start_timestamp=datetime(2024, 3, 4, tzinfo=UTC),
            end_timestamp=datetime(2024, 3, 5, tzinfo=UTC),
        ),
        "validation_report": ValidationReport(),
        "hash": "a" * 64,
    }
    defaults.update(overrides)
    return ResearchDataset(**defaults)  # type: ignore[arg-type]


def test_construction_with_valid_values() -> None:
    dataset = _make_dataset()
    assert dataset.number_of_rows == 10
    assert dataset.symbol.name == "EURUSD"


def test_is_frozen() -> None:
    dataset = _make_dataset()
    with pytest.raises(AttributeError):
        dataset.number_of_rows = 99  # type: ignore[misc]


def test_equality_for_identical_datasets() -> None:
    assert _make_dataset() == _make_dataset()


def test_hash_must_match_manifest_hash() -> None:
    with pytest.raises(InvalidResearchDatasetError, match="manifest.hash"):
        _make_dataset(hash="b" * 64)


def test_row_count_must_match_manifest_row_count() -> None:
    with pytest.raises(InvalidResearchDatasetError, match="manifest.row_count"):
        _make_dataset(number_of_rows=5)


def test_duplicate_feature_columns_rejected() -> None:
    with pytest.raises(InvalidResearchDatasetError, match="feature_columns"):
        _make_dataset(feature_columns=("log_return", "log_return"))


def test_duplicate_label_columns_rejected() -> None:
    with pytest.raises(InvalidResearchDatasetError, match="label_columns"):
        _make_dataset(label_columns=("target", "target"))


def test_negative_row_count_rejected() -> None:
    with pytest.raises(InvalidResearchDatasetError, match="number_of_rows"):
        _make_dataset(number_of_rows=-1)


def test_start_after_end_rejected_when_rows_present() -> None:
    with pytest.raises(InvalidResearchDatasetError, match="start_date"):
        _make_dataset(
            start_date=datetime(2024, 3, 5, tzinfo=UTC),
            end_date=datetime(2024, 3, 4, tzinfo=UTC),
        )


def test_empty_hash_rejected() -> None:
    with pytest.raises(InvalidResearchDatasetError, match="hash"):
        _make_dataset(hash="")


def test_zero_rows_with_matching_manifest_allowed() -> None:
    dataset = _make_dataset(
        number_of_rows=0,
        start_date=datetime(2024, 3, 4, tzinfo=UTC),
        end_date=datetime(2024, 3, 4, tzinfo=UTC),
        manifest=_make_manifest(
            row_count=0,
            start_date=datetime(2024, 3, 4, tzinfo=UTC),
            end_date=datetime(2024, 3, 4, tzinfo=UTC),
        ),
    )
    assert dataset.number_of_rows == 0


def test_label_columns_default_placeholder_is_empty() -> None:
    dataset = _make_dataset()
    assert dataset.label_columns == ()
