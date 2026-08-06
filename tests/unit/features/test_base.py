"""Unit tests for forex_daytrade.features.base."""

from __future__ import annotations

import pandas as pd
import pytest

from forex_daytrade.features.base import (
    Feature,
    FeatureMetadata,
    MissingRequiredColumnsError,
    UnexpectedOutputColumnsError,
)


class _DoubleClose(Feature):
    """Twice the close price (test-only dummy feature)."""

    name = "double_close"
    required_columns = frozenset({"close"})
    generated_columns = frozenset({"double_close"})

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate_input(df)
        result = pd.DataFrame(index=df.index)
        result["double_close"] = df["close"] * 2
        self.validate_output(result)
        return result


def test_compute_returns_expected_column() -> None:
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
    result = _DoubleClose().compute(df)
    assert list(result["double_close"]) == [2.0, 4.0, 6.0]


def test_metadata() -> None:
    feature = _DoubleClose()
    metadata = feature.metadata()
    assert metadata == FeatureMetadata(
        name="double_close",
        required_columns=frozenset({"close"}),
        generated_columns=frozenset({"double_close"}),
        description="Twice the close price (test-only dummy feature).",
    )


def test_validate_input_raises_on_missing_column() -> None:
    feature = _DoubleClose()
    with pytest.raises(MissingRequiredColumnsError, match="close"):
        feature.validate_input(pd.DataFrame({"open": [1.0]}))


def test_validate_input_passes_when_column_present() -> None:
    feature = _DoubleClose()
    feature.validate_input(pd.DataFrame({"close": [1.0]}))


def test_validate_output_raises_on_unexpected_columns() -> None:
    feature = _DoubleClose()
    with pytest.raises(UnexpectedOutputColumnsError):
        feature.validate_output(pd.DataFrame({"wrong_name": [1.0]}))


def test_validate_output_passes_on_exact_match() -> None:
    feature = _DoubleClose()
    feature.validate_output(pd.DataFrame({"double_close": [2.0]}))


def test_feature_cannot_be_instantiated_without_compute() -> None:
    with pytest.raises(TypeError):
        Feature()  # type: ignore[abstract]
