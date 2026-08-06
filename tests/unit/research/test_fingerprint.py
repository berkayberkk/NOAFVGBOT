"""Unit tests for forex_daytrade.research.fingerprint."""

from __future__ import annotations

import pandas as pd
import pytest

from forex_daytrade.domain.symbol import Symbol
from forex_daytrade.domain.timeframe import Timeframe
from forex_daytrade.research.fingerprint import compute_fingerprint
from forex_daytrade.research.version import DatasetVersion, FeatureVersion


def _base_kwargs(raw_market_data_df: pd.DataFrame, sample_symbol: Symbol) -> dict[str, object]:
    return {
        "raw_data": raw_market_data_df,
        "feature_names": ["log_return", "high_low_range"],
        "configuration": {"broker_timezone": "UTC"},
        "dataset_version": DatasetVersion(1, 0, 0),
        "feature_version": FeatureVersion(1, 0, 0),
        "symbol": sample_symbol,
        "timeframe": Timeframe.M5,
    }


def test_fingerprint_is_reproducible(
    raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    kwargs = _base_kwargs(raw_market_data_df, sample_symbol)
    assert compute_fingerprint(**kwargs) == compute_fingerprint(**kwargs)  # type: ignore[arg-type]


def test_fingerprint_is_a_sha256_hex_digest(
    raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    digest = compute_fingerprint(**_base_kwargs(raw_market_data_df, sample_symbol))  # type: ignore[arg-type]
    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)


def test_feature_order_does_not_affect_fingerprint(
    raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    base = _base_kwargs(raw_market_data_df, sample_symbol)
    del base["feature_names"]
    forward = compute_fingerprint(feature_names=["a", "b", "c"], **base)  # type: ignore[arg-type]
    backward = compute_fingerprint(feature_names=["c", "b", "a"], **base)  # type: ignore[arg-type]
    assert forward == backward


@pytest.mark.parametrize(
    ("override_key", "override_value"),
    [
        ("feature_names", ["different_feature"]),
        ("configuration", {"broker_timezone": "Europe/Athens"}),
        ("dataset_version", DatasetVersion(2, 0, 0)),
        ("feature_version", FeatureVersion(2, 0, 0)),
        ("timeframe", Timeframe.M15),
    ],
)
def test_changing_any_input_changes_fingerprint(
    raw_market_data_df: pd.DataFrame,
    sample_symbol: Symbol,
    override_key: str,
    override_value: object,
) -> None:
    base = _base_kwargs(raw_market_data_df, sample_symbol)
    original = compute_fingerprint(**base)  # type: ignore[arg-type]
    changed = dict(base)
    changed[override_key] = override_value
    assert compute_fingerprint(**changed) != original  # type: ignore[arg-type]


def test_changing_symbol_changes_fingerprint(
    raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
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
    base = _base_kwargs(raw_market_data_df, sample_symbol)
    del base["symbol"]
    first = compute_fingerprint(symbol=sample_symbol, **base)  # type: ignore[arg-type]
    second = compute_fingerprint(symbol=other_symbol, **base)  # type: ignore[arg-type]
    assert first != second


def test_changing_raw_data_changes_fingerprint(
    raw_market_data_df: pd.DataFrame, sample_symbol: Symbol
) -> None:
    base = _base_kwargs(raw_market_data_df, sample_symbol)
    del base["raw_data"]
    mutated = raw_market_data_df.copy()
    mutated.loc[0, "close"] = mutated.loc[0, "close"] + 0.01
    first = compute_fingerprint(raw_data=raw_market_data_df, **base)  # type: ignore[arg-type]
    second = compute_fingerprint(raw_data=mutated, **base)  # type: ignore[arg-type]
    assert first != second
