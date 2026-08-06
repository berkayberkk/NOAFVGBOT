"""Unit tests for forex_daytrade.research.manifest."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from forex_daytrade.research.manifest import DatasetManifest, InvalidManifestError
from forex_daytrade.research.version import DatasetVersion, FeatureVersion, GeneratorVersion


def _make_manifest(**overrides: object) -> DatasetManifest:
    defaults: dict[str, object] = {
        "dataset_version": DatasetVersion(1, 0, 0),
        "feature_version": FeatureVersion(1, 0, 0),
        "generator_version": GeneratorVersion(1, 0, 0),
        "created_at": datetime(2024, 3, 4, tzinfo=UTC),
        "feature_names": ("log_return", "high_low_range"),
        "configuration": {"broker_timezone": "UTC"},
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


def test_construction_with_valid_values() -> None:
    manifest = _make_manifest()
    assert manifest.row_count == 10
    assert manifest.symbol == "EURUSD"


def test_configuration_is_read_only() -> None:
    manifest = _make_manifest()
    with pytest.raises(TypeError):
        manifest.configuration["new_key"] = "value"  # type: ignore[index]


def test_configuration_defensive_copy_not_aliased() -> None:
    original = {"broker_timezone": "UTC"}
    manifest = _make_manifest(configuration=original)
    original["broker_timezone"] = "Europe/Athens"
    assert manifest.configuration["broker_timezone"] == "UTC"


def test_duplicate_feature_names_rejected() -> None:
    with pytest.raises(InvalidManifestError, match="duplicate"):
        _make_manifest(feature_names=("log_return", "log_return"))


def test_negative_row_count_rejected() -> None:
    with pytest.raises(InvalidManifestError, match="row_count"):
        _make_manifest(row_count=-1)


def test_start_after_end_rejected() -> None:
    with pytest.raises(InvalidManifestError, match="start_date"):
        _make_manifest(
            start_date=datetime(2024, 3, 5, tzinfo=UTC),
            end_date=datetime(2024, 3, 4, tzinfo=UTC),
        )


def test_zero_row_count_with_equal_dates_allowed() -> None:
    manifest = _make_manifest(
        row_count=0,
        start_date=datetime(2024, 3, 4, tzinfo=UTC),
        end_date=datetime(2024, 3, 4, tzinfo=UTC),
    )
    assert manifest.row_count == 0


def test_empty_hash_rejected() -> None:
    with pytest.raises(InvalidManifestError, match="hash"):
        _make_manifest(hash="")


def test_is_frozen() -> None:
    manifest = _make_manifest()
    with pytest.raises(AttributeError):
        manifest.row_count = 99  # type: ignore[misc]


def test_equality_for_identical_manifests() -> None:
    assert _make_manifest() == _make_manifest()
