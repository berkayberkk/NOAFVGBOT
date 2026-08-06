"""Unit tests for forex_daytrade.research.version."""

from __future__ import annotations

import pytest

from forex_daytrade.research.version import (
    DatasetVersion,
    FeatureVersion,
    GeneratorVersion,
    InvalidVersionError,
    SemanticVersion,
)


def test_str_format() -> None:
    assert str(SemanticVersion(1, 2, 3)) == "1.2.3"


def test_parse_round_trip() -> None:
    assert SemanticVersion.parse("2.10.7") == SemanticVersion(2, 10, 7)


def test_parse_preserves_subclass_type() -> None:
    version = DatasetVersion.parse("1.0.0")
    assert isinstance(version, DatasetVersion)
    assert not isinstance(version, FeatureVersion)


@pytest.mark.parametrize("bad_value", ["1.0", "1.0.0.0", "a.b.c", "", "1.0.-1", "v1.0.0"])
def test_parse_rejects_invalid_strings(bad_value: str) -> None:
    with pytest.raises(InvalidVersionError):
        SemanticVersion.parse(bad_value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"major": -1, "minor": 0, "patch": 0},
        {"major": 0, "minor": -1, "patch": 0},
        {"major": 0, "minor": 0, "patch": -1},
    ],
)
def test_negative_components_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(InvalidVersionError):
        SemanticVersion(**kwargs)


def test_ordering_within_same_type() -> None:
    assert DatasetVersion(1, 0, 0) < DatasetVersion(1, 1, 0)
    assert DatasetVersion(2, 0, 0) > DatasetVersion(1, 9, 9)


def test_equality_requires_same_subclass() -> None:
    assert DatasetVersion(1, 0, 0) != FeatureVersion(1, 0, 0)
    assert DatasetVersion(1, 0, 0) == DatasetVersion(1, 0, 0)


def test_ordering_across_subclasses_raises_type_error() -> None:
    with pytest.raises(TypeError):
        _ = DatasetVersion(1, 0, 0) < FeatureVersion(2, 0, 0)  # type: ignore[operator]


def test_three_version_types_are_distinct_classes() -> None:
    assert DatasetVersion is not FeatureVersion
    assert FeatureVersion is not GeneratorVersion
    assert DatasetVersion is not GeneratorVersion


def test_is_frozen() -> None:
    version = DatasetVersion(1, 0, 0)
    with pytest.raises(AttributeError):
        version.major = 2  # type: ignore[misc]
