"""Shared fixtures for forex_daytrade.research tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from forex_daytrade.domain.symbol import Symbol


@pytest.fixture
def sample_symbol() -> Symbol:
    return Symbol(
        name="EURUSD",
        digits=5,
        point_size=0.00001,
        contract_size=100000.0,
        tick_value=1.0,
        min_volume=0.01,
        max_volume=100.0,
        volume_step=0.01,
    )


@pytest.fixture
def raw_market_data_df() -> pd.DataFrame:
    """25 consecutive, OHLC-valid M5 bars with a timestamp_utc + session column."""
    start = datetime(2024, 3, 4, 8, 0, tzinfo=UTC)  # Monday
    n = 25
    timestamps = [start + timedelta(minutes=5 * i) for i in range(n)]
    opens = [1.1000 + 0.0002 * i for i in range(n)]
    closes = [o + 0.0001 for o in opens]
    highs = [max(o, c) + 0.0003 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) - 0.0003 for o, c in zip(opens, closes, strict=True)]
    return pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(timestamps, utc=True),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "session": ["london"] * n,
        }
    )
