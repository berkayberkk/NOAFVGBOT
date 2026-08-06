"""Unit tests for forex_daytrade.features.registry."""

from __future__ import annotations

import pandas as pd
import pytest

import forex_daytrade.features  # noqa: F401  (triggers baseline feature registration)
from forex_daytrade.features.base import Feature
from forex_daytrade.features.registry import (
    DuplicateFeatureRegistrationError,
    UnknownFeatureError,
    all_features,
    feature_names,
    get_feature,
    register_feature,
)

_EXPECTED_BASELINE_NAMES = {
    "log_return",
    "simple_return",
    "high_low_range",
    "close_open_distance",
    "body_size",
    "upper_wick",
    "lower_wick",
    "true_range",
    "rolling_std_20",
    "hour_of_day",
    "day_of_week",
    "session_placeholder",
}


def test_baseline_features_are_registered() -> None:
    assert _EXPECTED_BASELINE_NAMES <= set(feature_names())


def test_get_feature_returns_registered_class() -> None:
    assert get_feature("log_return").name == "log_return"


def test_get_feature_unknown_raises() -> None:
    with pytest.raises(UnknownFeatureError, match="not_a_real_feature"):
        get_feature("not_a_real_feature")


def test_all_features_returns_mapping_of_registered_classes() -> None:
    registered = all_features()
    assert registered["log_return"].name == "log_return"


def test_all_features_view_is_read_only() -> None:
    registered = all_features()
    with pytest.raises(TypeError):
        registered["new_entry"] = get_feature("log_return")  # type: ignore[index]


def test_register_feature_duplicate_name_raises(isolated_registry: None) -> None:
    class _Dummy(Feature):
        name = "log_return"  # collides with the real LogReturnFeature
        required_columns = frozenset({"close"})
        generated_columns = frozenset({"dummy"})

        def compute(self, df: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame(index=df.index)

    with pytest.raises(DuplicateFeatureRegistrationError, match="log_return"):
        register_feature(_Dummy)


def test_register_feature_adds_new_feature(isolated_registry: None) -> None:
    @register_feature
    class _Dummy2(Feature):
        name = "dummy_feature_for_test"
        required_columns = frozenset({"close"})
        generated_columns = frozenset({"dummy_feature_for_test"})

        def compute(self, df: pd.DataFrame) -> pd.DataFrame:
            result = pd.DataFrame(index=df.index)
            result["dummy_feature_for_test"] = df["close"]
            return result

    assert get_feature("dummy_feature_for_test") is _Dummy2


def test_registry_isolation_fixture_does_not_leak(isolated_registry: None) -> None:
    assert "should_not_leak" not in feature_names()

    @register_feature
    class _ShouldNotLeak(Feature):
        name = "should_not_leak"
        required_columns = frozenset({"close"})
        generated_columns = frozenset({"should_not_leak"})

        def compute(self, df: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame(index=df.index)

    assert "should_not_leak" in feature_names()


def test_registry_isolation_fixture_cleanup_ran(isolated_registry: None) -> None:
    """Runs after the test above under the same fixture; if isolation had
    failed, `_ShouldNotLeak` from the previous test would still be present."""
    assert "should_not_leak" not in feature_names()
