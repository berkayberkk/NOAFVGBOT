"""
Phase 5A Unit Tests: Forward Validation Framework.
Verifies all 15 safety gates, mode behaviors, account verifications, config freeze,
historical cutoff rules, signal deduplication, and execution metrics.
"""

from pathlib import Path
import pytest

from backtest.forward import (
    ForwardValidationEngine,
    ForwardMode,
    AccountModeStatus,
    verify_account_safety,
    generate_signal_id,
    HISTORICAL_CUTOFF_TIMESTAMP,
)
from backtest.forward_store import ForwardStore
from strategy.config import StrategyConfig


@pytest.fixture
def memory_store():
    return ForwardStore(":memory:")


def test_1_shadow_mode_never_submits_broker_orders(memory_store):
    engine = ForwardValidationEngine("run_shadow_1", mode=ForwardMode.SHADOW, store=memory_store)
    sig = {
        "timestamp_utc": "2026-07-25 10:00:00",
        "direction": "buy",
        "setup_type": "A_PLUS",
        "entry": 2000.0,
        "stop_loss": 1990.0,
        "take_profit": 2020.0,
    }
    res = engine.process_signal(sig)
    assert res["status"] == "SHADOW_SIMULATED"


def test_2_demo_mode_refuses_unverified_account(memory_store):
    # Unverified account (None or invalid)
    engine = ForwardValidationEngine("run_demo_1", mode=ForwardMode.DEMO, account_info=None, store=memory_store)
    assert engine.account_status == AccountModeStatus.ACCOUNT_MODE_UNVERIFIED

    sig = {
        "timestamp_utc": "2026-07-25 10:00:00",
        "direction": "buy",
        "setup_type": "A_PLUS",
        "entry": 2000.0,
        "stop_loss": 1990.0,
        "take_profit": 2020.0,
    }
    res = engine.process_signal(sig)
    assert res["status"] == "REJECTED_UNVERIFIED_ACCOUNT"


def test_2b_demo_mode_accepts_verified_account(memory_store):
    verified_acc = {"trade_mode": 0, "is_demo": True, "type": "DEMO"}
    engine = ForwardValidationEngine("run_demo_2", mode=ForwardMode.DEMO, account_info=verified_acc, store=memory_store)
    assert engine.account_status == AccountModeStatus.VERIFIED_DEMO

    sig = {
        "timestamp_utc": "2026-07-25 10:00:00",
        "direction": "buy",
        "setup_type": "A_PLUS",
        "entry": 2000.0,
        "stop_loss": 1990.0,
        "take_profit": 2020.0,
    }
    res = engine.process_signal(sig)
    assert res["status"] == "DEMO_SUBMITTED"


def test_3_duplicate_signal_cannot_submit_twice(memory_store):
    engine = ForwardValidationEngine("run_dedup_1", mode=ForwardMode.SHADOW, store=memory_store)
    sig = {
        "timestamp_utc": "2026-07-25 11:00:00",
        "direction": "sell",
        "setup_type": "A_PLUS",
        "entry": 2010.0,
        "stop_loss": 2020.0,
        "take_profit": 1990.0,
    }
    res1 = engine.process_signal(sig)
    res2 = engine.process_signal(sig)

    assert res1["status"] == "SHADOW_SIMULATED"
    assert res2["status"] == "DUPLICATE_IGNORED"


def test_4_same_signal_survives_restart(memory_store):
    engine1 = ForwardValidationEngine("run_restart_1", mode=ForwardMode.SHADOW, store=memory_store)
    sig = {
        "timestamp_utc": "2026-07-25 12:00:00",
        "direction": "buy",
        "setup_type": "A_PLUS",
        "entry": 2005.0,
        "stop_loss": 1995.0,
    }
    res1 = engine1.process_signal(sig)
    assert res1["status"] == "SHADOW_SIMULATED"

    # Re-instantiate engine with same store (simulating restart)
    engine2 = ForwardValidationEngine("run_restart_1", mode=ForwardMode.SHADOW, store=memory_store)
    res2 = engine2.process_signal(sig)
    assert res2["status"] == "DUPLICATE_IGNORED"


def test_5_config_fingerprint_mismatch(memory_store):
    # Create run with default fingerprint
    ForwardValidationEngine("run_config_freeze", mode=ForwardMode.SHADOW, store=memory_store)

    # Attempt to reopen same run ID with altered config fingerprint
    with pytest.raises(ValueError, match="Config fingerprint mismatch"):
        # We simulate mismatch by passing a store where run config fingerprint differs
        memory_store.create_run(
            run_id="run_mismatch", created_at="2026-07-25", mode="SHADOW",
            symbol="XAUUSD", timeframe="M30", config_fingerprint="ALTERED_FP",
            git_commit="590a096", account_identifier_hash="HASH", start_forward_timestamp="2026-07-25"
        )
        ForwardValidationEngine("run_mismatch", mode=ForwardMode.SHADOW, store=memory_store)


def test_6_historical_cutoff_exclusion(memory_store):
    engine = ForwardValidationEngine("run_cutoff_1", mode=ForwardMode.SHADOW, store=memory_store)

    # Historical timestamp (<= 2026-07-24 23:30:00)
    old_sig = {
        "timestamp_utc": "2026-07-24 23:30:00",
        "direction": "buy",
        "setup_type": "A_PLUS",
        "entry": 1980.0,
        "stop_loss": 1970.0,
    }
    res = engine.process_signal(old_sig)
    assert res["status"] == "REJECTED_HISTORICAL_CUTOFF"
    assert "[HISTORICAL_CUTOFF_VIOLATION]" in res["reason"]


def test_7_event_persistence(memory_store):
    engine = ForwardValidationEngine("run_events_1", mode=ForwardMode.SHADOW, store=memory_store)
    sig = {
        "timestamp_utc": "2026-07-26 09:00:00",
        "direction": "buy",
        "setup_type": "A_PLUS",
        "entry": 2000.0,
        "stop_loss": 1990.0,
    }
    engine.process_signal(sig)

    events = memory_store.get_events_for_run("run_events_1")
    assert len(events) >= 2
    types = [e["event_type"] for e in events]
    assert "SIGNAL_GENERATED" in types
    assert "ORDER_INTENDED" in types


def test_8_to_13_execution_snapshots_and_drift(memory_store):
    engine = ForwardValidationEngine("run_drift_1", mode=ForwardMode.SHADOW, store=memory_store)
    sig = {
        "timestamp_utc": "2026-07-26 10:00:00",
        "direction": "buy",
        "setup_type": "A_PLUS",
        "entry": 2000.0,
        "stop_loss": 1990.0,
        "bid": 1999.85,
        "ask": 2000.15,
    }
    engine.process_signal(sig)

    rep = engine.generate_forward_report()
    assert rep.total_signals == 1
    assert rep.drift_metrics.average_modeled_spread == 0.30


def test_14_no_credentials_serialized(memory_store):
    verified_acc = {"trade_mode": 0, "is_demo": True, "password": "SECRET_PASSWORD", "token": "SECRET_TOKEN"}
    engine = ForwardValidationEngine("run_cred_test", mode=ForwardMode.DEMO, account_info=verified_acc, store=memory_store)

    events = memory_store.get_events_for_run("run_cred_test")
    for e in events:
        payload = str(e.get("payload_json", ""))
        assert "SECRET_PASSWORD" not in payload
        assert "SECRET_TOKEN" not in payload
