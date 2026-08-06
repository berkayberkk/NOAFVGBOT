"""Unit tests for forex_daytrade.data.mt5_client.

The MetaTrader5 package is Windows-only and not installed in this test
environment (nor available on CI); every test here injects a fake module
into `sys.modules` so the client's lazy import picks it up instead of the
real package. No MT5 terminal is required.
"""

import sys
from datetime import UTC, datetime
from typing import Any

import pytest

from forex_daytrade.data.exceptions import (
    MT5ConnectionError,
    MT5NotAvailableError,
    SymbolNotFoundError,
)
from forex_daytrade.data.mt5_client import MT5Client
from forex_daytrade.data.types import IngestionTimeframe


class FakeMT5:
    """Minimal stand-in for the MetaTrader5 module."""

    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385

    def __init__(self) -> None:
        self.initialize_result = True
        self.known_symbols = {"EURUSD"}
        self.rates: list[dict[str, Any]] = [
            {
                "time": 1700000000,
                "open": 1.10,
                "high": 1.12,
                "low": 1.08,
                "close": 1.11,
                "tick_volume": 100,
                "spread": 10,
                "real_volume": 0,
            }
        ]
        self.shutdown_calls = 0
        self.initialize_calls: list[dict[str, Any]] = []

    def initialize(self, **kwargs: Any) -> bool:
        self.initialize_calls.append(kwargs)
        return self.initialize_result

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def last_error(self) -> tuple[int, str]:
        return (1, "generic failure")

    def symbol_info(self, symbol: str) -> object | None:
        return object() if symbol in self.known_symbols else None

    def copy_rates_range(
        self, symbol: str, timeframe: int, date_from: datetime, date_to: datetime
    ) -> list[dict[str, Any]] | None:
        if symbol not in self.known_symbols:
            return None
        return self.rates


@pytest.fixture
def fake_mt5(monkeypatch: pytest.MonkeyPatch) -> FakeMT5:
    module = FakeMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)
    return module


def test_initialize_success(fake_mt5: FakeMT5) -> None:
    client = MT5Client()
    client.initialize()
    assert client.is_connected
    assert fake_mt5.initialize_calls == [{}]


def test_initialize_passes_terminal_path(fake_mt5: FakeMT5) -> None:
    client = MT5Client(terminal_path="C:/MT5/terminal64.exe")
    client.initialize()
    assert fake_mt5.initialize_calls == [{"path": "C:/MT5/terminal64.exe"}]


def test_initialize_failure_raises(fake_mt5: FakeMT5) -> None:
    fake_mt5.initialize_result = False
    client = MT5Client()
    with pytest.raises(MT5ConnectionError):
        client.initialize()
    assert not client.is_connected


def test_shutdown_when_not_connected_is_a_no_op(fake_mt5: FakeMT5) -> None:
    client = MT5Client()
    client.shutdown()
    assert fake_mt5.shutdown_calls == 0


def test_shutdown_after_initialize(fake_mt5: FakeMT5) -> None:
    client = MT5Client()
    client.initialize()
    client.shutdown()
    assert not client.is_connected
    assert fake_mt5.shutdown_calls == 1


def test_reconnect(fake_mt5: FakeMT5) -> None:
    client = MT5Client()
    client.initialize()
    client.reconnect()
    assert client.is_connected
    assert fake_mt5.shutdown_calls == 1
    assert len(fake_mt5.initialize_calls) == 2


def test_symbol_exists(fake_mt5: FakeMT5) -> None:
    client = MT5Client()
    client.initialize()
    assert client.symbol_exists("EURUSD") is True
    assert client.symbol_exists("GBPUSD") is False


def test_copy_rates_range_returns_dataframe(fake_mt5: FakeMT5) -> None:
    client = MT5Client()
    client.initialize()
    df = client.copy_rates_range(
        "EURUSD",
        IngestionTimeframe.M5,
        datetime(2023, 11, 1, tzinfo=UTC),
        datetime(2023, 11, 2, tzinfo=UTC),
    )
    assert len(df) == 1
    assert df.loc[0, "close"] == 1.11


def test_copy_rates_range_requires_initialize(fake_mt5: FakeMT5) -> None:
    client = MT5Client()
    with pytest.raises(MT5ConnectionError):
        client.copy_rates_range(
            "EURUSD",
            IngestionTimeframe.M5,
            datetime(2023, 11, 1, tzinfo=UTC),
            datetime(2023, 11, 2, tzinfo=UTC),
        )


def test_copy_rates_range_unknown_symbol_raises(fake_mt5: FakeMT5) -> None:
    client = MT5Client()
    client.initialize()
    with pytest.raises(SymbolNotFoundError):
        client.copy_rates_range(
            "GBPUSD",
            IngestionTimeframe.M5,
            datetime(2023, 11, 1, tzinfo=UTC),
            datetime(2023, 11, 2, tzinfo=UTC),
        )


def test_context_manager_initializes_and_shuts_down(fake_mt5: FakeMT5) -> None:
    with MT5Client() as client:
        assert client.is_connected
    assert not client.is_connected
    assert fake_mt5.shutdown_calls == 1


def test_mt5_not_available_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    client = MT5Client()
    with pytest.raises(MT5NotAvailableError):
        client.initialize()
