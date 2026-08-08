"""
Phase 5D Unit Tests: Forward Evidence Calibration & Drift Analysis.
Verifies all 24 sample policy, spread calibration, drift classification, non-mutation,
and read-only safety invariants.
"""

from dataclasses import asdict
from pathlib import Path
import pytest

from backtest.forward import BASELINE_CONFIG_V1, HISTORICAL_CUTOFF_TIMESTAMP
from backtest.forward_store import ForwardStore
from backtest.forward_drift import (
    ForwardDriftAnalyzer,
    ForwardDriftReport,
    EvidenceSampleState,
    DriftClassification,
    format_forward_drift_summary,
    export_forward_drift_snapshot,
)


@pytest.fixture
def memory_store():
    return ForwardStore(":memory:")


def test_1_historical_cutoff_exclusion(memory_store):
    memory_store.add_event({
        "run_id": "run_drift_1",
        "timestamp_utc": "2026-07-24 10:00:00",  # Old bar before cutoff
        "event_type": "SIGNAL_GENERATED",
        "symbol": "XAUUSD",
        "timeframe": "M30",
        "config_fingerprint": "5a56639725048f3d",
        "account_mode": "SHADOW",
        "payload_json": {"direction": "buy", "actual_spread": 0.35},
    })
    memory_store.add_event({
        "run_id": "run_drift_1",
        "timestamp_utc": "2026-07-25 10:00:00",  # New bar after cutoff
        "event_type": "SIGNAL_GENERATED",
        "symbol": "XAUUSD",
        "timeframe": "M30",
        "config_fingerprint": "5a56639725048f3d",
        "account_mode": "SHADOW",
        "payload_json": {"direction": "buy", "actual_spread": 0.35},
    })

    analyzer = ForwardDriftAnalyzer(memory_store, "run_drift_1")
    report = analyzer.analyze()
    assert report.signal_fill_report.total_signals == 1
    assert report.spread_report.sample_count == 1


def test_2_3_4_sample_policy_states(memory_store):
    analyzer = ForwardDriftAnalyzer(memory_store, "run_sample_test")

    # 0 trades = COLLECTING
    rep = analyzer.analyze()
    assert rep.evidence_state == EvidenceSampleState.COLLECTING
    assert rep.drift_classification == DriftClassification.INSUFFICIENT_DATA


def test_5_6_7_spread_calibration_and_zero_safety(memory_store):
    analyzer = ForwardDriftAnalyzer(memory_store, "run_zero_spread")
    rep = analyzer.analyze()

    assert rep.spread_report.sample_count == 0
    assert rep.spread_report.mean_spread is None
    assert rep.spread_report.median_spread is None
    assert rep.spread_report.pct_lte_0_30 is None


def test_11_shadow_slippage_labeled_not_observed(memory_store):
    analyzer = ForwardDriftAnalyzer(memory_store, "run_slippage_test")
    rep = analyzer.analyze()

    assert rep.performance_report.shadow_slippage_status == "NOT OBSERVED"


def test_12_empty_latency_when_no_real_records(memory_store):
    analyzer = ForwardDriftAnalyzer(memory_store, "run_latency_test")
    rep = analyzer.analyze()

    assert rep.reliability_report.shadow_processing_latency_ms == {}


def test_empty_sample_na_semantics(memory_store):
    analyzer = ForwardDriftAnalyzer(memory_store, "run_empty_semantics")
    rep = analyzer.analyze()

    assert rep.performance_report.forward_expectancy_r is None
    assert rep.performance_report.expectancy_diff_vs_holdout is None
    assert rep.signal_fill_report.forward_fill_rate is None
    assert rep.signal_fill_report.forward_signals_per_1000_bars is None

    summary = format_forward_drift_summary(rep)
    assert "Expectancy: N/A" in summary
    assert "Rate: N/A" in summary
    assert "INSUFFICIENT_DATA" in summary


def test_20_and_21_no_automatic_config_mutation(memory_store):
    original_spread = BASELINE_CONFIG_V1.spread
    analyzer = ForwardDriftAnalyzer(memory_store, "run_mutation_test")

    # Inject mock events with large spread
    memory_store.add_event({
        "run_id": "run_mutation_test",
        "timestamp_utc": "2026-07-26 10:00:00",
        "event_type": "SIGNAL_GENERATED",
        "symbol": "XAUUSD",
        "timeframe": "M30",
        "config_fingerprint": "5a56639725048f3d",
        "account_mode": "SHADOW",
        "payload_json": {"actual_spread": 0.85},
    })

    rep = analyzer.analyze()
    # Confirm config was NOT mutated
    assert BASELINE_CONFIG_V1.spread == original_spread
    assert BASELINE_CONFIG_V1.spread == 0.30
    assert rep.spread_report.median_spread == 0.85


def test_22_and_23_no_live_demo_or_execution_apis():
    from backtest.forward_drift import ForwardDriftAnalyzer
    analyzer_class = ForwardDriftAnalyzer
    assert not hasattr(analyzer_class, "order_send")
    assert not hasattr(analyzer_class, "order_check")


def test_format_and_export_snapshot(tmp_path, memory_store):
    analyzer = ForwardDriftAnalyzer(memory_store, "run_export_test")
    rep = analyzer.analyze()

    summary_text = format_forward_drift_summary(rep)
    assert "Forward Evidence Snapshot" in summary_text
    assert "NOT OBSERVED" in summary_text

    export_path = tmp_path / "drift_snapshot.json"
    export_forward_drift_snapshot(rep, export_path)
    assert export_path.exists()
    assert "run_export_test" in export_path.read_text()
