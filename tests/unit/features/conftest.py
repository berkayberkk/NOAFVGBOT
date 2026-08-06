"""Shared fixtures for forex_daytrade.features tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from forex_daytrade.features import registry


@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    """Five consecutive M5 bars with a realistic OHLCV + timestamp/session shape."""
    start = datetime(2024, 3, 4, 8, 0, tzinfo=UTC)  # Monday
    timestamps = [start + timedelta(minutes=5 * i) for i in range(5)]
    return pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(timestamps, utc=True),
            "symbol": ["EURUSD"] * 5,
            "open": [1.1000, 1.1010, 1.1005, 1.1012, 1.1015],
            "high": [1.1020, 1.1025, 1.1018, 1.1030, 1.1025],
            "low": [1.0995, 1.1000, 1.0995, 1.1010, 1.1005],
            "close": [1.1010, 1.1005, 1.1012, 1.1015, 1.1022],
            "tick_volume": [100, 120, 90, 150, 110],
            "session": ["london"] * 5,
        }
    )


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot and restore the global feature registry around a test.

    Any registration performed during the test happens on a private copy of
    `registry._REGISTRY`; monkeypatch restores the original dict afterward,
    so tests that register throwaway features never leak into other tests.
    """
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
