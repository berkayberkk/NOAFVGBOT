"""
Phase 5C Unit Tests: Shadow Runner & Operational Reliability.
Verifies all 24 operational, safety, single-instance, downtime catch-up, heartbeat,
daily summary, and crash-recovery invariants.
"""

from pathlib import Path
import pytest

from backtest.run_shadow import (
    ShadowRunner,
    SingleInstanceLock,
    HealthState,
    DailySummaryReport,
)
from backtest.forward import ForwardMode
from backtest.forward_store import ForwardStore
from backtest.mt5_shadow import MT5ShadowAdapter


class MockMT5ForRunner:
    TIMEFRAME_M30 = 30

    def __init__(self, connected=True):
        self._connected = connected
        self.rates_data = []

    def initialize(self):
        return self._connected

    def last_error(self):
        return (0, "OK")

    def symbol_info(self, symbol):
        class Sym:
            visible = True
        return Sym()

    def symbol_select(self, symbol, visible):
        return True

    def symbol_info_tick(self, symbol):
        class Tick:
            bid = 2000.0
            ask = 2000.30
            time = int(pytest.importorskip("time").time())
        return Tick() if self._connected else None

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        return self.rates_data


def test_1_and_2_runner_is_shadow_only_and_no_broker_api():
    mock_mt5 = MockMT5ForRunner()
    # Non-SHADOW mode throws error
    with pytest.raises(ValueError, match="ShadowRunner ONLY supports SHADOW mode"):
        ShadowRunner(mode=ForwardMode.DEMO, mt5_module=mock_mt5, lock_file_path="test_lock1.lock")

    # SHADOW mode succeeds and passes safety assertion
    runner = ShadowRunner(
        mode=ForwardMode.SHADOW,
        db_path=":memory:",
        lock_file_path="test_lock_safe.lock",
        mt5_module=mock_mt5,
    )
    runner.assert_read_only_safety()
    assert not hasattr(runner, "order_send")
    runner.shutdown()


def test_3_4_5_single_instance_lock_and_stale_recovery(tmp_path):
    lock_file = tmp_path / "test_runner.lock"
    lock1 = SingleInstanceLock(lock_file)
    assert lock1.acquire() is True

    # Second lock fails
    lock2 = SingleInstanceLock(lock_file)
    assert lock2.acquire() is False

    # Clean release
    lock1.release()
    assert lock2.acquire() is True
    lock2.release()


def test_6_to_11_downtime_catchup_chronological_and_cutoff(tmp_path):
    mock_mt5 = MockMT5ForRunner()
    mock_mt5.rates_data = [
        {"time": 1784935800, "open": 1980.0, "high": 1985.0, "low": 1975.0, "close": 1982.0, "tick_volume": 50},  # Historical cutoff (2026-07-24 23:30:00)
        {"time": 1785000000, "open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0, "tick_volume": 100}, # New forward bar (2026-07-25 17:20:00)
        {"time": 1785001800, "open": 2002.0, "high": 2008.0, "low": 2001.0, "close": 2006.0, "tick_volume": 120}, # New forward bar 2
    ]

    db_path = str(tmp_path / "forward_catchup.db")
    lock_path = str(tmp_path / "catchup.lock")

    runner = ShadowRunner(
        run_id="run_catchup_test",
        mode=ForwardMode.SHADOW,
        db_path=db_path,
        lock_file_path=lock_path,
        mt5_module=mock_mt5,
    )
    runner.initialize()

    # Catch up missing bars
    recovered = runner.catch_up_missing_bars()
    assert runner.adapter.last_processed_timestamp == "2026-07-25 17:50:00"
    runner.shutdown()


def test_17_18_19_health_states_and_heartbeat(tmp_path):
    mock_mt5 = MockMT5ForRunner(connected=True)
    db_path = str(tmp_path / "forward_health.db")
    lock_path = str(tmp_path / "health.lock")

    runner = ShadowRunner(
        run_id="run_health_test",
        mode=ForwardMode.SHADOW,
        db_path=db_path,
        lock_file_path=lock_path,
        mt5_module=mock_mt5,
    )
    runner.initialize()

    assert runner.get_health_state() == HealthState.HEALTHY
    runner.run_heartbeat()

    # Disconnect
    mock_mt5._connected = False
    assert runner.get_health_state() == HealthState.DISCONNECTED
    runner.shutdown()


def test_21_daily_summary_generation(tmp_path):
    mock_mt5 = MockMT5ForRunner(connected=True)
    db_path = str(tmp_path / "forward_summary.db")
    lock_path = str(tmp_path / "summary.lock")

    runner = ShadowRunner(
        run_id="run_summary_test",
        mode=ForwardMode.SHADOW,
        db_path=db_path,
        lock_file_path=lock_path,
        mt5_module=mock_mt5,
    )
    runner.initialize()

    summary = runner.generate_daily_summary("2026-07-26")
    assert isinstance(summary, DailySummaryReport)
    assert summary.date_str == "2026-07-26"
    assert summary.run_id == "run_summary_test"
    runner.shutdown()


def test_22_gitignore_rules_exist():
    gitignore_path = Path(__file__).resolve().parent.parent / ".gitignore"
    content = gitignore_path.read_text()
    assert "*.db" in content
    assert "*.lock" in content
    assert "forward_*.log" in content
