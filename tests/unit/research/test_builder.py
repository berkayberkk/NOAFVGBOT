"""Unit tests for forex_daytrade.research.builder."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from forex_daytrade.domain.symbol import Symbol
from forex_daytrade.domain.timeframe import Timeframe
from forex_daytrade.features.pipeline import FeaturePipeline
from forex_daytrade.features.price import HighLowRangeFeature
from forex_daytrade.features.returns import LogReturnFeature
from forex_daytrade.research.builder import DatasetBuilder, DatasetBuildError
from forex_daytrade.research.version import FeatureVersion


@pytest.fixture
def builder() -> DatasetBuilder:
    pipeline = FeaturePipeline([LogReturnFeature(), HighLowRangeFeature()])
    return DatasetBuilder(pipeline, FeatureVersion(1, 0, 0))


def test_build_produces_valid_dataset(
    builder: DatasetBuilder, raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    result = builder.build(
        raw_market_data_df,
        symbol=sample_symbol,
        timeframe=Timeframe.M5,
        source="MT5",
        configuration={"broker_timezone": "UTC"},
    )
    assert result.dataset.number_of_rows == len(raw_market_data_df)
    assert set(result.dataset.feature_columns) == {"log_return", "high_low_range"}
    assert result.dataset.validation_report.is_valid
    assert result.dataset.hash == result.dataset.manifest.hash
    assert "log_return" in result.data.columns
    assert "high_low_range" in result.data.columns


def test_build_is_reproducible(
    builder: DatasetBuilder, raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    kwargs: dict[str, object] = {
        "symbol": sample_symbol,
        "timeframe": Timeframe.M5,
        "source": "MT5",
        "configuration": {"broker_timezone": "UTC"},
    }
    first = builder.build(raw_market_data_df, **kwargs)  # type: ignore[arg-type]
    second = builder.build(raw_market_data_df, **kwargs)  # type: ignore[arg-type]
    assert first.dataset.hash == second.dataset.hash
    assert first.dataset.dataset_id == second.dataset.dataset_id


def test_build_with_fixed_now_produces_identical_manifest(
    builder: DatasetBuilder, raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    now = datetime(2024, 6, 1, tzinfo=UTC)
    kwargs: dict[str, object] = {
        "symbol": sample_symbol,
        "timeframe": Timeframe.M5,
        "source": "MT5",
        "configuration": {"broker_timezone": "UTC"},
        "now": now,
    }
    first = builder.build(raw_market_data_df, **kwargs)  # type: ignore[arg-type]
    second = builder.build(raw_market_data_df, **kwargs)  # type: ignore[arg-type]
    assert first.dataset.manifest == second.dataset.manifest
    assert first.dataset == second.dataset


def test_different_configuration_changes_fingerprint(
    builder: DatasetBuilder, raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    kwargs: dict[str, object] = {
        "symbol": sample_symbol,
        "timeframe": Timeframe.M5,
        "source": "MT5",
    }
    first = builder.build(
        raw_market_data_df, configuration={"broker_timezone": "UTC"}, **kwargs
    )  # type: ignore[arg-type]
    second = builder.build(
        raw_market_data_df, configuration={"broker_timezone": "Europe/Athens"}, **kwargs
    )  # type: ignore[arg-type]
    assert first.dataset.hash != second.dataset.hash


def test_different_symbol_changes_fingerprint_and_dataset_id(
    builder: DatasetBuilder, raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    other_symbol = Symbol(
        name="GBPUSD",
        digits=5,
        point_size=0.00001,
        contract_size=100000.0,
        tick_value=1.0,
        min_volume=0.01,
        max_volume=100.0,
        volume_step=0.01,
    )
    kwargs: dict[str, object] = {
        "timeframe": Timeframe.M5,
        "source": "MT5",
        "configuration": {},
    }
    first = builder.build(raw_market_data_df, symbol=sample_symbol, **kwargs)  # type: ignore[arg-type]
    second = builder.build(raw_market_data_df, symbol=other_symbol, **kwargs)  # type: ignore[arg-type]
    assert first.dataset.hash != second.dataset.hash
    assert first.dataset.dataset_id != second.dataset.dataset_id


def test_build_rejects_empty_input(builder: DatasetBuilder, sample_symbol: Symbol) -> None:
    empty = pd.DataFrame(
        {
            "timestamp_utc": pd.Series(dtype="datetime64[ns, UTC]"),
            "open": pd.Series(dtype=float),
            "high": pd.Series(dtype=float),
            "low": pd.Series(dtype=float),
            "close": pd.Series(dtype=float),
        }
    )
    with pytest.raises(DatasetBuildError):
        builder.build(
            empty, symbol=sample_symbol, timeframe=Timeframe.M5, source="MT5", configuration={}
        )


def test_builder_does_not_mutate_input(
    builder: DatasetBuilder, raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    original = raw_market_data_df.copy()
    builder.build(
        raw_market_data_df,
        symbol=sample_symbol,
        timeframe=Timeframe.M5,
        source="MT5",
        configuration={},
    )
    pd.testing.assert_frame_equal(raw_market_data_df, original)


def test_manifest_records_expected_fields(
    builder: DatasetBuilder, raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    result = builder.build(
        raw_market_data_df,
        symbol=sample_symbol,
        timeframe=Timeframe.M5,
        source="MT5",
        configuration={"broker_timezone": "UTC"},
    )
    manifest = result.dataset.manifest
    assert manifest.symbol == "EURUSD"
    assert manifest.timeframe == "M5"
    assert manifest.row_count == len(raw_market_data_df)
    assert set(manifest.feature_names) == {"log_return", "high_low_range"}
    assert manifest.hash == result.dataset.hash
    assert manifest.python_version
    assert manifest.project_version == "0.1.0"
