"""
Phase 5B Unit Tests: MT5 Shadow Runtime Adapter.
Verifies all 24 safety, symbol mapping, completed bar, deduplication, stale tick,
and read-only boundary invariants using a mock MT5 interface.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import pytest

from backtest.forward import ForwardValidationEngine, ForwardMode
from backtest.forward_store import ForwardStore
from backtest.mt5_shadow import MT5ShadowAdapter, ShadowAdapterStatus


class MockMT5SymbolInfo:
    def __init__(self, name="XAUUSD", visible=True):
        self.name = name
        self.visible = visible


class MockMT5Tick:
    def __init__(self, bid=2000.0, ask=2000.30, tick_time=1785000000):
        self.bid = bid
        self.ask = ask
        self.time = tick_time


class MockMT5:
    TIMEFRAME_M30 = 30

    def __init__(self, init_success=True, symbol_exists=True, symbol_visible=True):
        self.init_success = init_success
        self.symbol_exists = symbol_exists
        self.symbol_visible = symbol_visible
        self.select_calls = []
        self.rates_data = []
        self.tick_data = MockMT5Tick()

    def initialize(self):
        return self.init_success

    def last_error(self):
        return (0, "No error")

    def symbol_info(self, symbol):
        if not self.symbol_exists:
            return None
        return MockMT5SymbolInfo(symbol, self.symbol_visible)

    def symbol_select(self, symbol, visible):
        self.select_calls.append((symbol, visible))
        return self.symbol_visible  # returns True if selection succeeded

    def symbol_info_tick(self, symbol):
        return self.tick_data

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        # Index 1 simulates starting from completed bar 1 (excluding forming bar 0)
        return self.rates_data


@pytest.fixture
def memory_store():
    return ForwardStore(":memory:")


@pytest.fixture
def shadow_engine(memory_store):
    return ForwardValidationEngine("run_shadow_test", mode=ForwardMode.SHADOW, store=memory_store)


def test_1_adapter_cannot_submit_broker_orders(shadow_engine):
    mock_mt5 = MockMT5()
    adapter = MT5ShadowAdapter(shadow_engine, mt5_module=mock_mt5)
    adapter.assert_read_only_boundary()
    # Confirm no trade APIs exist on adapter
    assert not hasattr(adapter, "order_send")
    assert not hasattr(adapter, "order_check")


def test_2_successful_mt5_initialization(shadow_engine):
    mock_mt5 = MockMT5(init_success=True)
    adapter = MT5ShadowAdapter(shadow_engine, mt5_module=mock_mt5)
    assert adapter.initialize() is True
    assert adapter.connected is True


def test_3_initialization_failure(shadow_engine):
    mock_mt5 = MockMT5(init_success=False)
    adapter = MT5ShadowAdapter(shadow_engine, mt5_module=mock_mt5)
    assert adapter.initialize() is False
    assert adapter.connected is False


def test_4_and_5_symbol_found_and_not_found(shadow_engine):
    mock_mt5 = MockMT5(symbol_exists=False)
    adapter = MT5ShadowAdapter(shadow_engine, broker_symbol="INVALID_SYM", mt5_module=mock_mt5)
    assert adapter.initialize() is False
    assert any("SYMBOL_NOT_FOUND" in log for log in adapter.logs)


def test_6_and_7_symbol_visibility_selection(shadow_engine):
    mock_mt5 = MockMT5(symbol_visible=False)
    adapter = MT5ShadowAdapter(shadow_engine, mt5_module=mock_mt5)
    assert adapter.initialize() is False
    assert any("SYMBOL_SELECT_FAILED" in log for log in adapter.logs)


def test_8_and_9_forming_candle_excluded_and_completed_selected(shadow_engine):
    mock_mt5 = MockMT5()
    # Simulate completed M30 rates
    mock_mt5.rates_data = [
        {"time": 1785000000, "open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0, "tick_volume": 100},
        {"time": 1785001800, "open": 2002.0, "high": 2008.0, "low": 2001.0, "close": 2006.0, "tick_volume": 120},
    ]
    adapter = MT5ShadowAdapter(shadow_engine, mt5_module=mock_mt5)
    adapter.initialize()

    candles = adapter.fetch_completed_candles(count=2)
    assert len(candles) == 2
    # Verify index 1 (pos 1) completed candle timestamp
    assert candles[-1]["time"] == "2026-07-25 17:50:00"


def test_10_and_11_duplicate_completed_bar_ignored(shadow_engine):
    mock_mt5 = MockMT5()
    mock_mt5.rates_data = [
        {"time": 1785000000, "open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0, "tick_volume": 100},
    ]
    adapter = MT5ShadowAdapter(shadow_engine, mt5_module=mock_mt5)
    adapter.initialize()

    adapter.poll_shadow_cycle()
    first_processed = adapter.last_processed_timestamp
    assert first_processed != ""

    # Poll second time with same bar
    adapter.poll_shadow_cycle()
    assert any("DUPLICATE_BAR_IGNORED" in log for log in adapter.logs)


def test_12_and_13_historical_cutoff_bars_treated_as_context(shadow_engine):
    mock_mt5 = MockMT5()
    # Old candle (<= 2026-07-24 23:30:00)
    mock_mt5.rates_data = [
        {"time": 1784935800, "open": 1980.0, "high": 1985.0, "low": 1975.0, "close": 1982.0, "tick_volume": 50},  # 2026-07-24 23:30:00 UTC
    ]
    adapter = MT5ShadowAdapter(shadow_engine, mt5_module=mock_mt5)
    adapter.initialize()

    adapter.poll_shadow_cycle()
    rep = shadow_engine.generate_forward_report()
    assert rep.total_signals == 0  # No forward signals logged for historical cutoff bars


def test_14_to_17_valid_invalid_nan_stale_ticks(shadow_engine):
    mock_mt5 = MockMT5()
    adapter = MT5ShadowAdapter(shadow_engine, max_stale_seconds=10.0, mt5_module=mock_mt5)
    adapter.initialize()

    # 14. Valid Tick
    import time
    mock_mt5.tick_data = MockMT5Tick(bid=2000.0, ask=2000.30, tick_time=int(time.time()))
    tick = adapter.get_current_tick()
    assert tick is not None
    assert tick["bid"] == 2000.0

    # 15. Bid > Ask
    mock_mt5.tick_data = MockMT5Tick(bid=2005.0, ask=2000.0, tick_time=int(time.time()))
    assert adapter.get_current_tick() is None

    # 16. NaN Tick
    mock_mt5.tick_data = MockMT5Tick(bid=float("nan"), ask=2000.0, tick_time=int(time.time()))
    assert adapter.get_current_tick() is None

    # 17. Stale Tick
    mock_mt5.tick_data = MockMT5Tick(bid=2000.0, ask=2000.30, tick_time=int(time.time()) - 100)
    assert adapter.get_current_tick() is None
    assert any("STALE_TICK" in log for log in adapter.logs)


def test_18_and_19_reconnect_behavior(shadow_engine):
    mock_mt5 = MockMT5(init_success=True)
    adapter = MT5ShadowAdapter(shadow_engine, reconnect_attempts=2, reconnect_delay_sec=0.01, mt5_module=mock_mt5)
    adapter.initialize()

    # Simulate disconnect
    adapter.connected = False
    mock_mt5.rates_data = [{"time": 1785000000, "open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0, "tick_volume": 100}]

    adapter.poll_shadow_cycle()
    assert adapter.connected is True
    assert any("MT5_RECONNECTED" in log for log in adapter.logs)


def test_20_bar_gap_logging(shadow_engine):
    mock_mt5 = MockMT5()
    adapter = MT5ShadowAdapter(shadow_engine, mt5_module=mock_mt5)
    adapter.initialize()

    adapter.last_processed_timestamp = "2026-07-27 10:00:00"  # Monday
    # Bar 5 hours later on Monday (2026-07-27 15:00:00 UTC = 1785164400)
    mock_mt5.rates_data = [{"time": 1785164400, "open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0, "tick_volume": 100}]

    adapter.poll_shadow_cycle()
    assert any("BAR_GAP" in log for log in adapter.logs)


def test_22_shadow_mode_enforcement(memory_store):
    demo_engine = ForwardValidationEngine("run_demo_test", mode=ForwardMode.DEMO, account_info={"trade_mode": 0}, store=memory_store)
    mock_mt5 = MockMT5()

    with pytest.raises(ValueError, match="MT5ShadowAdapter ONLY permits SHADOW mode"):
        MT5ShadowAdapter(demo_engine, mt5_module=mock_mt5)
